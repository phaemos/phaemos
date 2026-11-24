from sqlalchemy import Column, DateTime, String, func

from app.db import Base


class UsedInvite(Base):
    """Retired. A used invitation is now a row in `invitations` with `used_at` set. This table is kept because the
    retention job still cleans it and a database may hold rows from before migration 032."""

    __tablename__ = "used_invites"

    token_hash = Column(String(64), primary_key=True)
    used_at    = Column(DateTime(timezone=True), server_default=func.now())
