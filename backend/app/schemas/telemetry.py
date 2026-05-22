from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


# --- TelemetryIngest ---
# The payload the ESP32 firmware POSTs to /api/v1/telemetry on every POLL_INTERVAL_MS tick.
class TelemetryIngest(BaseModel):
    # Sent as a plain string from firmware; the backend resolves it to a UUID before storing.
    device_id:   str
    # All sensor fields are optional: a device may only have a DHT22 (no MPU6050), so missing axes are fine.
    temperature: float | None = None
    humidity:    float | None = None
    # X/Y/Z axes from the MPU6050 accelerometer, in g-units (1 g ≈ 9.81 m/s²).
    vibration_x: float | None = None
    vibration_y: float | None = None
    vibration_z: float | None = None
    # Raw ADC reading from the LDR light sensor, converted to a float before sending.
    light_level: float | None = None


# --- TelemetryResponse ---
# What the API returns when a client queries stored telemetry records.
class TelemetryResponse(BaseModel):
    id:            UUID
    # device_id is a proper UUID here because the backend has already resolved it from the ingest string.
    device_id:     UUID
    temperature:   float | None
    humidity:      float | None
    vibration_x:   float | None
    vibration_y:   float | None
    vibration_z:   float | None
    light_level:   float | None
    # Computed by the anomaly-detection model; higher value = more unusual reading.
    anomaly_score: float | None
    # Boolean flag derived from anomaly_score; makes it easy to filter alerts without comparing floats.
    is_anomaly:    bool
    # Server-side timestamp set when the record is written — not trusting the device clock.
    recorded_at:   datetime

    # Required so Pydantic can serialise SQLAlchemy ORM row objects into this schema.
    model_config = {"from_attributes": True}
