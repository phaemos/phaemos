from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


# --- AlertRuleCreate ---
# Defines a threshold-based rule that the backend evaluates on every incoming telemetry reading.
class AlertRuleCreate(BaseModel):
    # Scoped to a single device so different machines can have different tolerances.
    device_id: UUID
    # Name of the telemetry column to watch, e.g. "temperature" or "vibration_x".
    metric:    str
    condition: str   # gt, lt, eq
    # The numeric boundary; e.g. threshold=80.0 with condition="gt" fires when metric > 80.
    threshold: float
    severity:  str   # info, warning, critical


# --- AlertRuleResponse ---
# Inherits all fields from AlertRuleCreate, then adds the DB-generated id and timestamp.
# This pattern avoids duplicating field definitions between the "create" and "response" schemas.
class AlertRuleResponse(AlertRuleCreate):
    id:         UUID
    created_at: datetime

    # Needed to serialise SQLAlchemy model instances; see DeviceResponse for full explanation.
    model_config = {"from_attributes": True}


# --- AlertResponse ---
# Represents a fired alert event (not the rule itself) as stored in the alerts table.
class AlertResponse(BaseModel):
    id:           UUID
    device_id:    UUID
    # rule_id can be NULL if an alert was raised by the anomaly-detection model, not a manual rule.
    rule_id:      UUID | None
    message:      str | None
    severity:     str | None
    # `resolved=False` means the condition is still active; the backend flips it when the reading normalises.
    resolved:     bool
    triggered_at: datetime
    # NULL until someone (or the system) marks the alert resolved, so the field must allow None.
    resolved_at:  datetime | None

    model_config = {"from_attributes": True}
