from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class TelemetryIngest(BaseModel):
    device_id:   str
    temperature: float | None = None
    humidity:    float | None = None
    vibration_x: float | None = None
    vibration_y: float | None = None
    vibration_z: float | None = None
    light_level: float | None = None


class TelemetryResponse(BaseModel):
    id:            UUID
    device_id:     UUID
    temperature:   float | None
    humidity:      float | None
    vibration_x:   float | None
    vibration_y:   float | None
    vibration_z:   float | None
    light_level:   float | None
    anomaly_score: float | None
    is_anomaly:    bool
    recorded_at:   datetime

    model_config = {"from_attributes": True}
