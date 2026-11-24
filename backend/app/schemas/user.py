import re
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, field_validator


# passwords that are on every list of the most used ones. A password is also refused when it is one of these once the
# case is ignored. This is a small floor and not a replacement for a long passphrase
_COMMON_PASSWORDS = frozenset({
    "password", "password1", "password12", "password123", "passw0rd1", "passw0rd", "12345678", "123456789", "1234567890",
    "qwertyui", "qwertyuiop", "qwerty123", "letmein1", "letmein123", "welcome1", "welcome123", "admin123", "admin1234",
    "administrator", "iloveyou1", "changeme", "changeme1", "abc12345", "abcd1234", "monkey123", "dragon123", "football1",
    "baseball1", "sunshine1", "princess1", "trustno1", "111111111", "00000000", "11111111", "phaemos1", "phaemos123",
})


def check_password(v: str) -> str:
    """The password rules, in one place. Used by registration, accepting an invitation, changing and resetting."""
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    # bcrypt only hashes the first 72 bytes, so anything longer is
    # rejected here rather than silently truncated.
    if len(v.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    if "\x00" in v:
        raise ValueError("Password must not contain NUL characters")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    if v.lower() in _COMMON_PASSWORDS:
        raise ValueError("That password is too common. Choose another")
    return v


def _lower(v):
    return v.lower() if isinstance(v, str) else v


# --- UserRegister ---
# payload for POST /auth/register; password is stored hashed - never plain-text in the DB.
class UserRegister(BaseModel):
    # the column holds 100 characters, so a longer name is refused here and not with a database error
    name:     str = Field(max_length=100)
    email:    EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return _lower(v)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return check_password(v)


# --- UserLogin ---
# kept separate from UserRegister so login does not accidentally accept a `name` field.
class UserLogin(BaseModel):
    email:    EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return _lower(v)

    @field_validator("password")
    @classmethod
    def no_nul(cls, v: str) -> str:
        # a NUL byte made bcrypt raise, which answered 500 for a known address and 401 for an unknown one
        if "\x00" in v:
            raise ValueError("Password must not contain NUL characters")
        return v


# --- UserUpdate ---
# fields the user may update on their own profile; all optional for partial updates.
class UserUpdate(BaseModel):
    name:         str | None = Field(default=None, max_length=100)
    email:        EmailStr | None = Field(default=None, max_length=150)
    phone_number: str | None = Field(default=None, max_length=30)
    # proof of ownership, needed only when the email changes. They are never stored
    current_password: str | None = None
    code:             str | None = None

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str | None) -> str | None:
        return _lower(v)

    @field_validator("phone_number")
    @classmethod
    def phone_number_format(cls, v: str | None) -> str | None:
        # critical alert texts go to this number, so a value Brevo would refuse is
        # rejected here instead of failing silently when an alert fires;
        # an empty value clears the number. Spaces and hyphens are dropped.
        if v is None:
            return v
        cleaned = re.sub(r"[\s-]", "", v)
        if cleaned and not re.fullmatch(r"\+[0-9]{8,15}", cleaned):
            raise ValueError(
                "Phone number must be empty or in international format: "
                "a plus sign then 8 to 15 digits, for example +447700900000"
            )
        return cleaned


