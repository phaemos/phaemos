import uuid
from sqlalchemy import Column, Float, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class Telemetry(Base):
    __tablename__ = "telemetry"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id     = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    temperature   = Column(Float)
    humidity      = Column(Float)
    vibration_x   = Column(Float)
    vibration_y   = Column(Float)
    vibration_z   = Column(Float)
    light_level   = Column(Float)
    anomaly_score = Column(Float)
    is_anomaly    = Column(Boolean, default=False)
    recorded_at   = Column(DateTime(timezone=True), server_default=func.now())
