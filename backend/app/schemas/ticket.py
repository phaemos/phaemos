from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    device_id:   UUID | None = None
    alert_id:    UUID | None = None
    # I cap title and description to prevent storage exhaustion from oversized payloads.
    title:       str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    priority:    str | None = Field(default=None, max_length=20)   # low / medium / high / critical


class TicketUpdate(BaseModel):
    title:       str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status:      str | None = Field(default=None, max_length=20)   # open / in_progress / closed
    priority:    str | None = Field(default=None, max_length=20)
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
    created_at:    datetime
    updated_at:    datetime
    ticket_number: int | None = None

    model_config = {"from_attributes": True}
