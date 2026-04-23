from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class TicketCreate(BaseModel):
    device_id:   UUID | None = None
    alert_id:    UUID | None = None
    title:       str
    description: str | None = None
    priority:    str | None = None   # low / medium / high / critical


class TicketUpdate(BaseModel):
    title:       str | None = None
    description: str | None = None
    status:      str | None = None   # open / in_progress / closed
    priority:    str | None = None
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
    created_at:  datetime
    updated_at:  datetime

    model_config = {"from_attributes": True}
