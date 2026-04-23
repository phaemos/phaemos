from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class AlertRuleCreate(BaseModel):
    device_id: UUID
    metric:    str
    condition: str   # gt, lt, eq
    threshold: float
    severity:  str   # info, warning, critical


class AlertRuleResponse(AlertRuleCreate):
    id:         UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertResponse(BaseModel):
    id:           UUID
    device_id:    UUID
    rule_id:      UUID | None
    message:      str | None
    severity:     str | None
    resolved:     bool
    triggered_at: datetime
    resolved_at:  datetime | None

    model_config = {"from_attributes": True}
