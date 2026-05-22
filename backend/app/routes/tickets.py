from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate, TicketUpdate, TicketResponse

router = APIRouter()


# `status: str | None = None` becomes an optional query parameter, e.g. GET /tickets?status=open
@router.get("", response_model=list[TicketResponse])
def list_tickets(status: str | None = None, db: Session = Depends(get_db)):
    # Assign the query to a variable so we can optionally chain filters before executing it
    q = db.query(Ticket)
    # A truthy check on `status` also correctly skips the filter when an empty string is passed
    if status:
        q = q.filter(Ticket.status == status)
    # Show newest tickets first — important for maintenance workflows where recent issues take priority
    return q.order_by(Ticket.created_at.desc()).all()


@router.post("", response_model=TicketResponse, status_code=201)
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db)):
    # TODO: inject current user id from JWT token (Phase 2)
    # model_dump() converts the validated Pydantic object into a plain dict the SQLAlchemy model can accept
    ticket = Ticket(**payload.model_dump())
    db.add(ticket)   # register the object with the session — no SQL is sent yet
    db.commit()      # write the INSERT to the database and finalize the transaction
    # After commit the session expires the object; refresh re-fetches it so auto-set fields (id, etc.) are available
    db.refresh(ticket)
    return ticket


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket(ticket_id: UUID, db: Session = Depends(get_db)):
    # .first() is safe here — returns None instead of raising an exception when no row is found
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        # HTTP 404 tells the client the resource doesn't exist, which is more informative than a 500 server error
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


# PATCH allows partial updates — the client only sends fields they want to change
@router.patch("/{ticket_id}", response_model=TicketResponse)
def update_ticket(ticket_id: UUID, payload: TicketUpdate, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    # exclude_none=True means fields the client omitted are not included, preventing accidental overwrites with None
    for field, value in payload.model_dump(exclude_none=True).items():
        # setattr lets us update any attribute by name dynamically rather than writing one line per field
        setattr(ticket, field, value)
    db.commit()
    db.refresh(ticket)
    return ticket
