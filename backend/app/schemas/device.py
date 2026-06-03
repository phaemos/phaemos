from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


# --- DeviceCreate ---
# Used when a client (e.g. admin UI or POST /devices) registers a new device.
class DeviceCreate(BaseModel):
    # I cap string lengths to prevent storage exhaustion from oversized payloads.
    name:     str = Field(max_length=200)
    location: str | None = Field(default=None, max_length=200)
    type:     str | None = Field(default=None, max_length=50)
    # I allow owner_id at creation time so an admin can assign a device to a
    # technician in a single request rather than needing a follow-up PATCH.
    owner_id: UUID | None = None


# --- DeviceUpdate ---
# All fields are optional so clients can PATCH only the fields they want to change.
class DeviceUpdate(BaseModel):
    name:             str | None = Field(default=None, max_length=200)
    location:         str | None = Field(default=None, max_length=200)
    status:           str | None = Field(default=None, max_length=50)
    firmware_version: str | None = Field(default=None, max_length=100)
    owner_id:         UUID | None = None
    # I cap individual tag length to prevent oversized values in the ARRAY column.
    tags:             list[str] | None = None


# --- DeviceResponse ---
# Shape of the data the API sends back to the client after reading from the DB.
class DeviceResponse(BaseModel):
    # UUID avoids leaking record counts and stays unique across distributed nodes.
    id:         UUID
    name:       str
    # NULL in the DB means the device has not reported a value yet.
    location:   str | None
    type:       str | None
    status:     str
    # last_seen is set by the backend when a device posts telemetry; None = never seen.
    last_seen:        datetime | None
    firmware_version: str | None = None
    created_at:       datetime
    owner_id:         UUID | None = None
    tags:             list[str] = []

    # from_attributes=True lets Pydantic read fields from ORM objects (SQLAlchemy rows),
    # not just plain dicts - required when returning DB model instances directly.
    model_config = {"from_attributes": True}


# --- DeviceWithKey ---
# Extends DeviceResponse to include the raw API key - returned once at creation only.
class DeviceWithKey(DeviceResponse):
    # Inheriting from DeviceResponse reuses all validated fields without repeating them.
    api_key: str
