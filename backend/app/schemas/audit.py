from datetime import datetime

from pydantic import BaseModel


class AuditEntry(BaseModel):
    id: str
    user_id: str | None = None
    action: str
    resource: str | None = None
    resource_id: str | None = None
    detail: str | None = None
    created_at: datetime | None = None
