"""
The change detector's state (and the slow levels of the machine's model), kept on the device row.

The anomaly model's change detector (services/change_detector.py) accumulates small deviations over time for each machine. Its
state has to survive between readings and be the same for every worker or a worker that sees only some of a machine's readings
would reset on every gap. DbStateStore backs ml_service's state store (get and put by str(device_id)) with `devices.detector_state`.

- where: a JSONB column beside stuck_state. It is read and written on the Device object the ingest post has already locked
  (row lock, then advisory lock), so two posts cannot interleave and there is no extra query
- when: the scorer is called and the state written, once per scored LIVE reading. A backlog reading is never scored, so it never
  touches the state (routes/telemetry.py _build_item)
- outside a post (no session in context: a manual score, a test, the evaluation) the store falls back to process memory
- bounded: a stored state over MAX_BYTES or one that does not parse or holds a number that is not finite, is refused. It is
  logged, replaced with nothing (a fresh detector) and never raises, so a damaged state can cost a few minutes of the detector's warm
  up and never a reading
- tied to its model: the state carries the id of the model that wrote it and ml_service starts a fresh one when another model
  scores the machine, so a retrain that changed the columns can never feed an old state to a new model
- carried across a retrain (ml_service.carry_state) and cleared only when an admin accepts a new counter for the machine or its
  key is rotated (the hardware may be new). clear_all stays for an operator who wants every machine to start cold. A long silence needs no clearing: the detector resets itself after a gap
- paused in a maintenance window: paused(key, t) says whether the machine is in one at t, so the scorer stops stepping and the
  detector starts a fresh warm-up when the window ends. It is one indexed query on the post's own session
- shared: two workers posting for one machine read and write the column under the device row lock the post holds, one after
  the other. tests/test_detector_store.py runs that with two separate processes
"""

import contextlib
import contextvars
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import or_, update

from app.models.device import Device
from app.models.maintenance import MaintenanceWindow
from app.services import change_detector as cd

logger = logging.getLogger(__name__)

# about 3 kB for a machine of 11 sensors and four operating states, so 16 kB leaves room for 23 sensors
MAX_BYTES = 16384
_session: contextvars.ContextVar = contextvars.ContextVar("detector_session", default=None)


@contextlib.contextmanager
def use(db):
    """Make `db` the session the store reads and writes through, for the code inside the block."""
    token = _session.set(db)
    try:
        yield
    finally:
        _session.reset(token)


def _finite(value) -> bool:
    if isinstance(value, list):
        return all(_finite(v) for v in value)
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value))


# the one field that is text: the id of the model that wrote the state
_TEXT_FIELDS = {"model_id"}


def _valid_basis(value) -> bool:
    if value is None:
        return True
    return (isinstance(value, dict) and set(value) <= {"cols", "center", "scale", "boundary"}
            and all(isinstance(c, str) and len(c) <= 64 for c in value.get("cols") or [])
            and all(_finite(value.get(k)) for k in ("center", "scale", "boundary")))


def _valid(data) -> bool:
    if not isinstance(data, dict):
        return False
    for k, v in data.items():
        if k in _TEXT_FIELDS:
            if not (v is None or (isinstance(v, str) and len(v) <= 64)):
                return False
        elif k == "basis":
            if not _valid_basis(v):
                return False
        elif k == "cold":
            if not isinstance(v, bool):
                return False
        elif not _finite(v):
            return False
    return True


def _device(db, key):
    try:
        return db.get(Device, UUID(str(key)))
    except (ValueError, TypeError):
        return None


class DbStateStore:
    def __init__(self, fallback=None):
        self.fallback = fallback if fallback is not None else cd.MemoryStateStore()

    def get(self, key):
        db = _session.get()
        if db is None:
            return self.fallback.get(key)
        device = _device(db, key)
        if device is None or not device.detector_state:
            return None
        raw = device.detector_state
        try:
            if len(json.dumps(raw)) > MAX_BYTES or not _valid(raw):
                raise ValueError("not a detector state")
            return cd.DetectorState.from_dict(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("a stored change detector state was refused and replaced with a fresh one (%s)", type(exc).__name__)
            device.detector_state = None
            return None

    def put(self, key, state) -> None:
        db = _session.get()
        if db is None:
            self.fallback.put(key, state)
            return
        device = _device(db, key)
        if device is None:
            return
        data = state.to_dict()
        if len(json.dumps(data)) > MAX_BYTES or not _valid(data):
            logger.warning("a change detector state was too large or not finite and was not stored")
            device.detector_state = None
            return
        # a new dict each time, so the change is seen
        device.detector_state = data

    def ambient(self, key, t: float) -> float | None:
        """
        The machine's site reference at epoch time t: the newest air temperature its ambient source posted at most
        training_data.AMBIENT_MAX_AGE_S before t or None (no source set or it has not posted recently).
        """
        db = _session.get()
        if db is None:
            return None
        device = _device(db, key)
        source = getattr(device, "ambient_source_id", None) if device is not None else None
        if source is None:
            return None
        from app.models.telemetry import Telemetry
        from app.services.training_data import AMBIENT_MAX_AGE_S
        at = datetime.fromtimestamp(float(t), tz=timezone.utc)
        row = (db.query(Telemetry.temperature)
               .filter(Telemetry.device_id == source, Telemetry.temperature.isnot(None),
                       Telemetry.recorded_at <= at, Telemetry.recorded_at >= at - timedelta(seconds=AMBIENT_MAX_AGE_S))
               .order_by(Telemetry.recorded_at.desc()).first())
        return None if row is None else float(row[0])

    def paused(self, key, t: float) -> bool:
        """True when the machine is in a maintenance window (its own or a fleet-wide one) at epoch time t."""
        db = _session.get()
        if db is None:
            return False
        try:
            device_id = UUID(str(key))
        except (ValueError, TypeError):
            return False
        at = datetime.fromtimestamp(float(t), tz=timezone.utc)
        return db.query(MaintenanceWindow.id).filter(
            MaintenanceWindow.start_at <= at, MaintenanceWindow.end_at >= at,
            MaintenanceWindow.suppress_alerts.is_(True),
            or_(MaintenanceWindow.device_id == device_id, MaintenanceWindow.device_id.is_(None)),
        ).first() is not None


def clear_device(db, device_id) -> None:
    """Forget one machine's state: the next reading starts a fresh detector."""
    device = _device(db, device_id)
    if device is not None:
        device.detector_state = None


def clear_all(db) -> int:
    """Forget every machine's state, after a retrain: the new model's detector starts from nothing. Returns rows changed."""
    result = db.execute(update(Device).where(Device.detector_state.isnot(None)).values(detector_state=None))
    db.commit()
    return result.rowcount or 0
