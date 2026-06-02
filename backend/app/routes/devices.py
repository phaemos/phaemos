import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import any_, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.device import Device
# DeviceWithKey is a separate schema that includes the api_key field - we only expose it at registration time
from app.schemas.device import DeviceCreate, DeviceUpdate, DeviceResponse, DeviceWithKey
from app.routes.auth import get_current_user, require_admin
from app.models.user import User
from app.services import audit_service

# APIRouter groups related endpoints; the prefix ("/devices") is set when the router is mounted in main.py
router = APIRouter()


# response_model tells FastAPI which Pydantic schema to use when serialising the return value
@router.get("", response_model=list[DeviceResponse])
def list_devices(
    skip: int = 0,
    limit: int = 20,
    search: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Device).order_by(Device.created_at.desc())
    # I apply ownership filtering here rather than in a middleware so the logic
    # is explicit and easy to audit: admins and viewers see everything; technicians
    # see only their own devices plus unowned (shared) devices.
    if current_user.role == "technician":
        q = q.filter(
            or_(Device.owner_id == current_user.id, Device.owner_id.is_(None))
        )
    if search:
        q = q.filter(Device.name.ilike(f"%{search}%"))
    if status:
        q = q.filter(Device.status == status)
    if tag:
        q = q.filter(tag == any_(Device.tags))
    return q.offset(skip).limit(limit).all()


# status_code=201 (Created) is more semantically correct than 200 (OK) for a resource creation endpoint
@router.post("", response_model=DeviceWithKey, status_code=201)
def register_device(
    payload: DeviceCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    # API key is generated once at registration and used by the device for ingest auth.
    # token_urlsafe(32) produces a 43-character URL-safe random string - cryptographically secure
    api_key = secrets.token_urlsafe(32)
    # **payload.model_dump() unpacks the Pydantic model into keyword arguments for the SQLAlchemy constructor
    device  = Device(api_key=api_key, **payload.model_dump())
    db.add(device)   # stage the new object in the session (not yet written to the DB)
    db.commit()      # flush and permanently save to the database
    # db.refresh reloads the object from the DB so auto-generated fields (e.g. id, created_at) are populated
    db.refresh(device)
    return device


# UUID in the path is automatically validated and parsed by FastAPI - a non-UUID value returns 422
@router.get("/{device_id}", response_model=DeviceResponse)
def get_device(
    device_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # .first() returns None if no row matches, avoiding an exception from .one()
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        # Raising HTTPException short-circuits the function and sends a JSON error response to the client
        raise HTTPException(status_code=404, detail="Device not found")
    if (
        current_user.role == "technician"
        and device.owner_id is not None
        and device.owner_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Access denied")
    return device


# PATCH is used instead of PUT because we only update the fields that are sent, not the whole resource
@router.patch("/{device_id}", response_model=DeviceResponse)
def update_device(
    device_id: UUID,
    payload: DeviceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if (
        current_user.role == "technician"
        and device.owner_id is not None
        and device.owner_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Access denied")
    # exclude_none=True skips fields the client didn't send, so we only overwrite what was explicitly provided
    for field, value in payload.model_dump(exclude_none=True).items():
        # setattr dynamically sets device.<field> = value without needing to name each field explicitly
        setattr(device, field, value)
    db.commit()
    db.refresh(device)
    return device


@router.post("/{device_id}/rotate-key", response_model=DeviceWithKey)
def rotate_api_key(
    device_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # I require auth so only legitimate operators can rotate keys, not
    # unauthenticated callers who might know a device UUID from other sources.
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.api_key = secrets.token_urlsafe(32)
    db.commit()
    db.refresh(device)
    audit_service.log_action(
        db,
        user_id=str(current_user.id),
        action="api_key_rotated",
        resource="device",
        resource_id=str(device_id),
        detail=f"name={device.name}",
    )
    return device


# status_code=204 (No Content) signals success with no response body - standard for DELETE
@router.delete("/{device_id}", status_code=204)
def delete_device(
    device_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    db.delete(device)  # mark the object for deletion in the current session
    db.commit()        # execute the DELETE statement and end the transaction

    # I log after commit so the audit row references a device that no longer exists in a
    # consistent state - logging before commit would record a deletion that might still roll back.
    audit_service.log_action(
        db,
        user_id=str(current_user.id),
        action="device_deleted",
        resource="device",
        resource_id=str(device_id),
        detail=f"name={device.name}",
    )


# ── Tag management ───────────────────────────────────────────────────────────

class TagBody(BaseModel):
    tag: str


@router.post("/{device_id}/tags", response_model=DeviceResponse)
def add_tag(
    device_id: UUID,
    body: TagBody,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if body.tag not in device.tags:
        device.tags = device.tags + [body.tag]
        db.commit()
        db.refresh(device)
    return device


@router.delete("/{device_id}/tags/{tag}", response_model=DeviceResponse)
def remove_tag(
    device_id: UUID,
    tag: str,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.tags = [t for t in device.tags if t != tag]
    db.commit()
    db.refresh(device)
    return device


# ── Batch operations ─────────────────────────────────────────────────────────

class BatchFirmwareUpdate(BaseModel):
    tag: str
    version: str


@router.post("/batch/firmware-update", status_code=202)
def batch_firmware_update(
    body: BatchFirmwareUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Queue a firmware version flag on all devices with the given tag.
    Devices pick up the new target version on their next /firmware/latest poll."""
    updated = (
        db.query(Device)
        .filter(body.tag == any_(Device.tags))
        .all()
    )
    for device in updated:
        device.firmware_version = body.version
    db.commit()
    return {"queued": len(updated), "tag": body.tag, "target_version": body.version}
