import uuid
from sqlalchemy import Boolean, Column, String, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class Webhook(Base):
    __tablename__ = "webhooks"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name       = Column(String(200), nullable=False)
    url        = Column(Text, nullable=False)
    enabled    = Column(Boolean, default=True, nullable=False)
    # I allow a custom message template with {device_name}, {metric}, {value},
    # {threshold}, {severity} placeholders; NULL means use the built-in format.
    template   = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
