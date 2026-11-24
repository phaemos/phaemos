from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Page, set_total
from app.errors import ApiError, Code
from app.patching import apply_patch
from app.models.alert import Alert
from app.models.device import Device
from app.models.ticket import Ticket
from app.schemas.misc_responses import Assignee
from app.schemas.ticket import TicketCreate, TicketPriority, TicketResponse, TicketStatus, TicketUpdate
from app.routes.auth import get_current_user
from app.models.user import User
from app.services import audit_service, idempotency
from app.services.access import (
    can_read_ticket,
    can_write_ticket,
    get_device_for_read,
    limit_tickets_to_readable,
    machine_of_ticket,
    require_device_read,
    require_device_write,
)

router = APIRouter()


def _machine_for_new_ticket(
    db: Session, user: User, device_id: UUID | None, alert_id: UUID | None
) -> Device | None:
    # every refusal about a machine or alert the caller may not read is a plain 404, so a
    # ticket request cannot be used to find out which ids exist or which alert is whose.
    device = None
    if device_id is not None:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            raise ApiError(404, Code.DEVICE_NOT_FOUND, "Device not found")
        require_device_read(user, device)
    if alert_id is not None:
        alert = db.query(Alert).filter(Alert.id == alert_id).first()
        # with both ids given, the alert must belong to that machine
        if not alert or (device is not None and alert.device_id != device.id):
            raise ApiError(404, Code.ALERT_NOT_FOUND, "Alert not found")
        if device is None:
            device = db.query(Device).filter(Device.id == alert.device_id).first()
            if device is None:
                raise ApiError(404, Code.ALERT_NOT_FOUND, "Alert not found")
            require_device_read(user, device, detail="Alert not found", code=Code.ALERT_NOT_FOUND)
    return device


