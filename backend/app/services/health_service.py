"""
Health Service - the ingest side of node health.

Jobs, all run from the telemetry post:
- apply_faults stops a faulted sensor: its fields are nulled before anything reads them and the rejected value
  is kept for diagnosis.
- record_health keeps the node's latest vitals in device_health, notices lost posts and restarts and runs the
  sensor fault alerts (one stateful monitoring alert per device and sensor).
- track_scoring raises one monitoring alert when a node that is posting has no scored reading for ten minutes.
- raise_reset_loop_alert opens one monitoring alert when a node keeps restarting.

The silent-node side lives in liveness_service.py.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.device import Device
from app.models.device_health import (
    BOOT_HISTORY_KEEP,
    DeviceHealth,
    RESET_LOOP_BOOTS,
    RESET_LOOP_WINDOW,
)
from app.services.maintenance_service import is_in_maintenance
from app.schemas.telemetry import DROPPED_FIELDS, HEALTH_FIELDS, TelemetryIngest
from app.services import alert_service, ml_service, stuck_sensors
from app.services.alert_state import add_alert, lock_device  # noqa: F401  (shared helpers, kept importable from here)
from app.services.sensor_map import (
    FIELD_SENSOR, QUIET_STATES, SENSOR_FIELDS, STATE_WORDS, canonical_key, faulted_fields, state_fields,
)

logger = logging.getLogger(__name__)

# alert messages end in these, so an open alert of each kind can be found after the device is renamed
RESET_LOOP_SUFFIX = f"has restarted {RESET_LOOP_BOOTS} times in {int(RESET_LOOP_WINDOW.total_seconds() // 60)} minutes"
UNSCORED_SUFFIX = "has had no scored reading for 10 minutes"
_MAX_BOOT_EVENTS = 20

# a fault must be reported without a break for this long before it raises an alert and a sensor must report ok (or
# leave the fault map) for this long before the alert resolves
FAULT_ALERT_AFTER_S = 60
FAULT_CLEAR_AFTER_S = 60
# a sensor that changes between ok and a fault more than this many times in an hour is intermittent
FLAP_LIMIT = 5
FLAP_WINDOW = timedelta(hours=1)
# a node that is posting but has no scored reading for this long raises an alert
UNSCORED_ALERT_AFTER_S = 600


# at most this many sensor keys that are not in the sensor map are tracked for one device, so a node that names new keys
# in every post cannot make the tracking record grow. A fault on such a key is still stored for display
MAX_UNKNOWN_TRACKED = 4
# the state changes kept per sensor. Intermittent needs more than FLAP_LIMIT of them, so a few more than that is plenty
MAX_FLIPS_KEPT = FLAP_LIMIT + 3
# the vibration clipping alert resolves after this long without a clipping reading
CLIPPING_CLEAR_AFTER_S = 60


def open_sensor_alert_keys(db: Session, device: Device) -> set[str]:
    """The sensors that have an open sensor-fault alert now: the only ones a node's own claim may stop."""
    rows = (
        db.query(Alert.sensor_key)
        .filter(Alert.device_id == device.id, Alert.kind == "sensor", Alert.resolved.is_(False))
        .all()
    )
    return {canonical_key(key) for (key,) in rows if key}


def stoppable_sensors(db: Session, device: Device) -> set[str]:
    """
    The sensors whose fields a node's fault claim may stop: those with an open sensor-fault alert and those an admin marked as
    not fitted. What a node says about itself must not be able to hide the machine: a claim with no alert behind it stops
    nothing, so the rules keep judging the value and an attacker holding a key cannot silence a rule without leaving an open
    alert that says why. The firmware's own not-fitted list is display only and does not widen this.
    """
    return open_sensor_alert_keys(db, device) | {canonical_key(k) for k in device.not_fitted or []}


