import uuid
from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4) # unique identifier for the user, generated automatically using uuid4 to ensure uniqueness across distributed systems and prevent enumeration attacks
    name          = Column(String(100))
    email         = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role          = Column(String(20), default="viewer")   # admin / technician / viewer (default is viewer for security reasons - only admins can assign roles to users other than viewer to prevent privilege escalation attacks - this way, if an attacker compromises a user account, they will only have viewer access by default)
    created_at    = Column(DateTime(timezone=True), server_default=func.now()) # when the user account was created
    last_login    = Column(DateTime(timezone=True)) # when the user last logged in
