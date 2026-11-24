import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class UserSession(Base):
    """One signed-in browser. The refresh token names it, so signing out can end just this one.

    The row's id is the `sid` claim in the refresh and access tokens. `current_jti` is the id of
    the refresh token that is live now: each use of the token swaps it for a new one, so a copy of
    an older token no longer matches and is treated as stolen.
    """

    __tablename__ = "user_sessions"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    current_jti  = Column(String(64), nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), server_default=func.now())
    # when the live refresh token stops working. The clean-up job deletes rows past this
    expires_at   = Column(DateTime(timezone=True), nullable=False)
    revoked_at   = Column(DateTime(timezone=True), nullable=True)
    # a coarse description of the browser ("Chrome on macOS"), made from the user agent when the
    # session starts, so its owner can tell their sessions apart. No address and no raw user agent is kept
    label        = Column(String(80), nullable=True)
    # the refresh token this one replaced and when. The older token is accepted again for a few seconds, so two
    # tabs refreshing together or a retry after a lost reply, are not mistaken for a stolen copy
    previous_jti = Column(String(64), nullable=True)
    rotated_at   = Column(DateTime(timezone=True), nullable=True)
    # when this session came back from the sign-in provider. A provider-only account proves it is
    # the owner with a return from the last 5 minutes and only the session that made the return counts
    provider_signin_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_user_sessions_user", "user_id"),
        Index("idx_user_sessions_expires", "expires_at"),
    )
