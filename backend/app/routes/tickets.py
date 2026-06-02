from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate, TicketUpdate, TicketResponse
from app.routes.auth import get_current_user
from app.models.user import User
from app.services import audit_service

router = APIRouter()


# `status: str | None = None` becomes an optional query parameter, e.g. GET /tickets?status=open
@router.get("", response_model=list[TicketResponse])
def list_tickets(
    status: str | None = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Assign the query to a variable so we can optionally chain filters before executing it
    q = db.query(Ticket)
    # A truthy check on `status` also correctly skips the filter when an empty string is passed
    if status:
        q = q.filter(Ticket.status == status)
    # Show newest tickets first - important for maintenance workflows where recent issues take priority
    return q.order_by(Ticket.created_at.desc()).offset(skip).limit(limit).all()


@router.post("", response_model=TicketResponse, status_code=201)
def create_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # I set created_by from the authenticated user so the audit trail is accurate.
    ticket = Ticket(**payload.model_dump(), created_by=current_user.id)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    # Serialise before audit call - audit_service commits its own transaction,
    # which expires the ORM object and breaks FastAPI serialisation if we return
    # the raw ORM object after that second commit.
    response = TicketResponse.model_validate(ticket)
    audit_service.log_action(
        db,
        user_id=str(current_user.id),
        action="ticket_created",
        resource="ticket",
        resource_id=str(response.id),
        detail=f"title={response.title!r} priority={response.priority}",
    )
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
        raise HTTPException(status_code=404, detail="Ticket not found")
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
        raise HTTPException(status_code=404, detail="Ticket not found")

    old_status = ticket.status
    # exclude_none=True means fields the client omitted are not included, preventing accidental overwrites with None
    updates = payload.model_dump(exclude_none=True)
    for field, value in updates.items():
        setattr(ticket, field, value)
    db.commit()
    db.refresh(ticket)

    # Serialise to Pydantic before the audit call for the same reason as create_ticket -
    # audit_service.log_action() commits its own transaction which expires ORM objects.
    response = TicketResponse.model_validate(ticket)

    # I only log when fields actually changed - empty PATCH calls should not pollute the audit log.
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
