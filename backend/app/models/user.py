import uuid
from sqlalchemy import BigInteger, Boolean, Column, Index, JSON, String, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base
from app.services.two_step_secrets import EncryptedSecret


class User(Base):
    __tablename__ = "users"

    # UUID4 is randomly generated, ensuring uniqueness across distributed systems
    # and preventing enumeration attacks (sequential IDs let attackers guess valid IDs)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100))
    # unique=True enforces that no two accounts can share the same email at the DB level
    email = Column(String(150), unique=True, nullable=False)
    # the plain-text password is never stored - only its bcrypt hash,
    # so a DB leak doesn't expose real passwords. Nullable to support
    # OAuth users who authenticate via Google/GitHub and have no password.
    password_hash = Column(String(255), nullable=True)
    # default is "viewer" for security: a newly created or compromised account gets
    # the least privilege; only admins can elevate a role to technician or admin
    role = Column(String(20), default="viewer")  # admin / technician / viewer
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True))
    # track consecutive failed attempts so the account can be locked after 5 failures
    # and prevent brute-force attacks without rate-limiting every single request.
    failed_login_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)

    # OAuth - set when a user signs in via Google or GitHub instead of a password
    oauth_provider = Column(String(50), nullable=True)   # "google" | "github" | "microsoft" | None
    oauth_id       = Column(String(200), nullable=True)  # provider's user sub/id

    # profile - phone number for SMS alert delivery
    phone_number = Column(String(30), nullable=True)

    # TOTP 2FA - the secret is stored encrypted (`enc:v1:...`) under a key derived from SECRET_KEY for this purpose, so a
    # database read or a backup alone does not give a second factor. A row from before migration 032 is plain text until
    # the next start encrypts it. The flag tracks enrolment state
    totp_secret  = Column(EncryptedSecret(), nullable=True)
    totp_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    # the last accepted TOTP time step, so a one-time code is never accepted twice.
    totp_last_step = Column(BigInteger, nullable=True)

    # every token carries this number. Raising it ends all of the user's
    # sessions, for example after a password or two-factor change.
    token_version = Column(Integer, nullable=False, default=0, server_default="0")

    # retired: this column was meant for per-user capability overrides but nothing ever read it;
    # no route sets it and no reply returns it. It stays so existing rows and migration 009 still fit.
    permissions = Column(JSON, nullable=True)

    # a deactivated account cannot sign in, refresh, reset its password or accept an invitation. An admin sets it and
    # doing so ends every session
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    # a service account is owned by an integration and not by a person: it has a role and API tokens and no way to sign in. It
    # has no password, provider link, two-step, session, invitation or reset link and every route that would give it one
    # refuses it (see docs/security.md). An admin makes it with fresh proof and makes its tokens the same way
    is_service = Column(Boolean, nullable=False, default=False, server_default="false")
    deactivated_at = Column(DateTime(timezone=True), nullable=True)

    # when the current sign-in address became the account's. NULL means it was never unconfirmed: the address an
    # invitation went to or one a provider verified. A self-registered or changed address has the time it was set
    # and is trusted with a notice only after an hour (see the email change route)
    email_since = Column(DateTime(timezone=True), nullable=True)

    # alert texts go only to a number confirmed by a code sent to that number. A changed number starts unconfirmed. The code
    # is kept as a keyed hash with its number, its expiry and how many wrong tries it has had
    phone_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    phone_code_hash = Column(String(64), nullable=True)
    phone_code_number = Column(String(30), nullable=True)
    phone_code_expires_at = Column(DateTime(timezone=True), nullable=True)
    phone_code_attempts = Column(Integer, nullable=False, default=0, server_default="0")

    @property
    def phone_confirmed(self) -> bool:
        return bool(self.phone_number) and self.phone_confirmed_at is not None

    @property
    def has_password(self) -> bool:
        # accounts that sign in through a provider have none, which changes how they confirm deleting the account
        return bool(self.password_hash)

    # one account for one mailbox: addresses are stored in lower case and this stops two that differ only in case
    __table_args__ = (Index("idx_users_email_lower", func.lower(email), unique=True),)
