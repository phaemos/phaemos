import uuid
# Column and the type classes (String, DateTime, etc.) describe the shape of each DB column
from sqlalchemy import Column, String, DateTime, func
# UUID is imported from the PostgreSQL dialect because it's a Postgres-specific column type
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


# Inheriting from Base registers this class with SQLAlchemy's ORM metadata
class Device(Base):
    # __tablename__ tells SQLAlchemy which database table this class maps to
    __tablename__ = "devices"

    # UUID(as_uuid=True) makes SQLAlchemy return Python uuid.UUID objects instead of raw strings
    # default=uuid.uuid4 means a new UUID is generated in Python before the row is inserted
    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # nullable=False enforces a NOT NULL constraint at the database level
    name       = Column(String(100), nullable=False)
    # No nullable=False means this column is optional — the device may not have a location yet
    location   = Column(String(100))
    type       = Column(String(50))          # esp32 / arduino / stm32
    # unique=True adds a UNIQUE constraint so no two devices can share the same API key
    api_key    = Column(String(255), unique=True, nullable=False)
    status     = Column(String(20), default="offline")  # online/offline/warning/fault
    # timezone=True stores the timestamp as UTC in the DB, preventing timezone confusion
    last_seen  = Column(DateTime(timezone=True))
    # server_default=func.now() lets the database set the timestamp, which is more reliable
    # than relying on application-side time (avoids clock-skew issues between app and DB servers)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
