import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class Ticket(Base):
    __tablename__ = "tickets"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # the delete rules match migrations 001 and 013: a ticket outlives the machine, alert or person it names
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    alert_id    = Column(UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True)
    title       = Column(String(200))
    description = Column(Text)
    status      = Column(String(20), default="open")     # open / in_progress / closed
    priority    = Column(String(20))                      # low / medium / high / critical
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by  = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # numbered by the database as each ticket is created. Declaring the identity here matters
    # because the app creates its tables before the migrations run. Migration 004 only adds
    # its SERIAL column when the column is missing, so a plain integer would never be numbered.
    ticket_number = Column(Integer, Identity(), unique=True)

    # read-only links so a reply can carry the two names without an extra query per ticket;
    # only the name is ever exposed, never an email or phone number.
    assignee = relationship("User", foreign_keys=[assigned_to], viewonly=True, lazy="joined")
    creator  = relationship("User", foreign_keys=[created_by], viewonly=True, lazy="joined")

    @property
    def assigned_to_name(self) -> str | None:
        return self.assignee.name if self.assignee else None

    @property
    def created_by_name(self) -> str | None:
        return self.creator.name if self.creator else None
