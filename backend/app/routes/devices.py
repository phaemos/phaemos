from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel
from sqlalchemy import any_, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Page, set_total
from app.errors import ApiError, Code
from app.patching import apply_patch
from app.models.alert import AlertRule
from app.models.device import Device
from app.models.device_health import DeviceHealth
# DeviceWithKey is a separate schema that includes the api_key field - it is only exposed at registration time
from app.schemas.misc_responses import BatchFirmwareResult
from app.schemas.device import DeviceCreate, DeviceHealthResponse, ModelStatus, DeviceUpdate, DeviceResponse, DeviceWithKey
from app.routes.auth import fresh_proof, get_current_user, require_admin
from app.models.user import User
from app.services import audit_service, device_keys, health_service, idempotency, ml_service, token_access
from app.services.access import get_device_for_read, get_device_for_write, readable_device_clause

# APIRouter groups related endpoints; the prefix ("/devices") is set when the router is mounted in main.py
router = APIRouter()


def _with_health(db: Session, devices: list[Device]) -> list[DeviceResponse]:
    # one query for every device's vitals, so a list does not cost a query per machine
    rows = {}
    if devices:
        rows = {h.device_id: h for h in db.query(DeviceHealth).filter(DeviceHealth.device_id.in_([d.id for d in devices]))}
    # the rules of the devices that have a fault, in one query, to say which of them cannot be evaluated
    faulty = [
        d.id for d in devices
        if rows.get(d.id) is not None and (rows[d.id].faults or d.not_fitted or rows[d.id].not_fitted_by_firmware)
    ]
    rules: dict = {}
    if faulty:
        for rule in db.query(AlertRule).filter(AlertRule.device_id.in_(faulty)):
            rules.setdefault(rule.device_id, []).append(rule)
    out = []
    for device in devices:
        item = DeviceResponse.model_validate(device)
        # read from the loaded model bundle, so a list of machines costs no query
        item.model = ModelStatus.model_validate(ml_service.model_status(device.id, device.type))
        row = rows.get(device.id)
        if row is not None:
            health = DeviceHealthResponse.model_validate(row)
            # the admin's list and the firmware's list together. A fault on a sensor that is not fitted here is shown as
            # that and not as a failure
            fitted_out = health_service.effective_not_fitted(device, row)
            health.faults = {k: ("not_fitted" if k in fitted_out else v) for k, v in (row.faults or {}).items()}
            health.server_faults = dict((device.stuck_state or {}).get("_faults") or {})
            health.rules_cannot_evaluate = health_service.cannot_evaluate(
                rules.get(device.id, []), row.faults or {}, fitted_out,
            )
            item.health = health
            item.not_fitted_by_firmware = list(row.not_fitted_by_firmware or [])
        out.append(item)
    return out


def _owner_exists(db: Session, owner_id) -> bool:
    # a machine is owned by someone who can work on it, so a viewer or an unknown role cannot be an owner
    # the row is locked, so an account deletion running at the same time waits and cannot leave a machine owned by a
    # user who no longer exists
    owner = (
        db.query(User)
        .filter(User.id == owner_id, User.role.in_(("admin", "technician")), User.is_service.is_(False))
        .with_for_update(of=User)
        .first()
    )
    return owner is not None


# response_model tells FastAPI which Pydantic schema to use when serialising the return value
@router.get("", response_model=list[DeviceResponse])
def list_devices(
    response: Response,
    # name is an exact match (not case sensitive). search is a contains match on the name (not case sensitive)
    name: str | None = None,
    search: str | None = None,
    # status is the older two-state word the system keeps. link_state is online, late or offline from the age of the last post
    status: Literal["online", "offline", "warning", "fault"] | None = None,
    link_state: Literal["online", "late", "offline"] | None = None,
    tag: str | None = None,
    page: Page = Depends(Page),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Device)
    # apply ownership filtering here rather than in a middleware so the logic
    # is explicit and easy to audit: admins and viewers see everything; technicians
    # see only their own devices plus unowned (shared) devices.
    # the rule itself lives in services/access.py so other routes share it
    clause = readable_device_clause(current_user)
    if clause is not None:
        q = q.filter(clause)
    if name:
        q = q.filter(func.lower(Device.name) == name.lower())
    if search:
        # the user's own % and _ are text here, not wildcards
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        q = q.filter(Device.name.ilike(f"%{escaped}%", escape="\\"))
    if status:
        q = q.filter(Device.status == status)
    if link_state:
        q = q.filter(Device.link_state == link_state)
    if tag:
        q = q.filter(tag == any_(Device.tags))
    # the total for the same filters, so a page can show how many there are and page truthfully
    set_total(response, q.count())
    # newest first and ending in id so a page never swaps two machines made in the same instant
    return _with_health(db, q.order_by(Device.created_at.desc(), Device.id.desc()).offset(page.offset).limit(page.limit).all())


