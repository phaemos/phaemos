from datetime import datetime, timezone
from typing import ClassVar
from uuid import UUID
from pydantic import BaseModel, Field, computed_field, field_validator

from app.services import rule_metrics
from app.services.rule_metrics import CONDITIONS, RULE_METRICS, SEVERITIES


def _one_of(value, allowed, what):
    if value is not None and value not in allowed:
        raise ValueError(f"{what} must be one of: {', '.join(allowed)}")
    return value


# --- AlertRuleBase ---
# the fields of a rule. Both the request and the response carry them. Only the request checks them against the allowed lists, so
# a rule saved before the check existed can still be listed
class AlertRuleBase(BaseModel):
    # scoped to a single device so different machines can have different tolerances.
    device_id: UUID
    # name of the telemetry column to watch, e.g. "temperature" or "vibration_x".
    # the columns hold 50, 10 and 20 characters, so a longer value is refused here and not with a database error
    metric:    str = Field(max_length=50)
    condition: str = Field(max_length=10)   # gt, lt, eq
    # the numeric boundary; e.g. threshold=80.0 with condition="gt" fires when metric > 80.
    threshold: float
    severity:  str = Field(max_length=20)   # info, warning, critical
    # how long the condition must hold, without a break, before the alert is raised, in seconds. Null means the default for
    # the metric: 30 for a number and 0 for an on-or-off reading, which raises at once. The value must also be back
    # inside the limit for this long (at least 60 seconds) before the alert resolves
    for_seconds:  int | None = Field(default=None, ge=0, le=86_400)
    # how far back inside the limit a number must come before the alert can resolve. Null means 2 per cent of the threshold
    # and never less than one unit of its last decimal place. An equality rule does not use it
    clear_margin: float | None = Field(default=None, ge=0)


# --- AlertRuleCreate ---
# defines a threshold-based rule that the backend evaluates on every incoming telemetry reading.
class AlertRuleCreate(AlertRuleBase):
    # a rule on anything but a reading a post carries could never fire, so the three free-text fields are checked against
    # the lists the dashboard gets from GET /api/v1/alert-metrics
    @field_validator("metric")
    @classmethod
    def _known_metric(cls, value):
        return _one_of(value, RULE_METRICS, "metric")

    @field_validator("condition")
    @classmethod
    def _known_condition(cls, value):
        return _one_of(value, CONDITIONS, "condition")

    @field_validator("severity")
    @classmethod
    def _known_severity(cls, value):
        return _one_of(value, SEVERITIES, "severity")


# --- AlertRuleResponse ---
# inherits all fields from AlertRuleCreate, then adds the DB-generated id and timestamp.
# this pattern avoids duplicating field definitions between the "create" and "response" schemas.
class AlertRuleResponse(AlertRuleBase):
    id:         UUID
    created_at: datetime

    @computed_field
    @property
    def effective_for_seconds(self) -> int:
        """The hold the backend uses: the rule's own or the default for its metric."""
        return self.for_seconds if self.for_seconds is not None else rule_metrics.default_for_seconds(self.metric)

    @computed_field
    @property
    def effective_clear_margin(self) -> float:
        """The margin the backend uses: the rule's own or the default for its threshold."""
        return self.clear_margin if self.clear_margin is not None else rule_metrics.default_clear_margin(self.threshold)

    # needed to serialise SQLAlchemy model instances; see DeviceResponse for full explanation.
    model_config = {"from_attributes": True}


# --- AlertRuleUpdate ---
# all fields optional so callers can PATCH any subset without resending unchanged values.
class AlertRuleUpdate(BaseModel):
    metric:    str | None = Field(default=None, max_length=50)
    condition: str | None = Field(default=None, max_length=10)
    threshold: float | None = None
    severity:  str | None = Field(default=None, max_length=20)
    for_seconds:  int | None = Field(default=None, ge=0, le=86_400)
    clear_margin: float | None = Field(default=None, ge=0)

    @field_validator("metric")
    @classmethod
    def _known_metric(cls, value):
        return _one_of(value, RULE_METRICS, "metric")

    @field_validator("condition")
    @classmethod
    def _known_condition(cls, value):
        return _one_of(value, CONDITIONS, "condition")

    @field_validator("severity")
    @classmethod
    def _known_severity(cls, value):
        return _one_of(value, SEVERITIES, "severity")


# --- AlertResponse ---
# represents a fired alert event (not the rule itself) as stored in the alerts table.
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
    # machine: the machine is outside its normal range. monitoring: the way it is watched has failed
    # (a silent node or a restart loop)
    category:     str = "machine"
    # the sensor a monitoring alert is about. Null for a machine alert and for a node-wide one
    sensor_key:   str | None = None
    # what a system alert is about: offline, reset_loop, unscored, sensor or clipping. Null for a rule or model alert
    kind:         str | None = None
    # a rule alert is one row while its condition lasts: how many readings met it, the latest value, the most extreme
    # value (the highest for gt and eq, the lowest for lt) and when a reading last met it. For the model alert, peak_value
    # is the highest score and last_seen_at the latest evaluation. Null on system alerts
    occurrences:  int = 1
    last_value:   float | None = None
    peak_value:   float | None = None
    last_seen_at: datetime | None = None
    # when the condition first began to hold. triggered_at is when the alert was raised, which is one hold later. Null on
    # system alerts and on rule alerts raised before the field existed
    first_seen_at: datetime | None = None
    # the figures behind a model alert, null on every other alert. Range form: readings, over_boundary, median, window_s and, when one
    # sensor carried the score, sensor, value, range ([low, high], the machine's usual range) and direction (above or below). Drift
    # form (a sensor that drifted from where the model expects it): sensor, expected and minutes. A client reads `sensor` to tell
    # which form it has
    evidence:     dict | None = None

    # a reading met the condition within this many seconds, so the alert is still occurring. The dashboard shows "still
    # occurring" while this is true and "last seen at ..." when it is not (the readings stopped or the sensor is faulted)
    STILL_OCCURRING_SECONDS: ClassVar[int] = 120

    @computed_field
    @property
    def still_occurring(self) -> bool | None:
        if self.last_seen_at is None:
            return None
        if self.resolved:
            return False
        seen = self.last_seen_at if self.last_seen_at.tzinfo else self.last_seen_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - seen).total_seconds() <= self.STILL_OCCURRING_SECONDS

    model_config = {"from_attributes": True}
