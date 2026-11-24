"""
Retraining the anomaly models: the manual retrain of an admin and the nightly one.

Both run the same function and so the same guard: a model that is refused (over the false alert budget, finding too
few faults, worse than the model in service on the same newest readings or moving the machine's normal too far) never
replaces one in service. When nothing is accepted nothing is saved. The outcome, accepted or refused, is written beside
the model file where GET /ml/status reads it. It also goes to the audit log. A machine the retrain leaves with no working
model gets a monitoring alert that says why and so does a machine whose new model needs a person to accept its move.

A retrain reads a fortnight of every machine and takes minutes, so only one may run at a time across all API workers.
The lock is the shared one in services/cooldown.py that the liveness sweep also uses (a Redis key with a process memory
fallback). The nightly job also takes a lock per UTC day, so two workers that wake at the same minute run it once.

To register the nightly job, tasks/retention.py needs these two statements in start_retention_scheduler (and the import
at the top of the file):

    from app.tasks import model_retrain
    scheduler.add_job(model_retrain.run_nightly_job, trigger="cron", hour=model_retrain.RETRAIN_HOUR_UTC,
                      minute=model_retrain.RETRAIN_MINUTE_UTC, id="model_retrain", max_instances=1, coalesce=True)
"""
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import text

from app.db import SessionLocal
from app.models.device import Device
from app.services import audit_service, cooldown, ml_service, training_data

logger = logging.getLogger(__name__)

# 03:30 UTC: after the retention purge at 02:00 and before a working day starts in most of the world, so the fortnight it
# reads is not competing with a morning's ingest. It reads one machine at a time in short transactions in any case
RETRAIN_HOUR_UTC = 3
RETRAIN_MINUTE_UTC = 30
# held for the whole run. Two hours is longer than a retrain of a large fleet takes. It frees itself if a worker dies
RUNNING_KEY = "phaemos:model-retrain:running"
RUNNING_SECONDS = 2 * 60 * 60
# one nightly run per UTC day however many workers wake. Twenty hours so the next night's run is never blocked
DAY_KEY = "phaemos:model-retrain:nightly:{day}"
DAY_SECONDS = 20 * 60 * 60


def next_run(now: datetime | None = None) -> datetime:
    """The next time the nightly retrain is due, for GET /ml/status."""
    now = now or datetime.now(timezone.utc)
    due = now.replace(hour=RETRAIN_HOUR_UTC, minute=RETRAIN_MINUTE_UTC, second=0, microsecond=0)
    return due if due > now else due + timedelta(days=1)


def schedule(now: datetime | None = None) -> dict:
    return {
        "nightly_utc": f"{RETRAIN_HOUR_UTC:02d}:{RETRAIN_MINUTE_UTC:02d}",
        "next_at": next_run(now).isoformat(),
    }


def fleet() -> list:
    """
    The machines to train on, as plain objects, read in one short query so no session stays open while training.

    The node type of a machine is the one its readings carry (the scoring path looks models up by it) and falls back
    to the machine's own type. Oldest machines come first, which is the order the per-machine cap is filled in.
    """
    db = SessionLocal()
    try:
        # one index probe per machine: its newest reading that names a node type
        latest = {
            str(row[0]): row[1]
            for row in db.execute(text(
                "SELECT d.id, (SELECT t.node_type FROM telemetry t WHERE t.device_id = d.id AND t.node_type IS NOT NULL "
                "ORDER BY t.recorded_at DESC LIMIT 1) FROM devices d"
            ))
        }
        devices = db.query(Device).order_by(Device.created_at.asc(), Device.id.asc()).all()
        return [
            SimpleNamespace(id=d.id, name=d.name, type=latest.get(str(d.id)) or d.type,
                            expected_interval_s=d.expected_interval_s, ambient_source_id=d.ambient_source_id)
            for d in devices
        ]
    finally:
        db.close()


def _serving_bundle() -> dict:
    ml_service._load_model()
    current = ml_service._model
    if current is None:
        return {}
    return current if isinstance(current, dict) else {"default": current}