# status_code=201 (Created) is more semantically correct than 200 (OK) for a resource creation endpoint
@router.post("", response_model=DeviceWithKey, status_code=201)
def register_device(
    payload: DeviceCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # a retry after a lost answer would make a second machine and a second key. With an Idempotency-Key the first answer, key
    # included, comes back (stored encrypted for 24 hours: services/idempotency.py) and nothing is made twice
    idem = idempotency.begin(admin.id, "POST /devices", idempotency_key, payload)
    if idem.replay is not None:
        return idem.replay
    with idem:
        device = _register(payload, db)
        idem.save(201, DeviceWithKey.model_validate(device).model_dump(mode="json"))
    return device


def _register(payload: DeviceCreate, db: Session) -> Device:
    if payload.owner_id is not None and not _owner_exists(db, payload.owner_id):
        raise ApiError(404, Code.OWNER_NOT_FOUND, "Owner not found")
    # API key is generated once at registration and used by the device for ingest auth.
    # token_urlsafe(32) produces a 43-character URL-safe random string - cryptographically secure
    api_key = device_keys.new_key()
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
    # a missing machine and one this user may not read both answer 404, so ids cannot be probed
    return _with_health(db, [get_device_for_read(db, current_user, device_id)])[0]


_ADMIN_ONLY_FIELDS = ("owner_id", "tags", "firmware_version", "not_fitted", "expected_interval_s")


# PATCH is used instead of PUT because only the fields that are sent are updated, not the whole resource
@router.patch("/{device_id}", response_model=DeviceResponse)
def update_device(
    request: Request,
    device_id: UUID,
    payload: DeviceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = get_device_for_write(db, current_user, device_id)
    # exclude_unset keeps an explicit null for owner_id (it clears the owner). Every other
    # null is skipped as before, because those columns cannot be empty.
    changes = payload.model_dump(exclude_unset=True)
    if not token_access.acts_as_admin(request, current_user):
        # owner, tags and firmware version are admin matters: a technician who could set them
        # could claim a machine, hand it on or get round the admin-only tag routes
        for field in _ADMIN_ONLY_FIELDS:
            # a null clears owner_id and firmware_version, so for those it is a change like any other
            if field in changes and (changes[field] is not None or field in ("owner_id", "firmware_version")):
                raise ApiError(403, Code.ADMIN_ONLY_FIELD, f"Only an admin can change {field}")
    if changes.get("owner_id") is not None:
        if not _owner_exists(db, changes["owner_id"]):
            raise ApiError(404, Code.OWNER_NOT_FOUND, "Owner not found")
    # a field left out is kept. owner_id, location and firmware_version may be cleared with null. Any other null is a 422
    apply_patch(device, changes, clearable={"owner_id", "location", "firmware_version"})
    db.commit()
    db.refresh(device)
    return device


@router.post("/{device_id}/rotate-key", response_model=DeviceWithKey)
def rotate_api_key(
    device_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _proof: None = Depends(fresh_proof("rotate this machine's key", admin_only=False)),
):
    # the response carries the new key and the old one stops working at once, so rotation is narrower than a write: an admin or
    # the machine's owner. A technician who merely shares an unowned machine could otherwise lock the real node out and post as it
    device = get_device_for_write(db, current_user, device_id)
    if current_user.role != "admin" and device.owner_id != current_user.id:
        raise ApiError(403, Code.KEY_ROTATION_FORBIDDEN, "Only an admin or the machine's owner can rotate its key")
    device.api_key = device_keys.new_key()
    # a rotated key may mean new hardware: the anomaly detector starts again
    device.detector_state = None
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


@router.post("/{device_id}/accept-counter", response_model=DeviceResponse)
def accept_new_counter(
    device_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Accept a new (boot, seq) counter for a machine whose flash was wiped.

    A machine that sends the pair must always send a newer one. A hub whose flash was erased starts its boot count again at 1
    and would be refused for ever. This forgets the last pair so the next post sets the new start. The machine still has to
    send the pair. Admin only and audited.
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise ApiError(404, Code.DEVICE_NOT_FOUND, "Device not found")
    old = (device.last_boot, device.last_seq)
    device.detector_state = None
    pushed = device.counter_jump_note
    device.counter_jump_at = None
    device.counter_jump_note = None
    device.last_boot = None
    device.last_seq = None
    device.replay_refused = 0
    device.replay_refused_at = None
    db.commit()
    db.refresh(device)
    audit_service.log_action(
        db,
        user_id=str(current_user.id),
        action="replay_counter_accepted",
        resource="device",
        resource_id=str(device_id),
        detail=f"name={device.name} previous_boot={old[0]} previous_seq={old[1]}"
        + (f" counter_jump={pushed} key_rotation_advised=true" if pushed else ""),
    )
    return _with_health(db, [device])[0]


# status_code=204 (No Content) signals success with no response body - standard for DELETE
@router.delete("/{device_id}", status_code=204)
def delete_device(
    device_id: UUID,
    db: Session = Depends(get_db),
    # deleting matches creating: admins only.
    current_user: User = Depends(require_admin),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise ApiError(404, Code.DEVICE_NOT_FOUND, "Device not found")
    db.delete(device)  # mark the object for deletion in the current session
    db.commit()        # execute the DELETE statement and end the transaction

    # log after commit so the audit row references a device that no longer exists in a
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


@router.post("/{device_id}/tags", response_model=DeviceResponse, status_code=201)
def add_tag(
    device_id: UUID,
    body: TagBody,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise ApiError(404, Code.DEVICE_NOT_FOUND, "Device not found")
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
        raise ApiError(404, Code.DEVICE_NOT_FOUND, "Device not found")
    device.tags = [t for t in device.tags if t != tag]
    db.commit()
    db.refresh(device)
    return device


# ── Batch operations ─────────────────────────────────────────────────────────

class BatchFirmwareUpdate(BaseModel):
    tag: str
    version: str


@router.post("/batch/firmware-update", status_code=202, response_model=BatchFirmwareResult)
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
