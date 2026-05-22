import uuid
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


# AlertRule defines the user-configured conditions that should trigger an alert
# (e.g. "fire an alert when temperature > 80 for device X")
class AlertRule(Base):
    __tablename__ = "alert_rules"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # CASCADE delete keeps the DB clean: removing a device removes all its rules automatically
    device_id  = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    metric     = Column(String(50))   # temperature, vibration_x, etc.
    condition  = Column(String(10))   # gt, lt, eq
    # nullable=False because a rule without a threshold is meaningless — it can never be evaluated
    threshold  = Column(Float, nullable=False)
    severity   = Column(String(20))   # info, warning, critical
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Alert is a fired event — one row is created each time a rule's condition is met
class Alert(Base):
    __tablename__ = "alerts"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id    = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    # nullable=True because some alerts may be system-generated without a matching AlertRule
    rule_id      = Column(UUID(as_uuid=True), ForeignKey("alert_rules.id"), nullable=True)
    # No length limit on String here — alert messages can be arbitrarily long
    message      = Column(String)
    severity     = Column(String(20))
    # Note: this column is typed String but defaults to False (a boolean) — the stored value
    # will be the string "False"; a Boolean column would be cleaner, but this is the current design
    resolved     = Column(String, default=False)
    # server_default timestamps when the alert was first raised, using the DB clock
    triggered_at = Column(DateTime(timezone=True), server_default=func.now())
    # nullable=True because the alert hasn't been resolved yet when the row is first inserted
    resolved_at  = Column(DateTime(timezone=True), nullable=True)
