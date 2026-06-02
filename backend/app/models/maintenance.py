import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class MaintenanceWindow(Base):
    __tablename__ = "maintenance_windows"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # NULL device_id means the window applies to the entire fleet, not one device.
    device_id       = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=True)
    label           = Column(String(200), nullable=False)
    start_at        = Column(DateTime(timezone=True), nullable=False)
    end_at          = Column(DateTime(timezone=True), nullable=False)
    suppress_alerts = Column(Boolean, default=True, nullable=False)
    created_by      = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
