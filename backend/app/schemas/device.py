from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class DeviceCreate(BaseModel):
    name:     str
    location: str | None = None
    type:     str | None = None   # esp32, arduino, stm32


class DeviceUpdate(BaseModel):
    name:     str | None = None
    location: str | None = None
    status:   str | None = None


class DeviceResponse(BaseModel):
    id:         UUID
    name:       str
    location:   str | None
    type:       str | None
    status:     str
    last_seen:  datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DeviceWithKey(DeviceResponse):
    api_key: str