def apply_faults(
    reading: dict, faults: dict[str, str] | None, allowed: set[str] | None = None,
) -> tuple[dict, dict | None, set[str]]:
    """
    Stop the sensors a post names as faulted, when they may be stopped.

    `allowed` is the set of sensor keys whose claim counts (see stoppable_sensors). A claim for any other sensor is recorded in
    the quality record as "not_applied" and stops nothing. None means every claim counts, which only the unit tests use.

    Returns the reading with every field of those sensors set to None, the quality record to store with the row
    (None when there is no fault) and the set of fields that were stopped. A value the node did send for a
    stopped field is kept in the record under "rejected". Alert rules read the returned reading, so none can
    fire on a stopped field and the model sees a missing feature and does not score the row.
    """
    if not faults:
        return reading, None, set()
    counted = faults if allowed is None else {k: v for k, v in faults.items() if canonical_key(k) in allowed}
    stopped = faulted_fields(counted)
    cleaned = {field: (None if field in stopped else value) for field, value in reading.items()}
    rejected = {field: reading[field] for field in stopped if reading.get(field) is not None}
    quality: dict = {"faults": dict(faults)}
    # a claim that would have stopped a value and did not (no open alert behind it) is noted, so the row explains why the value
    # is there
    not_counted = {k: v for k, v in faults.items() if k not in counted}
    if any(reading.get(f) is not None for f in faulted_fields(not_counted)):
        quality["not_applied"] = sorted(not_counted)
    if rejected:
        quality["rejected"] = rejected
    return cleaned, quality, stopped


@dataclass
class HealthResult:
    stored: bool = False
    # posts missed since the last one, from a jump in the sequence number
    lost: int = 0
    reset_loop: bool = False
    # monitoring emails to send after the commit, as (kind, message)
    notify: list = field(default_factory=list)
    # true when the sensor fault alerts were run from this post's fault map
    tracked: bool = False


def _aware(when: datetime | None) -> datetime | None:
    if when is not None and when.tzinfo is None:
        return when.replace(tzinfo=timezone.utc)
    return when


def _parse(stamp) -> datetime | None:
    try:
        return _aware(datetime.fromisoformat(stamp))
    except (TypeError, ValueError):
        return None


def _recent(stamps, cutoff: datetime) -> list[str]:
    return [s for s in stamps or [] if (when := _parse(s)) is not None and when >= cutoff]


# how long a sensor alert that was resolved by hand while its fault goes on is left alone before it is raised again, as a new
# alert that says the earlier one was resolved by hand. The same wait holds a silent-node or restart-loop alert back
HAND_RESOLVED_HOLD_S = 3600
HAND_RESOLVED_SUFFIX = " (resolved by hand)"
BOARD_MISMATCH_TEXT = "the firmware image does not match this board"


def effective_not_fitted(device: Device, row: DeviceHealth | None) -> set[str]:
    """
    The sensor keys that are not expected on this machine: the admin's own list and the keys the firmware says it was built
    without. Both are kept apart where they are stored and returned. A fault on one of them raises no alert and the
    machine is not made unknown by it.
    """
    keys = {canonical_key(k) for k in device.not_fitted or []}
    if row is not None:
        keys |= {canonical_key(k) for k in row.not_fitted_by_firmware or []}
    return keys


def fault_message(device_name: str, key: str, state: str, flips: int = 0, intermittent: bool = False) -> str:
    """The text of a sensor fault alert, in plain words."""
    if intermittent:
        return (
            f"{device_name}: sensor {key} is intermittent "
            f"(it changed between working and faulty {flips} times in the last hour)"
        )
    return f"{device_name}: sensor {key} is {STATE_WORDS.get(state, STATE_WORDS['unknown'])} ({state})"


def _open_sensor_alert(db: Session, device_id, key: str) -> Alert | None:
    return (
        db.query(Alert)
        .filter(
            Alert.device_id == device_id,
            Alert.category == "monitoring",
            Alert.sensor_key == key,
            Alert.resolved.is_(False),
        )
        .first()
    )


