import uuid
from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class Device(Base):
    __tablename__ = "devices"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name       = Column(String(100), nullable=False)
    location   = Column(String(100))
    type       = Column(String(50))          # esp32 / arduino / stm32
    api_key    = Column(String(255), unique=True, nullable=False)
    status     = Column(String(20), default="offline")  # online/offline/warning/fault
    last_seen  = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
