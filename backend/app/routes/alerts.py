from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
# Alert is a fired event; AlertRule is the config that defines when an alert should fire
from app.models.alert import Alert, AlertRule
from app.schemas.alert import AlertRuleCreate, AlertRuleResponse, AlertResponse
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

    # I log after commit so the audit row is written even if the caller's surrounding context
    # were to roll back for unrelated reasons - audit_service commits its own transaction.
    audit_service.log_action(
        db,
        user_id=str(current_user.id),
        action="alert_resolved",
        resource="alert",
        resource_id=str(alert_id),
        detail=f"severity={alert.severity}",
    )
    return alert


@router.post("/alert-rules", response_model=AlertRuleResponse, status_code=201)
def create_rule(payload: AlertRuleCreate, db: Session = Depends(get_db)):
    # **payload.model_dump() converts the Pydantic model to a dict and passes each key as a constructor argument
    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule
