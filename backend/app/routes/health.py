"""
Health routes - fleet summary for authenticated users and a public
status check for uptime monitors and the frontend status page.
"""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
from app.errors import ApiError, Code
from app.routes.moved import moved
from app.services import liveness_service, ml_service
from app.limiter import limiter
from app.models.alert import Alert, AlertRule
from app.models.device import Device
from app.models.ticket import Ticket
from app.models.user import User
from app.routes.auth import get_current_user
from app.services.access import (
    limit_tickets_to_readable,
    limit_to_readable_devices,
    readable_device_clause,
)

# two routers: one for auth-protected fleet stats, one for the public /status check.
router = APIRouter()
public_router = APIRouter()


def _health_score(online: int, total: int, active_alerts: int, total_rules: int) -> int:
    if total == 0:
        return 100
    ratio = online / total
    alert_penalty = min(active_alerts / max(total_rules, 1), 0.5)
    return round(ratio * 100 * (1 - alert_penalty))


class LinkStates(BaseModel):
    online: int
    late: int
    offline: int


class FleetSummary(BaseModel):
    total_devices: int
    online: int
    offline: int
    link_states: LinkStates
    active_alerts: int
    open_tickets: int
    health_score: int


class Status(BaseModel):
    # `operational` when the database and Redis both answer, `degraded` when either does not. The answer is 200 either way
    status: Literal["operational", "degraded"]
    api: Literal["ok"]
    database: Literal["ok", "error"]
    redis: Literal["ok", "error"]
    # none (no model file yet), ok, legacy (a file from before missing values stopped being filled with zero) or error
    model: Literal["none", "ok", "legacy", "error"]
    # the release the API belongs to (the same as `version` at GET /). Nothing else about the deployment is shown
    version: str
    # the server's clock in UTC, for a client that wants to check its own against it
    updated_at: datetime


class Live(BaseModel):
    status: Literal["ok"]


# the fleet statistics were at /health/summary. "health" meant three different things, so they are at /fleet/summary and the
# old path is a deprecated alias for one release
@moved(router, router, "GET", "/health/summary", "/fleet/summary", response_model=FleetSummary)
@limiter.limit("120/minute")
def health_summary(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # every total covers only what the caller may read, so a technician's figures
    # describe their own and unowned machines and nothing else
    devices = db.query(Device)
    clause = readable_device_clause(current_user)
    if clause is not None:
        devices = devices.filter(clause)
    total_devices = devices.count()
    online_devices = devices.filter(Device.status == "online").count()
    # how many machines are in each link state. The same rule as a machine's own read: the worse of the state the sweep stored and
    # what the age of its last post implies for its own interval, so the sidebar never says online for a machine whose page
    # says late (the stored state lags by up to a sweep)
    link_states = {"online": 0, "late": 0, "offline": 0}
    now = datetime.now(timezone.utc)
    for stored, last_seen, interval in devices.with_entities(Device.link_state, Device.last_seen, Device.expected_interval_s).all():
        link_states[liveness_service.effective_link_state(stored, last_seen, interval, now)] += 1
    active_alerts = limit_to_readable_devices(
        db.query(Alert).filter(Alert.resolved.is_(False)), current_user, Alert.device_id
    ).count()
    open_tickets = limit_tickets_to_readable(
        db.query(Ticket).filter(Ticket.status != "closed"), current_user
    ).count()
    total_rules = limit_to_readable_devices(db.query(AlertRule), current_user, AlertRule.device_id).count()

    score = _health_score(online_devices, total_devices, active_alerts, total_rules)

    return FleetSummary(
        total_devices=total_devices, online=online_devices, offline=total_devices - online_devices,
        link_states=LinkStates(**link_states), active_alerts=active_alerts, open_tickets=open_tickets, health_score=score,
    )


def _check_db() -> str:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return "ok"
    except Exception:
        return "error"


def _check_redis() -> str:
    # import redis lazily so the main app does not fail if the package is absent.
    try:
        import redis as redis_lib
        client = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        return "ok"
    except Exception:
        return "error"


@public_router.get("/livez", response_model=Live, operation_id="livez")
@limiter.limit("240/minute")
def liveness(request: Request):
    """The process is up. It checks nothing else, so an orchestrator can tell a dead process from a dependency that is down."""
    return Live(status="ok")


@public_router.get("/readyz", response_model=Live, operation_id="readyz", responses={503: {"description": "A dependency is down"}})
@limiter.limit("240/minute")
def readiness(request: Request):
    """Ready to serve: the database and Redis answer. A 503 names the one that does not."""
    down = [name for name, state in (("database", _check_db()), ("redis", _check_redis())) if state != "ok"]
    if down:
        raise ApiError(503, Code.UNAVAILABLE, f"Not ready: {', '.join(down)} not answering")
    return Live(status="ok")


@public_router.get("/status", response_model=Status, operation_id="status_page")
# each call opens a database session and a Redis connection and the page polls every 30 seconds,
# so 120 a minute an address is far more than a page or an uptime monitor needs
@limiter.limit("120/minute")
def status_check(request: Request):
    """Public endpoint - no auth required. Used by uptime monitors."""
    db_status = _check_db()
    redis_status = _check_redis()
    overall = "operational" if db_status == "ok" and redis_status == "ok" else "degraded"
    return {
        "status": overall,
        "api": "ok",
        "database": db_status,
        "redis": redis_status,
        # none (no model file yet), ok, legacy (a file from before missing values stopped being filled with zero) or
        # error (the file will not load, so readings are stored without a score). deploy.sh fails on error
        "model": ml_service.model_state(),
        "version": settings.release_version,
        "updated_at": datetime.now(timezone.utc),
    }
