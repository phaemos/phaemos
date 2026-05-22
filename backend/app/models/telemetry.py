import uuid
# Float stores decimal sensor readings; Boolean stores true/false flags (e.g. is_anomaly)
from sqlalchemy import Column, Float, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class Telemetry(Base):
    __tablename__ = "telemetry"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # ForeignKey("devices.id") creates a database-level link to the devices table
    # ondelete="CASCADE" means if a device is deleted, all its telemetry rows are also deleted automatically
    device_id     = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    # Sensor readings are nullable — a device may not report every metric on every reading
    temperature   = Column(Float)
    humidity      = Column(Float)
    # Vibration is split into three axes (x, y, z) to capture the full 3-D motion vector
    vibration_x   = Column(Float)
    vibration_y   = Column(Float)
    vibration_z   = Column(Float)
    light_level   = Column(Float)
    # anomaly_score is a continuous value (e.g. 0.0–1.0) from an ML model indicating how unusual this reading is
    anomaly_score = Column(Float)
    # is_anomaly is a derived boolean flag: True when anomaly_score crosses the configured threshold
    is_anomaly    = Column(Boolean, default=False)
    # server_default=func.now() stamps the row with the DB server's current time at insert
    recorded_at   = Column(DateTime(timezone=True), server_default=func.now())
