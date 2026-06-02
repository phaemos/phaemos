"""
Health routes - fleet summary for authenticated users and a public
status check for uptime monitors and the frontend status page.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models.alert import Alert, AlertRule
from app.models.device import Device
from app.models.ticket import Ticket
from app.models.user import User
from app.routes.auth import get_current_user

# Two routers: one for auth-protected fleet stats, one for the public /status check.
router = APIRouter()
public_router = APIRouter()


def _health_score(online: int, total: int, active_alerts: int, total_rules: int) -> int:
    if total == 0:
        return 100
    ratio = online / total
    alert_penalty = min(active_alerts / max(total_rules, 1), 0.5)
    return round(ratio * 100 * (1 - alert_penalty))


@router.get("/health/summary")
def health_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total_devices = db.query(Device).count()
    online_devices = db.query(Device).filter(Device.status == "online").count()
    active_alerts = db.query(Alert).filter(Alert.resolved.is_(False)).count()
    open_tickets = db.query(Ticket).filter(Ticket.status != "closed").count()
    total_rules = db.query(AlertRule).count()

    score = _health_score(online_devices, total_devices, active_alerts, total_rules)

    return {
        "total_devices": total_devices,
        "online": online_devices,
        "offline": total_devices - online_devices,
        "active_alerts": active_alerts,
        "open_tickets": open_tickets,
        "health_score": score,
    }


def _check_db() -> str:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return "ok"
    except Exception:
        return "error"


def _check_redis() -> str:
    # I import redis lazily so the main app does not fail if the package is absent.
    from app.config import settings
    try:
        import redis as redis_lib
        client = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        return "ok"
    except Exception:
        return "error"


@public_router.get("/status", include_in_schema=False)
def status_check():
    """Public endpoint - no auth required. Used by uptime monitors."""
    db_status = _check_db()
    redis_status = _check_redis()
    overall = "operational" if db_status == "ok" and redis_status == "ok" else "degraded"
    return {
        "status": overall,
        "api": "ok",
        "database": db_status,
        "redis": redis_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