# --- ChangePassword ---
class ChangePassword(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return check_password(v)


# --- UserSummary ---
# one row of the admin user list. The phone number stays on the person's own profile read.
class UserSummary(BaseModel):
    id:             UUID
    name:           str | None
    email:          str
    role:           str
    created_at:     datetime | None = None
    oauth_provider: str | None = None
    totp_enabled:   bool = False
    # what an admin needs to manage accounts. The state (an admin can deactivate an account), when the person last signed in
    # and how many sessions are live now
    is_active:      bool = True
    last_login:     datetime | None = None
    session_count:  int = 0
    # an account owned by an integration. It cannot sign in and owns API tokens
    is_service:     bool = False

    model_config = {"from_attributes": True}


# --- OwnerProof ---
# proof that the caller is the account's owner, for an action a stolen token must not be enough for
# (deleting the account, changing the email, switching two-step on or off). Send the one that applies:
# password for an account that has one, code (a fresh two-step code) for a provider account with
# two-step on. A provider account with neither proves itself by returning from its provider
# within the last 5 minutes, which needs no field.
class OwnerProof(BaseModel):
    password: str | None = None
    code:     str | None = None


# --- DeleteAccount ---
class DeleteAccount(OwnerProof):
    # accepted and ignored. A provider account now proves itself with a recent provider sign-in
    confirm:  str | None = None


# --- UserResponse ---
# what the API sends back after login or profile fetch - notably, password is NOT included.
class UserResponse(BaseModel):
    id:    UUID
    # name can be NULL if the user registered without providing one (e.g. via OAuth).
    name:  str | None
    # email stays as plain `str` here because it is only output and never re-validated, not re-validate format.
    email: str
    # role drives authorization checks (e.g. "admin" vs "viewer"); stored as a string for flexibility.
    role:           str
    created_at:     datetime | None = None
    phone_number:   str | None = None
    oauth_provider: str | None = None
    totp_enabled:   bool = False
    # false for an account that signs in through a provider. The profile page uses it to
    # choose how to confirm deleting the account.
    has_password:   bool = False
    # whether the phone number is confirmed by a code. Alert texts go only to a confirmed number
    phone_confirmed: bool = False
    # true when the person returned from their provider in the last 5 minutes, which is how a
    # provider-only account proves it is the owner. False for everyone else
    provider_signin_recent: bool = False

    # allows Pydantic to convert a SQLAlchemy User ORM object directly into this schema.
    model_config = {"from_attributes": True}


# --- TokenResponse ---
# returned after a successful login; the client stores access_token and sends it in the Authorization header.
class TokenResponse(BaseModel):
    access_token: str
    # hardcoded default of "bearer" matches the OAuth 2.0 spec - clients expect exactly this string.
    token_type:   str = "bearer"


# --- LoginResponse ---
# a finished sign-in returns an access token. An account with two-factor
# authentication gets mfa_required and a short-lived mfa_token instead, which
# only POST /auth/2fa/verify accepts.
class LoginResponse(BaseModel):
    access_token: str | None = None
    token_type:   str = "bearer"
    mfa_required: bool = False
    mfa_token:    str | None = None


# --- TotpVerify ---
# body for POST /auth/2fa/verify. mfa_token may be left out after an OAuth
# sign-in, which sets it as a cookie instead.
class TotpVerify(BaseModel):
    code:      str
    mfa_token: str | None = None


# --- InviteCreate ---
# body for POST /auth/invite (admin creates an invite for a new user).
class InviteCreate(BaseModel):
    email: EmailStr
    # proof for inviting an admin (see OwnerProof). Ignored for the other roles
    password: str | None = None
    code:     str | None = None

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.lower()

    # only the three real roles, so an invite can never mint an unknown one.
    role:  Literal["admin", "technician", "viewer"] = "viewer"


# --- AcceptInvite ---
# body for POST /auth/accept-invite (invitee sets their password to activate the account).
class AcceptInvite(BaseModel):
    token:    str
    name:     str = Field(max_length=100)
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return check_password(v)


class InvitationSummary(BaseModel):
    id:              UUID
    email:           str
    role:            str
    invited_by_name: str | None = None
    created_at:      datetime | None = None
    expires_at:      datetime


class ServiceAccountCreate(BaseModel):
    """The fresh proof (`password`, `code`) rides in the same body and is read by fresh_proof."""
    name: str = Field(min_length=1, max_length=60)
    role: Literal["admin", "technician", "viewer"] = "viewer"

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v or any(ord(ch) < 32 or ord(ch) == 127 for ch in v):
            raise ValueError("The name must be 1 to 60 characters with no control characters")
        return v
