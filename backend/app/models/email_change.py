import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class EmailChange(Base):
    """One change of an account's sign-in address, kept so changes can be limited per hour and per day."""

    __tablename__ = "email_changes"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("idx_email_changes_user_time", "user_id", "changed_at"),)