def _track_sensor_faults(
    db: Session, device: Device, row: DeviceHealth, now: datetime, result: HealthResult, server: dict[str, str] | None = None,
) -> None:
    """
    Run the sensor fault alerts from the fault map the row now holds.

    A fault must be reported without a break for FAULT_ALERT_AFTER_S before an alert opens. One open alert exists
    per device and sensor: it is updated when the state changes and never duplicated. It resolves once the sensor
    has reported ok or been left out of the map, for FAULT_CLEAR_AFTER_S. A sensor that changes state more than
    FLAP_LIMIT times in an hour gets one alert that says it is intermittent, at once and not after a minute and
    that alert stays until the sensor has also been quiet. A sensor the admin marked as not fitted and the two
    states that are not a failure, raise nothing. No alert opens while the machine is in a maintenance window.
    """
    not_fitted = effective_not_fitted(device, row)
    # what the server found itself (a value outside what the part can measure, a value that stopped moving) goes through the same
    # alerts as a fault the node reports. The node's own word wins for a sensor it names
    merged = {**(server or {}), **(row.faults or {})}
    active = {
        k: v for k, v in merged.items()
        if k not in not_fitted and v not in QUIET_STATES
    }
    result.tracked = True
    # a fault only the server found (an impossible value, a stuck value) is not counted as a change between faulty and fine. A
    # corrupted frame now and then is not an intermittent sensor and the one minute the fault must last is the debounce
    server_only = {k for k in (server or {}) if k not in (row.faults or {})}
    track = {k: dict(v) for k, v in (row.sensor_track or {}).items()}
    cutoff = now - FLAP_WINDOW
    in_maintenance = None

    # bounded: every key in the sensor map and a few that are not. A key already tracked keeps its place
    unknown = {k for k in track if k not in SENSOR_FIELDS}
    for key in active:
        if key not in SENSOR_FIELDS and key not in unknown and len(unknown) < MAX_UNKNOWN_TRACKED:
            unknown.add(key)
    active = {k: v for k, v in active.items() if k in SENSOR_FIELDS or k in unknown}

    for key, state in active.items():
        t = track.setdefault(key, {})
        t["flips"] = _recent(t.get("flips"), cutoff)
        if not t.get("since"):
            # the fault begins or begins again after a clear spell
            t["since"] = now.isoformat()
            t["ok_since"] = None
            t["server"] = key in server_only
            if key not in server_only:
                t["flips"].append(now.isoformat())
                t["flips"] = t["flips"][-MAX_FLIPS_KEPT:]
        t["state"] = state
        began = _parse(t["since"]) or now
        flips = len(t["flips"])
        intermittent = flips > FLAP_LIMIT
        t["intermittent"] = intermittent
        if not intermittent and (now - began).total_seconds() < FAULT_ALERT_AFTER_S:
            continue
        message = fault_message(device.name, key, state, flips, intermittent)
        if t.get("alerted"):
            # update the open alert when the words change and only then, so a steady fault costs no query
            if t.get("message") != message:
                alert = _open_sensor_alert(db, device.id, key)
                if alert is not None:
                    alert.message = message
                t["message"] = message
            # once an hour make sure the alert is still open. One resolved by hand while the fault goes on is raised again
            # as a new alert that says so
            checked = _parse(t.get("checked"))
            if checked is None or (now - checked).total_seconds() >= HAND_RESOLVED_HOLD_S:
                t["checked"] = now.isoformat()
                if _open_sensor_alert(db, device.id, key) is None:
                    again = f"{message} (an earlier alert for this fault was resolved by hand)"
                    if add_alert(db, Alert(
                        device_id=device.id, rule_id=None, message=again, severity="warning", resolved=False,
                        category="monitoring", sensor_key=key, kind="sensor",
                    )):
                        t["message"] = again
                        result.notify.append((f"sensor-{key}", again))
            continue
        if in_maintenance is None:
            in_maintenance = is_in_maintenance(db, device.id)
        if in_maintenance:
            continue
        if _open_sensor_alert(db, device.id, key) is None and add_alert(db, Alert(
            device_id=device.id, rule_id=None, message=message, severity="warning", resolved=False,
            category="monitoring", sensor_key=key, kind="sensor",
        )):
            result.notify.append((f"sensor-{key}", message))
        t["alerted"] = True
        t["message"] = message
        t["checked"] = now.isoformat()

    for key in list(track):
        if key in active:
            continue
        t = track[key]
        t["flips"] = _recent(t.get("flips"), cutoff)
        if t.get("since"):
            # the sensor has just come back
            t["since"] = None
            t["ok_since"] = now.isoformat()
            if not t.get("server"):
                t["flips"].append(now.isoformat())
                t["flips"] = t["flips"][-MAX_FLIPS_KEPT:]
        t["intermittent"] = len(t["flips"]) > FLAP_LIMIT
        if t.get("alerted") and t["intermittent"]:
            # the sensor has recovered but changed too often to resolve. The alert must not go on saying that it is
            # not answering, so its words follow the intermittent wording here as well as while it is faulted
            message = fault_message(device.name, key, t.get("state", ""), len(t["flips"]), True)
            if t.get("message") != message:
                alert = _open_sensor_alert(db, device.id, key)
                if alert is not None:
                    alert.message = message
                t["message"] = message
        ok_since = _parse(t.get("ok_since"))
        quiet = ok_since is not None and (now - ok_since).total_seconds() >= FAULT_CLEAR_AFTER_S
        if quiet and not t["intermittent"]:
            alert = _open_sensor_alert(db, device.id, key) if t.get("alerted") else None
            if alert is not None:
                alert.resolved = True
                alert.resolved_at = now
                alert.message = f"{alert.message} (resolved: the sensor has reported ok for a minute)"
            # a sensor with no recent changes needs no record. One that flapped keeps its list until it ages out
            if t["flips"]:
                t["alerted"] = False
                t["message"] = None
            else:
                del track[key]
    row.sensor_track = track


