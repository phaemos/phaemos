from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MaintenanceWindowCreate(BaseModel):
    # the column holds 200 characters
    label: str = Field(max_length=200)
    start_at: datetime
    end_at: datetime
    # null makes the window fleet-wide: it silences every machine
    device_id: UUID | None = None
    suppress_alerts: bool = True


class MaintenanceWindowUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    start_at: datetime | None = None
    end_at: datetime | None = None
    # an explicit null makes the window fleet-wide
    device_id: UUID | None = None
    suppress_alerts: bool | None = None


class MaintenanceWindowResponse(BaseModel):
    id: UUID
    label: str
    start_at: datetime
    end_at: datetime
    device_id: UUID | None
    suppress_alerts: bool
    created_by: UUID | None

    model_config = {"from_attributes": True}
