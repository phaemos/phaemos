from uuid import UUID
# EmailStr is a Pydantic type that validates the string is a properly-formatted email address.
from pydantic import BaseModel, EmailStr


# --- UserRegister ---
# Payload for POST /auth/register; password is stored hashed — never plain-text in the DB.
class UserRegister(BaseModel):
    name:     str
    # Using EmailStr instead of plain `str` means Pydantic rejects "notanemail" automatically.
    email:    EmailStr
    password: str


# --- UserLogin ---
# Kept separate from UserRegister so login does not accidentally accept a `name` field.
class UserLogin(BaseModel):
    email:    EmailStr
    password: str


# --- UserResponse ---
# What the API sends back after login or profile fetch — notably, password is NOT included.
class UserResponse(BaseModel):
    id:    UUID
    # name can be NULL if the user registered without providing one (e.g. via OAuth).
    name:  str | None
    # email stays as plain `str` here because we only need to output it, not re-validate format.
    email: str
    # Role drives authorization checks (e.g. "admin" vs "viewer"); stored as a string for flexibility.
    role:  str

    # Allows Pydantic to convert a SQLAlchemy User ORM object directly into this schema.
    model_config = {"from_attributes": True}


# --- TokenResponse ---
# Returned after a successful login; the client stores access_token and sends it in the Authorization header.
class TokenResponse(BaseModel):
    access_token: str
    # Hardcoded default of "bearer" matches the OAuth 2.0 spec — clients expect exactly this string.
    token_type:   str = "bearer"
