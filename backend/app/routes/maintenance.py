from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.maintenance import MaintenanceWindow
from app.models.user import User
from app.routes.auth import get_current_user, require_admin

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class MaintenanceWindowCreate(BaseModel):
    label: str
    start_at: datetime
    end_at: datetime
    device_id: UUID | None = None
    suppress_alerts: bool = True


class MaintenanceWindowUpdate(BaseModel):
    label: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    device_id: UUID | None = None
    suppress_alerts: bool | None = None


class MaintenanceWindowResponse(BaseModel):
    id: UUID
    label: str
    start_at: datetime
    end_at: datetime
    device_id: UUID | None
    suppress_alerts: bool
    created_by: UUID | None

    model_config = {"from_attributes": True}


# ── Helper ───────────────────────────────────────────────────────────────────

def is_in_maintenance(db: Session, device_id: UUID) -> bool:
    """Return True if device_id is currently inside an active maintenance window."""
    now = datetime.now(timezone.utc)
    return (
        db.query(MaintenanceWindow)
        .filter(
            MaintenanceWindow.start_at <= now,
            MaintenanceWindow.end_at >= now,
            MaintenanceWindow.suppress_alerts.is_(True),
            or_(
                MaintenanceWindow.device_id == device_id,
                MaintenanceWindow.device_id.is_(None),
            ),
        )
        .first()
    ) is not None


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/maintenance-windows", response_model=list[MaintenanceWindowResponse])
def list_windows(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(MaintenanceWindow).order_by(MaintenanceWindow.start_at.desc()).all()


@router.post("/maintenance-windows", response_model=MaintenanceWindowResponse, status_code=201)
def create_window(
    body: MaintenanceWindowCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if body.end_at <= body.start_at:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")
    window = MaintenanceWindow(
        label=body.label,
        start_at=body.start_at,
        end_at=body.end_at,
        device_id=body.device_id,
        suppress_alerts=body.suppress_alerts,
        created_by=admin.id,
    )
    db.add(window)
    db.commit()
    db.refresh(window)
    return window


@router.patch("/maintenance-windows/{window_id}", response_model=MaintenanceWindowResponse)
def update_window(
    window_id: UUID,
    body: MaintenanceWindowUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    window = db.query(MaintenanceWindow).filter(MaintenanceWindow.id == window_id).first()
    if not window:
        raise HTTPException(status_code=404, detail="Maintenance window not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(window, field, value)
    if window.end_at <= window.start_at:
        raise HTTPException(status_code=400, detail="end_at must be after start_at")
    db.commit()
    db.refresh(window)
    return window


@router.delete("/maintenance-windows/{window_id}", status_code=204)
def delete_window(
    window_id: UUID,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    window = db.query(MaintenanceWindow).filter(MaintenanceWindow.id == window_id).first()
    if not window:
        raise HTTPException(status_code=404, detail="Maintenance window not found")
    db.delete(window)
    db.commit()
