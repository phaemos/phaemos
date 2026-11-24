from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class ApiToken(Base):
    """An access token for a script or the command line tool. It belongs to one account.

    The token is `pht_<id>_<secret>`. The id is public and finds the row. Only a keyed hash of the secret is kept, so the
    secret can never be read back and is shown once, when the token is made. `token_version` is the account's version at
    creation, so anything that ends the account's sessions (a password change, an admin clearing sessions) ends its tokens.
    """

    __tablename__ = "api_tokens"

    id            = Column(String(12), primary_key=True)
    user_id       = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name          = Column(String(60), nullable=False)
    scope         = Column(String(10), nullable=False)
    secret_hash   = Column(String(64), nullable=False)
    token_version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at    = Column(DateTime(timezone=True), nullable=False)
    # moved on at most once a minute, so a busy script does not write on every call
    last_used_at  = Column(DateTime(timezone=True), nullable=True)
    revoked_at    = Column(DateTime(timezone=True), nullable=True)
    # who made it. For a token on a service account this is the admin who did. NULL when that person has been removed
    created_by    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (Index("idx_api_tokens_user", "user_id"),)
