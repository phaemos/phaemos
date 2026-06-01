from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
# Alert is a fired event; AlertRule is the config that defines when an alert should fire
from app.models.alert import Alert, AlertRule
from app.schemas.alert import AlertRuleCreate, AlertRuleUpdate, AlertRuleResponse, AlertResponse
from app.routes.auth import get_current_user
from app.models.user import User
from app.services import audit_service

router = APIRouter()


# `resolved: bool | None = None` makes this query parameter optional - omitting it returns all alerts
@router.get("/alerts", response_model=list[AlertResponse])
def list_alerts(resolved: bool | None = None, db: Session = Depends(get_db)):
    # Build the query object first, then conditionally append filters before executing
    q = db.query(Alert)
    # Only add the resolved filter when the caller explicitly passes ?resolved=true or ?resolved=false
    if resolved is not None:
        q = q.filter(Alert.resolved == resolved)
    # Show most recently triggered alerts first - useful for dashboards
    return q.order_by(Alert.triggered_at.desc()).all()


@router.get("/alerts/{device_id}", response_model=list[AlertResponse])
def alerts_for_device(device_id: UUID, db: Session = Depends(get_db)):
    return (
        db.query(Alert)
        .filter(Alert.device_id == device_id)
        # Chain .order_by on the same query object - SQLAlchemy queries are lazily built until .all()/.first()
        .order_by(Alert.triggered_at.desc())
        .all()
    )


# PATCH is appropriate here because we're updating a specific field (resolved status), not replacing the whole resource
@router.patch("/alerts/{alert_id}/resolve", response_model=AlertResponse)
def resolve_alert(
    alert_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.resolved    = True
    # datetime.now(timezone.utc) produces a timezone-aware timestamp - always use UTC in APIs to avoid timezone confusion
    alert.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)

    # I serialise to Pydantic BEFORE calling audit_service because audit_service
    # calls db.commit() internally, which expires all SQLAlchemy ORM objects in
    # the session. FastAPI would then fail to serialise the expired alert object.
    # Capturing it as a Pydantic model first avoids that race.
    response = AlertResponse.model_validate(alert)

    audit_service.log_action(
        db,
        user_id=str(current_user.id),
        action="alert_resolved",
        resource="alert",
        resource_id=str(alert_id),
        detail=f"severity={response.severity}",
    )
    return response


@router.get("/alert-rules", response_model=list[AlertRuleResponse])
def list_rules(device_id: UUID | None = None, db: Session = Depends(get_db)):
    q = db.query(AlertRule)
    if device_id:
        q = q.filter(AlertRule.device_id == device_id)
    return q.order_by(AlertRule.created_at.desc()).all()


@router.post("/alert-rules", response_model=AlertRuleResponse, status_code=201)
def create_rule(payload: AlertRuleCreate, db: Session = Depends(get_db)):
    # **payload.model_dump() converts the Pydantic model to a dict and passes each key as a constructor argument
    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/alert-rules/{rule_id}", response_model=AlertRuleResponse)
def update_rule(rule_id: UUID, payload: AlertRuleUpdate, db: Session = Depends(get_db)):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/alert-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: UUID, db: Session = Depends(get_db)):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    db.delete(rule)
    db.commit()
