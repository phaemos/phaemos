import logging
from datetime import timedelta, timezone, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import engine
from app.services import audit_service, liveness_service
from app.tasks import model_retrain

logger = logging.getLogger(__name__)

_RETENTION_DAYS = 90

# create a dedicated SessionLocal here because the background job runs
# outside FastAPI's request lifecycle and cannot use Depends(get_db).
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# rows deleted per statement and per commit. A purge after a long stop of the scheduler can reach millions of rows;
# one statement over all of them is a long transaction with a large write-ahead burst
_BATCH_SIZE = 10_000


def _purge(db, resource: str, table: str, where: str, cutoff: datetime, label: str, key: str = "id") -> int | None:
    """
    Delete the rows of `table` that match `where` (which uses :cutoff), a batch at a time with a commit per batch,
    then write one audit row. A failure is logged and does not stop the other rules. Batches already committed stay.
    """
    total = 0
    try:
        while True:
            n = db.execute(
                text(f"DELETE FROM {table} WHERE {key} IN (SELECT {key} FROM {table} WHERE {where} LIMIT :batch)"),
                {"cutoff": cutoff, "batch": _BATCH_SIZE},
            ).rowcount
            # a commit per batch, so no lock or transaction lasts long and the deletion is durable even if the audit
            # call fails
            db.commit()
            total += n
            if n < _BATCH_SIZE:
                break
    except Exception as exc:
        db.rollback()
        # the type only: the text of a database error can carry values from the row
        logger.warning("Retention cleanup of %s failed after %d rows (%s)", resource, total, type(exc).__name__)
        return None
    logger.info("Retention cleanup: deleted %d %s", total, label)
    audit_service.log_action(
        db,
        user_id="system",
        action="retention_cleanup",
        resource=resource,
        resource_id=None,
        detail=f"deleted {total} {label}",
    )
    return total


def run_retention(session_factory=_SessionLocal, now: datetime | None = None) -> dict:
    """
    Delete what is past its retention period. The clock is a parameter so a test needs no waiting.

    Order matters. Closed tickets go first, so the alerts they pointed at are free to go. A resolved alert that a
    remaining ticket still points at is kept, which means no ticket ever loses its alert and no delete can fail on
    the tickets.alert_id key. The audit log has no keys to other tables, so it can go at any time.
    Open tickets and unresolved alerts are never touched. A period of 0 or less keeps that data for ever.
    """
    now = now or datetime.now(timezone.utc)
    done: dict = {}
    db = session_factory()
    try:
        done["telemetry"] = _purge(
            db, "telemetry", "telemetry",
            "recorded_at < :cutoff",
            now - timedelta(days=_RETENTION_DAYS),
            f"rows older than {_RETENTION_DAYS} days",
        )
        if settings.retention_closed_tickets_days > 0:
            days = settings.retention_closed_tickets_days
            done["tickets"] = _purge(
                db, "tickets", "tickets",
                "lower(status) = 'closed' AND COALESCE(updated_at, created_at) < :cutoff",
                now - timedelta(days=days),
                f"closed tickets older than {days} days",
            )
        if settings.retention_resolved_alerts_days > 0:
            days = settings.retention_resolved_alerts_days
            done["alerts"] = _purge(
                db, "alerts", "alerts",
                "resolved IS TRUE AND COALESCE(resolved_at, triggered_at) < :cutoff "
                "AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.alert_id = alerts.id)",
                now - timedelta(days=days),
                f"resolved alerts older than {days} days",
            )
        if settings.retention_audit_days > 0:
            days = settings.retention_audit_days
            done["audit_log"] = _purge(
                db, "audit_log", "audit_log",
                "created_at < :cutoff",
                now - timedelta(days=days),
                f"audit log entries older than {days} days",
            )
        # sign-in sessions are kept a day past their expiry. A revoked row stays until then, so a refresh token
        # stolen before the revoke is still seen as revoked
        done["user_sessions"] = _purge(
            db, "user_sessions", "user_sessions",
            "expires_at < :cutoff",
            now - timedelta(days=1),
            "sign-in sessions expired for over a day",
        )
        # an accepted invitation is remembered by the hash of its token for the token's own life (48 hours) and a day
        # more. After that the link would be refused as expired anyway, so the record has done its job
        done["used_invites"] = _purge(
            db, "used_invites", "used_invites",
            "used_at < :cutoff",
            now - timedelta(days=3),
            "used invitation records older than 3 days",
            key="token_hash",
        )
        # an invitation is refused once it has expired, so its row is only a record. It is kept a month past its expiry (used,
        # cancelled or never opened) so an admin can still see what became of it, then removed
        done["invitations"] = _purge(
            db, "invitations", "invitations",
            "expires_at < :cutoff",
            now - timedelta(days=30),
            "invitations expired for over 30 days",
        )
    finally:
        db.close()
    return done


def start_retention_scheduler() -> None:
    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    # every device gets a full interval of grace from this moment, so a restart of the API is not read as silence
    liveness_service.mark_started()
    # run at 02:00 UTC daily - off-peak to avoid contention with live ingest.
    scheduler.add_job(
        run_retention,
        trigger="cron",
        hour=2,
        minute=0,
        id="retention_cleanup",
    )
    # the liveness sweep shares this scheduler. A Redis lock inside the job keeps two workers from both acting
    scheduler.add_job(
        liveness_service.run_sweep_job,
        trigger="interval",
        seconds=liveness_service.SWEEP_INTERVAL_S,
        id="liveness_sweep",
        max_instances=1,
        coalesce=True,
    )
    # the nightly model retrain shares this scheduler too. The job decides for itself whether it is due and takes its own lock
    scheduler.add_job(
        model_retrain.run_nightly_job,
        trigger="cron",
        hour=model_retrain.RETRAIN_HOUR_UTC,
        minute=model_retrain.RETRAIN_MINUTE_UTC,
        id="model_retrain",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "Retention scheduler started (daily 02:00 UTC, %d-day window) with the liveness sweep every %d s",
        _RETENTION_DAYS,
        liveness_service.SWEEP_INTERVAL_S,
    )