def train_and_save(trigger: str, now: datetime | None = None) -> tuple[str, str]:
    """
    Retrain, save an accepted bundle and record the outcome. Returns (audit action, summary).

    The action is "retrain" when a bundle was saved, "retrain_refused" when none was and "retrain_error" when the task
    failed. In the last two the model in service is untouched.
    """
    try:
        machines = fleet()
        if not machines:
            result = {"status": "refused", "summary": "Retrain skipped: there are no machines to learn from.",
                      "models": [], "learning": []}
            bundle = None
        else:
            counts: dict = {}
            for d in machines:
                if d.type:
                    counts[d.type] = counts.get(d.type, 0) + 1
            # machines are read one at a time, each in its own short transaction (training_data.load_machine)
            outcome = ml_service.train_bundle(
                (training_data.load_machine(d) for d in machines), counts, len(machines), _serving_bundle(),
            )
            bundle, result = outcome.bundle, outcome.result()
        stamp = now or datetime.now(timezone.utc)
        result["finished_at"] = stamp.isoformat()
        result["trigger"] = trigger
        if bundle is not None:
            ml_service.save_model(bundle)
            ml_service.reload_model()
            if machines:
                ml_service._consume_acceptances(outcome.used_acceptances)
        ml_service.save_last_retrain(result)
        # the machines' detector states are not cleared: each is carried into the new model at its next reading when the
        # new model reads the same sensors on close enough scales and starts cold from its own readings otherwise
        # (ml_service.carry_state). Clearing them all made every machine start cold every night
        if machines:
            raise_notices(result.get("unmonitored") or {}, result.get("moves") or {}, [d.id for d in machines])
        return ("retrain" if bundle is not None else "retrain_refused"), result["summary"]
    except Exception as exc:  # noqa: BLE001
        logger.exception("retrain failed")
        # the type only: a database error message can carry the values of a row
        return "retrain_error", f"Retrain failed: {type(exc).__name__}. The model in service is untouched."


UNMONITORED_KIND = "unmonitored"
MOVE_KIND = "model_move"
UNMONITORED_PREFIX = "Not monitored by the anomaly model"
MOVE_PREFIX = "Anomaly model needs a person"


def raise_notices(unmonitored: dict, moves: dict, device_ids: list, db=None) -> None:
    """
    Open one monitoring alert for each machine the retrain leaves with no working model and for each machine whose new
    model would move its normal past the bound (a person must accept that) and resolve the ones that no longer apply.

    The alerts are rows like every other monitoring alert: one open per machine and kind, shown on the dashboard. A
    machine nobody watches is never silent about it.
    """
    from app.models.alert import Alert
    from app.models.device import Device as DeviceRow
    from app.services.alert_state import add_alert

    session = db or SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        wanted = {(str(k), UNMONITORED_KIND): f"{UNMONITORED_PREFIX}: {v}" for k, v in unmonitored.items()}
        wanted.update({(str(k), MOVE_KIND): f"{MOVE_PREFIX}: {v}" for k, v in moves.items()})
        known = {str(d) for d in device_ids}
        open_rows = session.query(Alert).filter(Alert.kind.in_([UNMONITORED_KIND, MOVE_KIND]), Alert.resolved.is_(False)).all()
        for row in open_rows:
            if (str(row.device_id), row.kind) not in wanted:
                row.resolved = True
                row.resolved_at = now
                row.message = f"{row.message} (resolved: the last retrain gave it a working model)"
        have = {(str(r.device_id), r.kind) for r in open_rows}
        for (device_id, kind), message in wanted.items():
            if device_id not in known or (device_id, kind) in have:
                continue
            try:
                key = UUID(device_id)
            except ValueError:
                continue
            if session.get(DeviceRow, key) is None:
                continue
            add_alert(session, Alert(device_id=key, rule_id=None, message=message, severity="warning",
                                     resolved=False, category="monitoring", kind=kind, triggered_at=now))
        session.commit()
    except Exception as exc:  # noqa: BLE001
        # a notice that cannot be written must not undo the retrain. It is logged and the status still says it
        logger.error("the anomaly model's monitoring notices could not be written (%s)", type(exc).__name__)
        session.rollback()
    finally:
        if db is None:
            session.close()


def _audit(actor: str, action: str, detail: str) -> None:
    db = SessionLocal()
    try:
        audit_service.log_action(db, actor, action, "ml_model", "model", detail)
    finally:
        db.close()


def run_retrain(actor: str, trigger: str, now: datetime | None = None, trainer=None, audit=None) -> bool:
    """
    Run one retrain if none is running. True when this call ran it.

    trainer and audit are for tests. A retrain that is already running (in this or another worker) makes this call
    do nothing and say so in the audit log.
    """
    trainer = trainer or train_and_save
    audit = audit or _audit
    if not cooldown.acquire(RUNNING_KEY, RUNNING_SECONDS):
        audit(actor, "retrain_skipped", "Retrain skipped: another retrain is already running.")
        return False
    try:
        action, detail = trainer(trigger, now)
        audit(actor, action, detail)
        return True
    finally:
        cooldown.release(RUNNING_KEY)


def run_nightly_job(now: datetime | None = None, trainer=None, audit=None) -> bool:
    """
    The scheduled job. True when this call ran the retrain.

    The per-day lock makes it run once a night however many workers wake. The running lock in run_retrain keeps it from
    overlapping a manual retrain. A night whose retrain is refused leaves the model in service untouched like any other.
    """
    now = now or datetime.now(timezone.utc)
    day_key = DAY_KEY.format(day=now.strftime("%Y%m%d"))
    if not cooldown.acquire(day_key, DAY_SECONDS):
        return False
    ran = run_retrain("system", "nightly", now=now, trainer=trainer, audit=audit)
    if not ran:
        # another retrain was running: free the day so the next wake-up may try again
        cooldown.release(day_key)
    return ran
