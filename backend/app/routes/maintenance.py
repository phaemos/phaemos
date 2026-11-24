from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Page, set_total
from app.errors import ApiError, Code
from app.models.device import Device
from app.models.maintenance import MaintenanceWindow
from app.models.user import User
from app.patching import apply_patch
from app.routes.auth import get_current_user, require_admin
from app.schemas.maintenance import MaintenanceWindowCreate, MaintenanceWindowResponse, MaintenanceWindowUpdate
from app.services import idempotency
from app.services.access import can_read_device, limit_to_readable_devices
from app.services.maintenance_service import is_in_maintenance  # noqa: F401  (kept importable from here)

router = APIRouter()


def _utc(when: datetime) -> datetime:
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


@router.get("/maintenance-windows", response_model=list[MaintenanceWindowResponse])
def list_windows(
    response: Response,
    device_id: UUID | None = None,
    # a window is "active" while now lies inside it. Omit it for all of them
    active: bool | None = None,
    from_: datetime | None = Query(default=None, alias="from", description="Windows that end at or after this time"),
    to: datetime | None = Query(default=None, description="Windows that start at or before this time"),
    page: Page = Depends(Page),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # fleet-wide windows (no machine) stay visible to everyone
    q = limit_to_readable_devices(
        db.query(MaintenanceWindow), current_user, MaintenanceWindow.device_id, allow_no_device=True
    )
    if device_id is not None:
        q = q.filter(MaintenanceWindow.device_id == device_id)
    if active is not None:
        now = datetime.now(timezone.utc)
        inside = (MaintenanceWindow.start_at <= now) & (MaintenanceWindow.end_at >= now)
        q = q.filter(inside if active else ~inside)
    if from_ is not None:
        q = q.filter(MaintenanceWindow.end_at >= _utc(from_))
    if to is not None:
        q = q.filter(MaintenanceWindow.start_at <= _utc(to))
    set_total(response, q.count())
    return q.order_by(MaintenanceWindow.start_at.desc(), MaintenanceWindow.id.desc()).offset(page.offset).limit(page.limit).all()


@router.get("/maintenance-windows/{window_id}", response_model=MaintenanceWindowResponse)
def get_window(
    window_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    window = db.query(MaintenanceWindow).filter(MaintenanceWindow.id == window_id).first()
    if not window:
        raise ApiError(404, Code.WINDOW_NOT_FOUND, "Maintenance window not found")
    if window.device_id is not None:
        device = db.query(Device).filter(Device.id == window.device_id).first()
        # a window on a machine the caller may not read looks like one that does not exist
        if device is None or not can_read_device(current_user, device):
            raise ApiError(404, Code.WINDOW_NOT_FOUND, "Maintenance window not found")
    return window


@router.post("/maintenance-windows", response_model=MaintenanceWindowResponse, status_code=201)
def create_window(
    body: MaintenanceWindowCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    idem = idempotency.begin(admin.id, "POST /maintenance-windows", idempotency_key, body)
    if idem.replay is not None:
        return idem.replay
    with idem:
        if body.end_at <= body.start_at:
            raise ApiError(422, Code.INVALID_RANGE, "end_at must be after start_at")
        # an unknown machine is a 404, as everywhere else and not a foreign key error that answers 500
        if body.device_id is not None and db.query(Device.id).filter(Device.id == body.device_id).first() is None:
            raise ApiError(404, Code.DEVICE_NOT_FOUND, "Device not found")
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
        idem.save(201, MaintenanceWindowResponse.model_validate(window).model_dump(mode="json"))
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
        raise ApiError(404, Code.WINDOW_NOT_FOUND, "Maintenance window not found")
    # checked before anything is changed, so a refused update leaves the window as it was (and never needs a rollback)
    sent = body.model_dump(exclude_unset=True)
    start = _utc(sent["start_at"]) if sent.get("start_at") is not None else _utc(window.start_at)
    end = _utc(sent["end_at"]) if sent.get("end_at") is not None else _utc(window.end_at)
    if end <= start:
        raise ApiError(422, Code.INVALID_RANGE, "end_at must be after start_at")
    if sent.get("device_id") is not None and db.query(Device.id).filter(Device.id == sent["device_id"]).first() is None:
        raise ApiError(404, Code.DEVICE_NOT_FOUND, "Device not found")
    # null on device_id makes the window fleet-wide. Every other field must keep a value
    apply_patch(window, body, clearable={"device_id"})
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
        raise ApiError(404, Code.WINDOW_NOT_FOUND, "Maintenance window not found")
    db.delete(window)
    db.commit()
