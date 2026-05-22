import uuid
from sqlalchemy import Column, String, DateTime, func
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
    # The plain-text password is never stored — only its bcrypt hash,
    # so a DB leak doesn't expose real passwords
    password_hash = Column(String(255), nullable=False)
    # Default is "viewer" for security: a newly created or compromised account gets
    # the least privilege; only admins can elevate a role to technician or admin
    role = Column(String(20), default="viewer")  # admin / technician / viewer
    created_at = Column(DateTime(timezone=True), server_default=func.now())  # when the account was created
    last_login = Column(DateTime(timezone=True))  # updated each time the user authenticates