def server_faults(db: Session, device: Device, payload: TelemetryIngest, reading: dict, now: datetime) -> dict[str, str]:
    """
    The sensor faults the server finds for itself in one post, as {sensor key: state}.

    out_of_range: a value outside what the part can measure was dropped at the door (a corrupt or hostile number). The
    value is gone, so no rule can fire on it and the sensor is treated as faulted so that is visible.
    stuck: a continuous value that has stopped moving (services/stuck_sensors.py). It stops nothing: the value is kept.
    The stuck state is kept on the device and costs no query.
    """
    found: dict[str, str] = {}
    for name in payload.dropped_values or []:
        sensor = FIELD_SENSOR.get(name)
        if sensor is not None:
            found[sensor] = "out_of_range"
    state, stuck = stuck_sensors.update(
        device.stuck_state, reading, now.timestamp(), device.expected_interval_s or 5,
    )
    for sensor, word in stuck.items():
        found.setdefault(sensor, word)
    state["_faults"] = dict(found)
    device.stuck_state = state
    return found


def track_server_faults(db: Session, device: Device, server: dict[str, str], previous: dict, now: datetime, result: HealthResult) -> None:
    """
    Run the sensor fault alerts for the server's own findings when the post carried no health fields (so record_health did not).

    A machine with nothing to track and nothing tracked before costs nothing. The health row is made only when there is
    a fault to track.
    """
    if result.tracked or not (server or previous):
        return
    row = db.get(DeviceHealth, device.id)
    if row is None:
        if not server:
            return
        row = DeviceHealth(
            device_id=device.id, lost_posts=0, dropped_fields=0, boot_events=[], faults={}, links={}, sensor_track={},
        )
        db.add(row)
    _track_sensor_faults(db, device, row, now, result, server)


