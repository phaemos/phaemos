from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Response
from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.db import get_db
# alert is a fired event; AlertRule is the config that defines when an alert should fire
from app.deps import Page, set_total
from app.errors import ApiError, Code
from app.models.alert import Alert, AlertRule, RuleState
from app.patching import apply_patch
from app.schemas.misc_responses import AlertMetrics
from app.schemas.alert import AlertRuleCreate, AlertRuleUpdate, AlertRuleResponse, AlertResponse
from app.routes.auth import get_current_user, require_admin
from app.models.user import User
from app.services import alert_service, audit_service, idempotency, keyset, rule_metrics
from app.services.deprecation import deprecate
from app.services.access import (
    get_device_for_read,
    limit_to_readable_devices,
    require_device_read,
    require_device_write,
)
from app.models.device import Device

router = APIRouter()

# the fixed sets a filter may name. An unknown value is a 422 and not an empty list
AlertKind = Literal["rule", "anomaly", "offline", "reset_loop", "unscored", "sensor", "clipping", "board_mismatch", "unmonitored", "model_move"]
Severity = Literal["info", "warning", "critical"]


# `resolved: bool | None = None` makes this query parameter optional - omitting it returns all alerts
@router.get("/alerts", response_model=list[AlertResponse])
def list_alerts(
    response: Response,
    # filters. A thing that belongs to a device is filtered by query, never by a path segment (GET /alerts/{device_id} is gone)
    device_id: UUID | None = None,
    resolved: bool | None = None,
    # machine alerts are about the machine, monitoring alerts about the way it is watched. Omit it for both
    category: Literal["machine", "monitoring"] | None = None,
    kind: AlertKind | None = None,
    severity: Severity | None = None,
    # when the alert was raised, UTC when no zone is given
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    # keyset paging: the rows after this one, newest first. Use the X-Next-Before of the previous page. Offset is for small lists
    before: str | None = Query(default=None, description="Cursor from X-Next-Before: <ISO time>,<id>"),
    page: Page = Depends(Page.up_to(500, default=100)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # build the query object first, then conditionally append filters before executing
    q = limit_to_readable_devices(db.query(Alert), current_user, Alert.device_id)
    if device_id is not None:
        # a machine the caller may not read answers 404 as it does everywhere
        get_device_for_read(db, current_user, device_id)
        q = q.filter(Alert.device_id == device_id)
    # only add the resolved filter when the caller explicitly passes ?resolved=true or ?resolved=false
    if resolved is not None:
        q = q.filter(Alert.resolved == resolved)
    if category is not None:
        q = q.filter(Alert.category == category)
    if kind is not None:
        q = q.filter(Alert.kind == kind)
    if severity is not None:
        q = q.filter(Alert.severity == severity)
    if from_ is not None:
        q = q.filter(Alert.triggered_at >= _utc(from_))
    if to is not None:
        q = q.filter(Alert.triggered_at <= _utc(to))
    if from_ is not None and to is not None and _utc(from_) > _utc(to):
        raise ApiError(422, Code.INVALID_RANGE, "from must not be later than to")
    # most recently triggered first - useful for dashboards. Every order ends in id so two alerts raised in the same instant never swap
    order = (Alert.triggered_at.desc(), Alert.id.desc())
    if before is not None:
        when, row_id = keyset.decode(before)
        q = q.filter(tuple_(Alert.triggered_at, Alert.id) < tuple_(when, row_id))
        rows = q.order_by(*order).limit(page.limit).all()
    else:
        # a total is counted for the first page only: a keyset walk would pay a full count for every page
        set_total(response, q.count())
        rows = q.order_by(*order).offset(page.offset).limit(page.limit).all()
    keyset.set_next(response, rows, page.limit, "triggered_at")
    return rows


def _utc(when: datetime) -> datetime:
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
def get_alert(
    alert_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    device = db.query(Device).filter(Device.id == alert.device_id).first() if alert is not None else None
    if alert is None or device is None:
        # the path used to take a device id here. Say so, once, for a caller that still sends one for a machine it may read
        old = db.query(Device).filter(Device.id == alert_id).first() if alert is None else None
        if old is not None:
            from app.services.access import can_read_device

            if can_read_device(current_user, old):
                raise ApiError(
                    410, Code.ENDPOINT_REMOVED,
                    "GET /alerts/{device_id} was removed. Use GET /alerts?device_id=<id> for a machine's alerts",
                )
        raise ApiError(404, Code.ALERT_NOT_FOUND, "Alert not found")
    # an alert on a machine the caller may not read looks like one that does not exist
    require_device_read(current_user, device, detail="Alert not found", code=Code.ALERT_NOT_FOUND)
    return alert


def _resolve(alert_id: UUID, db: Session, current_user: User, background_tasks: BackgroundTasks):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise ApiError(404, Code.ALERT_NOT_FOUND, "Alert not found")
    device = db.query(Device).filter(Device.id == alert.device_id).first()
    if device is None:
        raise ApiError(404, Code.ALERT_NOT_FOUND, "Alert not found")
    # an alert on a machine the caller may not read looks like one that does not exist
    require_device_read(current_user, device, detail="Alert not found", code=Code.ALERT_NOT_FOUND)
    # documented as admin or technician: viewers are read-only. A technician
    # resolves alerts only on machines they may change
    require_device_write(current_user, device)
    already = alert.resolved is True
    alert.resolved    = True
    # a system alert (a silent node, a sensor fault, a restart loop) resolved by hand while its cause goes on is accepted and
    # recorded in its message. It is raised again, as a new alert that says so, only after an hour and only if the cause
    # is still there (services/health_service.py, HAND_RESOLVED_HOLD_S)
    if alert.kind and not already and not (alert.message or "").endswith(" (resolved by hand)"):
        alert.message = f"{alert.message or ''} (resolved by hand)"
    # datetime.now(timezone.utc) produces a timezone-aware timestamp - always use UTC in APIs to avoid timezone confusion
    alert.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)

    # serialise to Pydantic BEFORE calling audit_service because audit_service
    # calls db.commit() internally, which expires all SQLAlchemy ORM objects in
    # the session. FastAPI would then fail to serialise the expired alert object.
    # capturing it as a Pydantic model first avoids that race.
    result = AlertResponse.model_validate(alert)

    if not already:
        # the json webhooks are told it resolved (alert.resolved). A failure to queue it never costs the resolve
        try:
            rule = db.query(AlertRule).filter(AlertRule.id == alert.rule_id).first() if alert.rule_id else None
            alert_service.notify_resolved(background_tasks, db, device, alert, rule)
        except Exception:  # noqa: BLE001
            pass

    audit_service.log_action(
        db,
        user_id=str(current_user.id),
        action="alert_resolved",
        resource="alert",
        resource_id=str(alert_id),
        detail=f"severity={result.severity}",
    )
    return result


# an action is a POST. PATCH stays as an alias for this release because the dashboard calls it
@router.post("/alerts/{alert_id}/resolve", response_model=AlertResponse)
def resolve_alert(
    alert_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _resolve(alert_id, db, current_user, background_tasks)


@router.patch("/alerts/{alert_id}/resolve", response_model=AlertResponse, deprecated=True)
def resolve_alert_patch(
    alert_id: UUID,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deprecate(response, f"/api/v1/alerts/{alert_id}/resolve")
    return _resolve(alert_id, db, current_user, background_tasks)


@router.get("/alert-metrics", response_model=AlertMetrics)
def alert_metrics(_user: User = Depends(get_current_user)):
    """
    The readings a rule may watch, the conditions and the severities. The rule form reads this list, so it cannot drift. It also
    says where today's daily email and text limits stand (`daily_limits`: limit, count, reached and resets_at for each channel), so
    every signed-in role can see when messages have stopped.
    """
    return {**rule_metrics.describe(), "daily_limits": alert_service.daily_limits()}


@router.get("/alert-rules", response_model=list[AlertRuleResponse])
def list_rules(
    response: Response,
    device_id: UUID | None = None,
    metric: str | None = Query(default=None, max_length=50),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    page: Page = Depends(Page),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = limit_to_readable_devices(db.query(AlertRule), current_user, AlertRule.device_id)
    if device_id:
        # a single machine is checked directly so a refused id answers 404 as it does elsewhere
        get_device_for_read(db, current_user, device_id)
        q = q.filter(AlertRule.device_id == device_id)
    if metric is not None:
        if metric not in rule_metrics.RULE_METRICS:
            raise ApiError(422, Code.INVALID_FILTER, f"metric must be one of: {', '.join(rule_metrics.RULE_METRICS)}")
        q = q.filter(AlertRule.metric == metric)
    if from_ is not None:
        q = q.filter(AlertRule.created_at >= _utc(from_))
    if to is not None:
        q = q.filter(AlertRule.created_at <= _utc(to))
    set_total(response, q.count())
    return q.order_by(AlertRule.created_at.desc(), AlertRule.id.desc()).offset(page.offset).limit(page.limit).all()


@router.get("/alert-rules/{rule_id}", response_model=AlertRuleResponse)
def get_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise ApiError(404, Code.RULE_NOT_FOUND, "Alert rule not found")
    device = db.query(Device).filter(Device.id == rule.device_id).first()
    if device is None:
        raise ApiError(404, Code.RULE_NOT_FOUND, "Alert rule not found")
    require_device_read(current_user, device, detail="Alert rule not found", code=Code.RULE_NOT_FOUND)
    return rule


@router.post("/alert-rules", response_model=AlertRuleResponse, status_code=201)
def create_rule(
    payload: AlertRuleCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    idem = idempotency.begin(admin.id, "POST /alert-rules", idempotency_key, payload)
    if idem.replay is not None:
        return idem.replay
    with idem:
        # an unknown machine is a 404, as everywhere else and not a foreign key error
        if db.query(Device.id).filter(Device.id == payload.device_id).first() is None:
            raise ApiError(404, Code.DEVICE_NOT_FOUND, "Device not found")
        # **payload.model_dump() converts the Pydantic model to a dict and passes each key as a constructor argument
        rule = AlertRule(**payload.model_dump())
        db.add(rule)
        db.commit()
        db.refresh(rule)
        idem.save(201, AlertRuleResponse.model_validate(rule).model_dump(mode="json"))
    return rule


def _close_rule_alerts(db: Session, rule_id: UUID, why: str) -> None:
    """Close the open alert of a rule and forget what was being watched. The caller commits."""
    now = datetime.now(timezone.utc)
    for alert in db.query(Alert).filter(Alert.rule_id == rule_id, Alert.kind == "rule", Alert.resolved.is_(False)):
        alert.resolved = True
        alert.resolved_at = now
        alert.message = f"{alert.message} (closed: {why})"
    db.query(RuleState).filter(RuleState.rule_id == rule_id).delete()


def _patch_rule(rule_id: UUID, payload: AlertRuleUpdate, db: Session) -> AlertRule:
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise ApiError(404, Code.RULE_NOT_FOUND, "Alert rule not found")
    before = (rule.metric, rule.condition)
    # a field left out is kept. for_seconds and clear_margin may be set back to null, which means the default. Any other null is a 422
    changed = apply_patch(rule, payload, clearable={"for_seconds", "clear_margin"})
    # an open alert is about the metric and condition it was raised for. If either changed it no longer describes the rule,
    # so it is closed and the rule starts again. A new threshold, margin, hold or severity keeps the alert open: the next
    # readings are judged by the new values (a lower severity stays as raised, a critical one escalates)
    if (rule.metric, rule.condition) != before:
        _close_rule_alerts(db, rule.id, "the rule was changed")
    elif "threshold" in changed:
        db.query(RuleState).filter(RuleState.rule_id == rule.id).update({"breach_since": None, "clear_since": None, "hold_count": 0, "hold_peak": None})
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/alert-rules/{rule_id}", response_model=AlertRuleResponse)
def update_rule(
    rule_id: UUID,
    payload: AlertRuleUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return _patch_rule(rule_id, payload, db)


# PUT kept as an alias for this release: it merged like a PATCH, so it is one
@router.put("/alert-rules/{rule_id}", response_model=AlertRuleResponse, deprecated=True)
def update_rule_put(
    rule_id: UUID,
    payload: AlertRuleUpdate,
    response: Response,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    deprecate(response, f"/api/v1/alert-rules/{rule_id}")
    return _patch_rule(rule_id, payload, db)


@router.delete("/alert-rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise ApiError(404, Code.RULE_NOT_FOUND, "Alert rule not found")
    # its open alert would be left with no rule to resolve it, so it is closed here and says why
    _close_rule_alerts(db, rule.id, "the rule was deleted")
    db.delete(rule)
    db.commit()