# `status` and `priority` are fixed sets: an unknown value is a 422 and not an empty list
@router.get("", response_model=list[TicketResponse])
def list_tickets(
    response: Response,
    status: TicketStatus | None = None,
    priority: TicketPriority | None = None,
    # the tickets about one machine, found through the ticket's machine or its alert's machine
    device_id: UUID | None = None,
    # the tickets raised from one alert, so an alert page can link to them
    alert_id: UUID | None = None,
    # the ticket's own number, for a tool that is given "ticket 42"
    ticket_number: int | None = None,
    page: Page = Depends(Page),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # assign the query to a variable so filters can be chained before executing it
    q = db.query(Ticket)
    # a technician gets only tickets on machines they may read, found through the
    # ticket's machine or its alert's machine. Tickets tied to neither stay visible.
    q = limit_tickets_to_readable(q, current_user)
    if status:
        q = q.filter(Ticket.status == status)
    if priority:
        q = q.filter(Ticket.priority == priority)
    if device_id is not None:
        # a machine the caller may not read answers 404 as it does everywhere
        get_device_for_read(db, current_user, device_id)
        q = q.filter(or_(Ticket.device_id == device_id, Ticket.alert_id.in_(db.query(Alert.id).filter(Alert.device_id == device_id))))
    if alert_id is not None:
        q = q.filter(Ticket.alert_id == alert_id)
    if ticket_number is not None:
        q = q.filter(Ticket.ticket_number == ticket_number)
    # the total for the same filters, so a page can show how many there are and page truthfully
    set_total(response, q.count())
    # show newest tickets first - important for maintenance workflows where recent issues take priority. Ends in id so a page never swaps rows
    return q.order_by(Ticket.created_at.desc(), Ticket.id.desc()).offset(page.offset).limit(page.limit).all()


@router.get("/assignees", response_model=list[Assignee])
def list_assignees(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The people a ticket can be assigned to: id and name only, never an email or phone number."""
    # a technician cannot list users, so this is how they assign within the team
    if current_user.role not in ("admin", "technician"):
        raise ApiError(403, Code.TICKET_ACCESS_DENIED, "Access denied")
    people = db.query(User).filter(User.role.in_(("admin", "technician")), User.is_service.is_(False)).order_by(User.name).all()
    return [{"id": str(p.id), "name": p.name} for p in people]


@router.post("", response_model=TicketResponse, status_code=201)
def create_ticket(
    payload: TicketCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # viewers are read-only. Anyone else needs write access to the machine the ticket is about.
    if current_user.role not in ("admin", "technician"):
        raise ApiError(403, Code.TICKET_ACCESS_DENIED, "Access denied")
    idem = idempotency.begin(current_user.id, "POST /tickets", idempotency_key, payload)
    if idem.replay is not None:
        return idem.replay
    with idem:
        return _create_ticket(payload, db, current_user, idem)


def _create_ticket(payload: TicketCreate, db: Session, current_user: User, idem):
    machine = _machine_for_new_ticket(db, current_user, payload.device_id, payload.alert_id)
    if machine is not None:
        require_device_write(current_user, machine)
    # set created_by from the authenticated user so the audit trail is accurate.
    fields = payload.model_dump()
    # a ticket made from an alert alone takes the alert's machine, so one lookup decides who may see it
    if machine is not None and fields.get("device_id") is None:
        fields["device_id"] = machine.id
    ticket = Ticket(**fields, created_by=current_user.id)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    # serialise before audit call - audit_service commits its own transaction,
    # which expires the ORM object and breaks FastAPI serialisation when the
    # raw ORM object is returned after that second commit.
    response = TicketResponse.model_validate(ticket)
    audit_service.log_action(
        db,
        user_id=str(current_user.id),
        action="ticket_created",
        resource="ticket",
        resource_id=str(response.id),
        detail=f"title={response.title!r} priority={response.priority}",
    )
    idem.save(201, response.model_dump(mode="json"))
    return response


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # .first() is safe here - returns None instead of raising an exception when no row is found
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        # HTTP 404 tells the client the resource doesn't exist, which is more informative than a 500 server error
        raise ApiError(404, Code.TICKET_NOT_FOUND, "Ticket not found")
    machine = machine_of_ticket(db, ticket)
    if not can_read_ticket(current_user, ticket, machine):
        raise ApiError(404, Code.TICKET_NOT_FOUND, "Ticket not found")
    return ticket


# PATCH allows partial updates - the client only sends fields they want to change
@router.patch("/{ticket_id}", response_model=TicketResponse)
def update_ticket(
    ticket_id: UUID,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise ApiError(404, Code.TICKET_NOT_FOUND, "Ticket not found")
    # a ticket on a machine the caller may not read looks like one that does not exist
    machine = machine_of_ticket(db, ticket)
    if not can_read_ticket(current_user, ticket, machine):
        raise ApiError(404, Code.TICKET_NOT_FOUND, "Ticket not found")
    # documented as admin or technician: viewers are read-only
    if current_user.role not in ("admin", "technician") or not can_write_ticket(current_user, ticket, machine):
        raise ApiError(403, Code.TICKET_ACCESS_DENIED, "Access denied")

    old_status = ticket.status
    # a field left out is kept. assigned_to and description may be cleared with null. Any other null is a 422
    sent = payload.model_dump(exclude_unset=True)
    if sent.get("assigned_to") is not None:
        # a service account has no inbox and no phone: it is refused as an unknown user would be
        assignee = db.query(User).filter(User.id == sent["assigned_to"], User.is_service.is_(False)).first()
        if not assignee:
            raise ApiError(404, Code.ASSIGNEE_NOT_FOUND, "Assignee not found")
        # only people on the assignee list and only someone who can open the ticket afterwards
        if assignee.role not in ("admin", "technician") or not can_read_ticket(assignee, ticket, machine):
            raise ApiError(422, Code.ASSIGNEE_REFUSED, "That person cannot be given this ticket")
    updates = sent
    apply_patch(ticket, payload, clearable={"assigned_to", "description"})
    db.commit()
    db.refresh(ticket)

    # serialise to Pydantic before the audit call for the same reason as create_ticket -
    # audit_service.log_action() commits its own transaction which expires ORM objects.
    response = TicketResponse.model_validate(ticket)

    # only log when fields actually changed - empty PATCH calls should not pollute the audit log.
    if updates:
        detail = f"fields={list(updates.keys())}"
        if "status" in updates and updates["status"] != old_status:
            detail += f" status={old_status}->{response.status}"
        audit_service.log_action(
            db,
            user_id=str(current_user.id),
            action="ticket_updated",
            resource="ticket",
            resource_id=str(ticket_id),
            detail=detail,
        )
    return response
