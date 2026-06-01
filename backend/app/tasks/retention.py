import logging
from datetime import timedelta, timezone, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db import engine
from app.services import audit_service

logger = logging.getLogger(__name__)

_RETENTION_DAYS = 90

# I create a dedicated SessionLocal here because the background job runs
# outside FastAPI's request lifecycle and cannot use Depends(get_db).
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _delete_old_telemetry() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
    db = _SessionLocal()
    try:
        result = db.execute(
            text("DELETE FROM telemetry WHERE recorded_at < :cutoff"),
            {"cutoff": cutoff},
        )
        n_deleted = result.rowcount
        # I commit before audit so the deletion is durable even if the audit call fails.
        db.commit()
        logger.info(
            "Retention cleanup: deleted %d rows older than %d days",
            n_deleted,
            _RETENTION_DAYS,
        )
        audit_service.log_action(
            db,
            user_id="system",
            action="retention_cleanup",
            resource="telemetry",
            resource_id=None,
            detail=f"deleted {n_deleted} rows older than {_RETENTION_DAYS} days",
        )
    except Exception:
        db.rollback()
        logger.exception("Retention cleanup failed")
    finally:
        db.close()


def start_retention_scheduler() -> None:
    scheduler = BackgroundScheduler(daemon=True)
    # I run at 02:00 UTC daily - off-peak to avoid contention with live ingest.
    scheduler.add_job(
        _delete_old_telemetry,
        trigger="cron",
        hour=2,
        minute=0,
        id="retention_cleanup",
    )
    scheduler.start()
    logger.info(
        "Retention scheduler started (daily 02:00 UTC, %d-day window)",
        _RETENTION_DAYS,
    )
