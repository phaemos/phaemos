import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class Ticket(Base):
    __tablename__ = "tickets"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    alert_id    = Column(UUID(as_uuid=True), ForeignKey("alerts.id"), nullable=True)
    title       = Column(String(200))
    description = Column(Text)
    status      = Column(String(20), default="open")     # open / in_progress / closed
    priority    = Column(String(20))                      # low / medium / high / critical
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_by  = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # numbered by the database as each ticket is created. Declaring the identity here matters
    # because the app creates its tables before the migrations run. Migration 004 only adds
    # its SERIAL column when the column is missing, so a plain integer would never be numbered.
    ticket_number = Column(Integer, Identity(), unique=True)