def record_health(
    db: Session, device: Device, payload: TelemetryIngest, now: datetime, server: dict[str, str] | None = None,
) -> HealthResult:
    """
    Keep a post's health fields as the device's latest vitals and note what they show.

    A health field that was out of bounds or malformed was already dropped by the schema: it is counted here and the
    rest of the post is stored. A post with none of the health fields leaves device_health alone, so a node that
    does not send them has no row and its API answer says so. Fields the post leaves out keep their last value,
    except `faults`: absent means nothing is wrong, so a post that carries any health field replaces the fault map.
    """
    if not (payload.model_fields_set & HEALTH_FIELDS):
        return HealthResult()

    row = db.get(DeviceHealth, device.id)
    previous = row
    if row is None:
        row = DeviceHealth(
            device_id=device.id, lost_posts=0, dropped_fields=0, boot_events=[], faults={}, links={}, sensor_track={},
        )
        db.add(row)
    result = HealthResult(stored=True)

    # a field that could not be used is counted and never costs the reading
    row.dropped_fields = (row.dropped_fields or 0) + len(payload.dropped_health or [])
    usable = (payload.model_fields_set & HEALTH_FIELDS) - DROPPED_FIELDS
    if not usable:
        # nothing but bad fields: the latest vitals and faults stay as they were
        return result

    # a jump in the counter means posts were lost. A boot in between restarts the counter, so it proves nothing
    same_boot = payload.boot is None or previous is None or previous.boot_count in (None, payload.boot)
    if payload.seq is not None and previous is not None and previous.last_seq is not None and same_boot:
        gap = payload.seq - previous.last_seq - 1
        if gap > 0:
            result.lost = gap
            row.lost_posts = (row.lost_posts or 0) + gap
            row.last_gap_at = now

    # a rise in the boot counter is a restart and a fall means the counter was reset, which is a restart too;
    # only one boot is recorded per post, dated by the uptime: a counter that jumped while the node was away (it
    # booted several times without Wi-Fi) is not three restarts in ten minutes and the uptime says when the latest
    # one really was. Only boots seen inside the window can make a restart loop
    events = list(row.boot_events or [])
    if payload.boot is not None and previous is not None and previous.boot_count is not None:
        if payload.boot != previous.boot_count:
            booted_at = now - timedelta(seconds=payload.up) if payload.up is not None else now
            events.append(booted_at.isoformat())
    cutoff = now - BOOT_HISTORY_KEEP
    kept = [s for s in events if (when := _parse(s)) is not None and when >= cutoff]
    row.boot_events = kept[-_MAX_BOOT_EVENTS:]

    if payload.boot is not None:
        row.boot_count = payload.boot
    if payload.up is not None:
        row.uptime_s = payload.up
    if payload.reset_reason is not None:
        row.reset_reason = payload.reset_reason
    if payload.rssi is not None:
        row.rssi = payload.rssi
    if payload.heap_free is not None:
        row.heap_free = payload.heap_free
    if payload.fw is not None:
        row.firmware_version = payload.fw
    if payload.seq is not None:
        row.last_seq = payload.seq
    # a links or faults field that was dropped whole is no longer in the post, so the last value stays. One that was
    # only trimmed (a bad entry left out) is still in the post and its good entries are stored
    if payload.links is not None and "links" in payload.model_fields_set:
        row.links = dict(payload.links)
    # absent faults means nothing is wrong
    if "faults" in payload.model_fields_set or "faults" not in (payload.dropped_health or []):
        row.faults = dict(payload.faults or {})
    # the hub's bench counters and the sensors its firmware was built without (posted once per boot, so a post that leaves
    # them out keeps the last). A field dropped whole is not in the post, so the last value stays
    if payload.diag is not None and "diag" in payload.model_fields_set:
        row.diag = dict(payload.diag)
    if payload.not_fitted is not None and "not_fitted" in payload.model_fields_set:
        row.not_fitted_by_firmware = list(payload.not_fitted)
    row.reported_at = now

    _track_board_mismatch(db, device, row, payload, now, result)
    _track_sensor_faults(db, device, row, now, result, server)
    result.reset_loop = row.in_reset_loop(now)
    return result


def _track_board_mismatch(db: Session, device: Device, row: DeviceHealth, payload: TelemetryIngest, now: datetime, result: HealthResult) -> None:
    """
    One stateful monitoring alert while the firmware says its image was built for another board.

    It opens on the first post that says so (not in a maintenance window) and resolves on the first health post that does not.
    A board_mismatch that was dropped as malformed says nothing, so the state stays as it was.
    """
    if "board_mismatch" in (payload.dropped_health or []):
        return
    mismatch = payload.board_mismatch is True
    if mismatch and not row.board_mismatch:
        if is_in_maintenance(db, device.id):
            return
        row.board_mismatch = True
        message = f"{device.name}: {BOARD_MISMATCH_TEXT}"
        if open_alert_of_kind(db, device.id, BOARD_MISMATCH_TEXT, contains=True) is None and add_alert(db, Alert(
            device_id=device.id, rule_id=None, message=message, severity="warning", resolved=False,
            category="monitoring", kind="board_mismatch",
        )):
            result.notify.append(("board-mismatch", message))
    elif not mismatch and row.board_mismatch:
        row.board_mismatch = False
        alert = open_alert_of_kind(db, device.id, BOARD_MISMATCH_TEXT, contains=True)
        if alert is not None:
            alert.resolved = True
            alert.resolved_at = now
            alert.message = f"{alert.message} (resolved: the firmware no longer reports a mismatch)"


