from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.alert import Alert, AlertRule
from app.schemas.alert import AlertRuleCreate, AlertRuleResponse, AlertResponse

router = APIRouter()


@router.get("/alerts", response_model=list[AlertResponse])
def list_alerts(resolved: bool | None = None, db: Session = Depends(get_db)):
    q = db.query(Alert)
    if resolved is not None:
        q = q.filter(Alert.resolved == resolved)
    return q.order_by(Alert.triggered_at.desc()).all()


@router.get("/alerts/{device_id}", response_model=list[AlertResponse])
def alerts_for_device(device_id: UUID, db: Session = Depends(get_db)):
    return (
        db.query(Alert)
        .filter(Alert.device_id == device_id)
        .order_by(Alert.triggered_at.desc())
        .all()
    )


@router.patch("/alerts/{alert_id}/resolve", response_model=AlertResponse)
def resolve_alert(alert_id: UUID, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.resolved    = True
    alert.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/alert-rules", response_model=AlertRuleResponse, status_code=201)
def create_rule(payload: AlertRuleCreate, db: Session = Depends(get_db)):
    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule
