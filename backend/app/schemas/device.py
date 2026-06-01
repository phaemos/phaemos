from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


# --- DeviceCreate ---
# Used when a client (e.g. admin UI or POST /devices) sends data to register a new device.
class DeviceCreate(BaseModel):
    name:     str
    # `str | None = None` means the field is optional: the client can omit it entirely.
    location: str | None = None
    type:     str | None = None   # esp32, arduino, stm32


# --- DeviceUpdate ---
# All fields are optional so clients can PATCH only the fields they want to change.
class DeviceUpdate(BaseModel):
    name:             str | None = None
    location:         str | None = None
    status:           str | None = None
    firmware_version: str | None = None


# --- DeviceResponse ---
# Shape of the data the API sends BACK to the client after reading from the database.
class DeviceResponse(BaseModel):
    # UUID is used instead of an integer ID to avoid leaking record counts and to stay unique across distributed nodes.
    id:         UUID
    name:       str
    # These can be NULL in the DB, so Pydantic marks them `| None` to prevent a validation error.
    location:   str | None
    type:       str | None
    status:     str
    # `last_seen` is set by the backend when a device posts telemetry; NULL means never seen.
    last_seen:        datetime | None
    firmware_version: str | None = None
    created_at:       datetime

    # `from_attributes=True` tells Pydantic to read fields from ORM object attributes (e.g. SQLAlchemy row),
    # not just from plain dicts — required when returning database model instances directly.
    model_config = {"from_attributes": True}


# --- DeviceWithKey ---
# Extends DeviceResponse to include the raw API key — only returned once at creation time.
class DeviceWithKey(DeviceResponse):
    # Inheriting from DeviceResponse reuses all validated fields without repeating them.
    api_key: str
