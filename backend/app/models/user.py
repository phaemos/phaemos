import uuid
from sqlalchemy import Boolean, Column, String, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class User(Base):
    __tablename__ = "users"

    # UUID4 is randomly generated, ensuring uniqueness across distributed systems
    # and preventing enumeration attacks (sequential IDs let attackers guess valid IDs)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100))
    # unique=True enforces that no two accounts can share the same email at the DB level
    email = Column(String(150), unique=True, nullable=False)
    # The plain-text password is never stored - only its bcrypt hash,
    # so a DB leak doesn't expose real passwords. Nullable to support
    # OAuth users who authenticate via Google/GitHub and have no password.
    password_hash = Column(String(255), nullable=True)
    # Default is "viewer" for security: a newly created or compromised account gets
    # the least privilege; only admins can elevate a role to technician or admin
    role = Column(String(20), default="viewer")  # admin / technician / viewer
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True))
    # I track consecutive failed attempts so I can lock the account after 5 failures
    # and prevent brute-force attacks without rate-limiting every single request.
    failed_login_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)

    # OAuth - set when a user signs in via Google or GitHub instead of a password
    oauth_provider = Column(String(50), nullable=True)   # "google" | "github" | None
    oauth_id       = Column(String(200), nullable=True)  # provider's user sub/id

    # Profile - phone number for SMS alert delivery (Step 20g)
    phone_number = Column(String(30), nullable=True)

    # TOTP 2FA - secret stored encrypted-at-rest by the DB; flag tracks enrolment state
    totp_secret  = Column(String(64), nullable=True)
    totp_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
