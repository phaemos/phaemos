import re
from datetime import datetime
from typing import Any
from uuid import UUID
from pydantic import BaseModel, EmailStr, field_validator


# --- UserRegister ---
# Payload for POST /auth/register; password is stored hashed — never plain-text in the DB.
class UserRegister(BaseModel):
    name:     str
    email:    EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        # I enforce a minimum bar here so weak passwords never reach the DB.
        # Rules: 8+ chars, at least one uppercase letter, at least one digit.
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


# --- UserLogin ---
# Kept separate from UserRegister so login does not accidentally accept a `name` field.
class UserLogin(BaseModel):
    email:    EmailStr
    password: str


# --- UserUpdate ---
# Fields the user may update on their own profile; all optional for partial updates.
class UserUpdate(BaseModel):
    name:         str | None = None
    email:        EmailStr | None = None
    phone_number: str | None = None


# --- ChangePassword ---
class ChangePassword(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


# --- UserResponse ---
# What the API sends back after login or profile fetch — notably, password is NOT included.
class UserResponse(BaseModel):
    id:    UUID
    # name can be NULL if the user registered without providing one (e.g. via OAuth).
    name:  str | None
    # email stays as plain `str` here because we only need to output it, not re-validate format.
    email: str
    # Role drives authorization checks (e.g. "admin" vs "viewer"); stored as a string for flexibility.
    role:           str
    created_at:     datetime | None = None
    phone_number:   str | None = None
    oauth_provider: str | None = None
    permissions:    dict[str, Any] | None = None
    totp_enabled:   bool = False

    # Allows Pydantic to convert a SQLAlchemy User ORM object directly into this schema.
    model_config = {"from_attributes": True}


# --- TokenResponse ---
# Returned after a successful login; the client stores access_token and sends it in the Authorization header.
class TokenResponse(BaseModel):
    access_token: str
    # Hardcoded default of "bearer" matches the OAuth 2.0 spec — clients expect exactly this string.
    token_type:   str = "bearer"


# --- InviteCreate ---
# Body for POST /auth/invite (admin creates an invite for a new user).
class InviteCreate(BaseModel):
    email: EmailStr
    role:  str = "viewer"  # default to least privilege


# --- AcceptInvite ---
# Body for POST /auth/accept-invite (invitee sets their password to activate the account).
class AcceptInvite(BaseModel):
    token:    str
    name:     str
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v
