import uuid
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id  = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    metric     = Column(String(50))   # temperature, vibration_x, etc.
    condition  = Column(String(10))   # gt, lt, eq
    threshold  = Column(Float, nullable=False)
    severity   = Column(String(20))   # info, warning, critical
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id    = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    rule_id      = Column(UUID(as_uuid=True), ForeignKey("alert_rules.id"), nullable=True)
    message      = Column(String)
    severity     = Column(String(20))
    resolved     = Column(String, default=False)
    triggered_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at  = Column(DateTime(timezone=True), nullable=True)
