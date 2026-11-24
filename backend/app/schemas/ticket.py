from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, Field

# fixed lists, so a ticket never holds free text where a page expects one of a few words
TicketStatus = Literal["open", "in_progress", "resolved", "closed"]
TicketPriority = Literal["low", "medium", "high", "critical"]


class TicketCreate(BaseModel):
    device_id:   UUID | None = None
    alert_id:    UUID | None = None
    # cap title and description to prevent storage exhaustion from oversized payloads.
    title:       str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    priority:    TicketPriority | None = None


class TicketUpdate(BaseModel):
    title:       str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status:      TicketStatus | None = None
    priority:    TicketPriority | None = None
    assigned_to: UUID | None = None


class TicketResponse(BaseModel):
    id:          UUID
    device_id:   UUID | None
    alert_id:    UUID | None
    title:       str | None
    description: str | None
    status:      str
    priority:    str | None
    assigned_to: UUID | None
    created_by:  UUID | None
    # names only, so a page can show who without being able to list users
    assigned_to_name: str | None = None
    created_by_name:  str | None = None
    created_at:    datetime
    updated_at:    datetime
    ticket_number: int | None = None

    model_config = {"from_attributes": True}
