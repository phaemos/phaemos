from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class TokenCreate(BaseModel):
    """The body of POST /tokens. The fresh proof (`password`, `code`) rides in the same body and is read by fresh_proof."""

    name: str = Field(min_length=1, max_length=60, description="What the token is for, shown in the list")
    scope: Literal["read", "operate", "admin"]
    expires_in_days: int = Field(default=90, ge=1, le=365)
    # an admin may make the token for a service account instead of for themselves
    account_id: UUID | None = Field(default=None, description="A service account to make the token for. Admins only")

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise ValueError("The name must be 1 to 60 characters with no control characters")
        return value


class TokenSummary(BaseModel):
    id: str
    name: str
    scope: Literal["read", "operate", "admin"]
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = None
    # the account the token acts as. For a token on a service account, created_by is the admin who made it
    account_id: UUID
    created_by: UUID | None = None


class TokenCreated(BaseModel):
    """The only answer that ever holds the token itself."""

    id: str
    name: str
    scope: Literal["read", "operate", "admin"]
    created_at: datetime
    expires_at: datetime
    account_id: UUID
    token: str = Field(description="Shown once. It cannot be read back")


class WhoamiToken(BaseModel):
    id: str
    name: str
    scope: Literal["read", "operate", "admin"]
    expires_at: datetime


class Whoami(BaseModel):
    id: UUID
    role: str
    signed_in_with: Literal["session", "token"]
    token: WhoamiToken | None = None
    is_service: bool = False