def track_scoring(
    db: Session,
    device: Device,
    reading: dict,
    scored: bool,
    now: datetime,
    covered: set[str] | None = None,
    node_type: str | None = None,
) -> tuple[str, str] | None:
    """
    Watch for a node that posts but is never scored.

    A reading with no score means the model lacks an input (a faulted sensor or a field that goes missing with
    no fault named, such as a range sensor with no target) or the model cannot be used at all (its file will not load).
    When that has held for UNSCORED_ALERT_AFTER_S one monitoring alert opens and says which inputs are missing or why
    the model cannot be used. It resolves with the next scored reading. Returns the (kind, message) to email after the
    commit or None.

    `covered` is the set of fields that a fault in this post stopped. When every missing input is one of them the
    sensor alert already says so, so a second alert for the same cause is not opened.
    """
    if scored:
        if device.unscored_since is not None or device.unscored_alerted:
            device.unscored_since = None
            device.unscored_missing = []
            if device.unscored_alerted:
                alert = open_alert_of_kind(db, device.id, UNSCORED_SUFFIX, contains=True)
                if alert is not None:
                    alert.resolved = True
                    alert.resolved_at = now
                    alert.message = f"{alert.message} (resolved: readings are scored again)"
            device.unscored_alerted = False
        return None

    # a machine whose model is still learning (not enough clean readings yet) or that has no model file is unscored by design,
    # so a missing score is not a fault there. The alert is for a machine that should be scored and is not
    try:
        model_state = ml_service.model_status(device.id, node_type or device.type).get("state")
    except Exception:  # noqa: BLE001
        # a status that cannot be read must not stop the alert for a machine that should be scored
        model_state = None
    if model_state in ("learning", "none"):
        if device.unscored_since is not None:
            device.unscored_since = None
            device.unscored_missing = []
        return None
    problem = ml_service.scoring_problem()
    missing = ml_service.missing_features(reading, device_id=device.id)
    if device.unscored_since is None:
        device.unscored_since = now
    if missing:
        device.unscored_missing = missing
    if device.unscored_alerted:
        return None
    since = _aware(device.unscored_since)
    if (now - since).total_seconds() < UNSCORED_ALERT_AFTER_S or is_in_maintenance(db, device.id):
        return None
    if problem:
        message = f"{device.name} {UNSCORED_SUFFIX}: the model could not be used ({problem})"
    else:
        inputs = device.unscored_missing or []
        if inputs and covered and set(inputs) <= covered:
            return None
        message = f"{device.name} {UNSCORED_SUFFIX}: the model is missing {', '.join(inputs) or 'an input'}"
    if open_alert_of_kind(db, device.id, UNSCORED_SUFFIX, contains=True) is None:
        if not add_alert(db, Alert(
            device_id=device.id, rule_id=None, message=message, severity="warning", resolved=False,
            category="monitoring", kind="unscored",
        )):
            device.unscored_alerted = True
            return None
    device.unscored_alerted = True
    return ("unscored", message)


def track_clipping(db: Session, device: Device, reading: dict, now: datetime) -> str | None:
    """
    Keep one machine warning open while the vibration node says a sample reached the sensor's limit.

    Clipping is a reading and not a fault: the vibration values are kept and still scored. The warning opens on the
    first post that says so and resolves after CLIPPING_CLEAR_AFTER_S without it. Returns the message to notify after
    the commit or None.
    """
    if reading.get("vib_clipping") is True:
        device.clipping_last_true = now
        if device.clipping_alerted or is_in_maintenance(db, device.id):
            return None
        device.clipping_alerted = True
        message = f"{device.name}: vibration is beyond the sensor's range"
        if add_alert(db, Alert(
            device_id=device.id, rule_id=None, message=message, severity="warning", resolved=False,
            category="machine", kind="clipping",
        )):
            return message
        return None
    if device.clipping_alerted and device.clipping_last_true is not None:
        if (now - _aware(device.clipping_last_true)).total_seconds() >= CLIPPING_CLEAR_AFTER_S:
            alert = (
                db.query(Alert)
                .filter(Alert.device_id == device.id, Alert.kind == "clipping", Alert.resolved.is_(False))
                .first()
            )
            if alert is not None:
                alert.resolved = True
                alert.resolved_at = now
                alert.message = f"{alert.message} (resolved: no clipping for a minute)"
            device.clipping_alerted = False
    return None


