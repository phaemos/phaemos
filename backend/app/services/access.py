"""
Who may see and who may change a machine.

These rules used to live in routes/devices.py. They sit here so every route that
touches something belonging to a machine (readings, alerts, rules, tickets,
maintenance windows, the health totals and the live socket) applies the same answer.

Read: admins and viewers see every machine, technicians see their own and unowned ones.
Write: admins change every machine, technicians their own and unowned ones, viewers none.
An unknown or empty role gets nothing.

A machine that exists but may not be read answers exactly like one that does not exist
(404), so the API does not reveal which ids are real. Someone who may read a machine but
not change it gets 403 on a write.
"""

from uuid import UUID

from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import Session

from app.errors import ApiError, Code
from app.models.alert import Alert
from app.models.device import Device
from app.models.ticket import Ticket
from app.models.user import User

# an explicit list, so a role that is empty, misspelt or added later gets nothing by default
ROLES = ("admin", "technician", "viewer")


def _owns_or_shared(user: User, device: Device) -> bool:
    return device.owner_id is None or device.owner_id == user.id


def can_read_device(user: User, device: Device) -> bool:
    if user.role in ("admin", "viewer"):
        return True
    return user.role == "technician" and _owns_or_shared(user, device)


def can_write_device(user: User, device: Device) -> bool:
    if user.role == "admin":
        return True
    return user.role == "technician" and _owns_or_shared(user, device)


def readable_device_clause(user: User):
    """SQL condition on Device for the machines the user may read. None means no limit."""
    if user.role in ("admin", "viewer"):
        return None
    if user.role == "technician":
        return or_(Device.owner_id == user.id, Device.owner_id.is_(None))
    return false()


def limit_to_readable_devices(query, user: User, device_id_column, allow_no_device: bool = False):
    """Narrow a query on a table with a device id column to rows on machines the user may read.

    allow_no_device keeps rows whose device id is empty (a window with no machine).
    """
    clause = readable_device_clause(user)
    if clause is None:
        return query
    readable = device_id_column.in_(select(Device.id).where(clause))
    if allow_no_device:
        readable = or_(device_id_column.is_(None), readable)
    return query.filter(readable)


def limit_tickets_to_readable(query, user: User):
    """Narrow a ticket query to tickets on machines the user may read.

    A ticket belongs to the machine it names or, failing that, to its alert's machine.
    One tied to neither is visible to admins, viewers, its creator and its assignee only.
    """
    if user.role not in ROLES:
        return query.filter(false())
    clause = readable_device_clause(user)
    if clause is None:
        return query
    readable = select(Device.id).where(clause)
    via_alert = Ticket.alert_id.in_(select(Alert.id).where(Alert.device_id.in_(readable)))
    # a ticket tied to no machine can be one whose machine was deleted, so it is not open to every
    # technician. Its creator and its assignee still see it and admins and viewers see everything
    own_machineless = and_(
        Ticket.alert_id.is_(None), or_(Ticket.created_by == user.id, Ticket.assigned_to == user.id)
    )
    return query.filter(
        or_(
            Ticket.device_id.in_(readable),
            and_(Ticket.device_id.is_(None), or_(via_alert, own_machineless)),
        )
    )


def machine_of_ticket(db: Session, ticket: Ticket) -> Device | None:
    """The machine a ticket belongs to: the one it names or, failing that, its alert's machine."""
    device_id = ticket.device_id
    if device_id is None and ticket.alert_id is not None:
        alert = db.query(Alert).filter(Alert.id == ticket.alert_id).first()
        device_id = alert.device_id if alert else None
    if device_id is None:
        return None
    return db.query(Device).filter(Device.id == device_id).first()


def can_read_ticket(user: User, ticket: Ticket, machine: Device | None) -> bool:
    if machine is not None:
        return can_read_device(user, machine)
    # no machine, perhaps because it was deleted: admins and viewers read everything and a
    # technician reads only what they raised or were given
    if user.role in ("admin", "viewer"):
        return True
    return user.role == "technician" and user.id in (ticket.created_by, ticket.assigned_to)


def can_write_ticket(user: User, ticket: Ticket, machine: Device | None) -> bool:
    if machine is not None:
        return can_write_device(user, machine)
    if user.role == "admin":
        return True
    return user.role == "technician" and user.id in (ticket.created_by, ticket.assigned_to)


def require_device_read(user: User, device: Device, detail: str = "Device not found", code: str = Code.DEVICE_NOT_FOUND) -> None:
    # 404 and not 403, so a refused machine looks the same as one that does not exist
    if not can_read_device(user, device):
        raise ApiError(404, code, detail)


def require_device_write(user: User, device: Device) -> None:
    # callers check the read rule first, so reaching here means the caller can see the machine
    if not can_write_device(user, device):
        raise ApiError(403, Code.DEVICE_ACCESS_DENIED, "Access denied")


def get_device_for_read(db: Session, user: User, device_id: UUID) -> Device:
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise ApiError(404, Code.DEVICE_NOT_FOUND, "Device not found")
    require_device_read(user, device)
    return device


def get_device_for_write(db: Session, user: User, device_id: UUID) -> Device:
    device = get_device_for_read(db, user, device_id)
    require_device_write(user, device)
    return device