def recently_resolved_by_hand(db: Session, device_id, kind: str, now: datetime) -> bool:
    """True when a person resolved an alert of this kind for the device within the last HAND_RESOLVED_HOLD_S."""
    return (
        db.query(Alert.id)
        .filter(
            Alert.device_id == device_id,
            Alert.kind == kind,
            Alert.resolved.is_(True),
            Alert.resolved_at >= now - timedelta(seconds=HAND_RESOLVED_HOLD_S),
            Alert.message.endswith(HAND_RESOLVED_SUFFIX),
        )
        .first()
    ) is not None


def open_alert_of_kind(db: Session, device_id, suffix: str, contains: bool = False) -> Alert | None:
    match = Alert.message.contains(suffix) if contains else Alert.message.endswith(suffix)
    return (
        db.query(Alert)
        .filter(
            Alert.device_id == device_id,
            Alert.category == "monitoring",
            Alert.resolved.is_(False),
            match,
        )
        .first()
    )


def open_reset_loop_alert(db: Session, device: Device) -> str | None:
    """
    Add the one monitoring alert for a restart loop, unless one is open already or the machine is in maintenance.
    No commit: the caller commits with the rest of the post. Returns the message to notify or None.
    """
    if is_in_maintenance(db, device.id):
        return None
    if open_alert_of_kind(db, device.id, RESET_LOOP_SUFFIX) is not None:
        return None
    # one resolved by hand while the loop goes on is not raised again straight away
    if recently_resolved_by_hand(db, device.id, "reset_loop", datetime.now(timezone.utc)):
        return None
    message = f"{device.name} {RESET_LOOP_SUFFIX}"
    if add_alert(db, Alert(
        device_id=device.id, rule_id=None, message=message, severity="warning", resolved=False,
        category="monitoring", kind="reset_loop",
    )):
        return message
    return None


def raise_reset_loop_alert(
    db: Session,
    device: Device,
    background_tasks: BackgroundTasks | None = None,
) -> Alert | None:
    """Open the restart-loop alert, commit and email it. Under the device lock, so two posts cannot both open one."""
    lock_device(db, device.id)
    message = open_reset_loop_alert(db, device)
    if message is None:
        return None
    db.commit()
    alert_service.notify_monitoring(background_tasks, device, "reset-loop", message)
    return open_alert_of_kind(db, device.id, RESET_LOOP_SUFFIX)


def cannot_evaluate(rules, faults: dict[str, str], not_fitted) -> list[dict]:
    """
    The rules that cannot fire now because the sensor that produces their field is faulted or not fitted.

    Each is reported with the sensor and the reason, so the health read shows it. No alert is raised per rule: the
    sensor fault alert already covers the cause.
    """
    absent = {canonical_key(k) for k in not_fitted or []}
    found = []
    for rule in rules:
        for key in absent | {canonical_key(k) for k in faults}:
            if key in absent:
                state = "not_fitted"
            else:
                state = faults.get(key) or next(v for k, v in faults.items() if canonical_key(k) == key)
            if rule.metric not in state_fields(key, state):
                continue
            if key in absent:
                reason = f"sensor {key} is not fitted on this machine"
            else:
                reason = f"sensor {key} is {STATE_WORDS.get(state, STATE_WORDS['unknown'])}, so {rule.metric} is not measured"
            found.append({
                "rule_id": rule.id, "metric": rule.metric, "sensor_key": key, "state": state, "reason": reason,
            })
            break
    return found
