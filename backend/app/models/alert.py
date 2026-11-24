import uuid
from sqlalchemy import Boolean, Column, String, Float, DateTime, ForeignKey, Index, Integer, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db import Base


# AlertRule defines the user-configured conditions that should trigger an alert
# (e.g. "fire an alert when temperature > 80 for device X")
class AlertRule(Base):
    __tablename__ = "alert_rules"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # CASCADE delete keeps the DB clean: removing a device removes all its rules automatically
    device_id  = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    metric     = Column(String(50))   # temperature, vibration_x, etc.
    condition  = Column(String(10))   # gt, lt, eq
    # nullable=False because a rule without a threshold is meaningless - it can never be evaluated
    threshold  = Column(Float, nullable=False)
    severity   = Column(String(20))   # info, warning, critical
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # how long the condition must hold, without a break, before the alert is raised. NULL means the default for the
    # metric: 30 seconds for a number and 0 for an on-or-off reading (gas, water, clipping), which raises at once. It is
    # also how long the value must be back inside the limit before the alert resolves, but never less than 60 seconds
    for_seconds  = Column(Integer, nullable=True)
    # how far back inside the limit a number must come before the alert can resolve. NULL means 2 per cent of the
    # threshold and never less than one unit of its last decimal place. Not used by an equality rule
    clear_margin = Column(Float, nullable=True)


# one row for each (rule) while its condition is being watched: when the condition began to hold and when the value came
# back inside the limit. It is what lets a rule wait out for_seconds between posts without a row for every reading and
# it survives an API restart. It holds one row per rule and never grows (migration 029)
class RuleState(Base):
    __tablename__ = "rule_states"

    rule_id      = Column(UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="CASCADE"), primary_key=True)
    device_id    = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    # when the condition began to hold, without a break. NULL while it does not
    breach_since = Column(DateTime(timezone=True), nullable=True)
    # when the value came back inside the limit by the margin. NULL while it has not
    clear_since  = Column(DateTime(timezone=True), nullable=True)
    # the last time a reading carried the metric, so a gap in the readings is not read as a break-free hold
    last_eval_at = Column(DateTime(timezone=True), nullable=True)
    # what the readings of the hold added up to before the alert exists (migration 031): how many met the condition and the
    # most extreme value. They are copied onto the alert when it is raised, so its count and peak cover the qualifying period
    # and not only the readings after the raise. Cleared with breach_since
    hold_count   = Column(Integer, nullable=False, default=0, server_default=text("0"))
    hold_peak    = Column(Float, nullable=True)


# alert is a fired event. A rule alert is one row for the whole time its condition lasts and it is updated in place
class Alert(Base):
    __tablename__ = "alerts"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id    = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    # nullable=True because some alerts are system-generated and lack a matching AlertRule
    rule_id      = Column(UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True)
    # no length limit on String here - alert messages can be arbitrarily long
    message      = Column(String)
    severity     = Column(String(20))
    # never NULL (migration 028). A NULL used to count as open for the unique index and as not open for the lookups
    resolved     = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # server_default timestamps when the alert was first raised, using the DB clock
    triggered_at = Column(DateTime(timezone=True), server_default=func.now())
    # nullable=True because the alert hasn't been resolved yet when the row is first inserted
    resolved_at  = Column(DateTime(timezone=True), nullable=True)
    # machine: the machine itself is out of its normal range. monitoring: the way it is watched has failed
    # (a silent node, a restart loop, a faulted sensor)
    category     = Column(String(20), nullable=False, default="machine", server_default="machine")
    # the sensor a monitoring alert is about, when it is about one
    sensor_key   = Column(String(50), nullable=True)
    # what a monitoring or machine alert raised by the system is about: offline, reset_loop, unscored, sensor or
    # clipping. Null for a rule or model alert. The database refuses two open alerts of one kind on one device (and
    # one sensor), so a race between two posts cannot leave a duplicate that never resolves (migration 020)
    kind         = Column(String(30), nullable=True)
    # a rule alert while it lasts (migration 029): how many readings met the condition, the latest value, the most extreme
    # value (the highest for gt and eq, the lowest for lt) and when a reading last met it. last_seen_at is what tells "still
    # occurring" from "the readings stopped": it stops moving when the field is unavailable or the node is silent
    occurrences  = Column(Integer, nullable=False, default=1, server_default=text("1"))
    last_value   = Column(Float, nullable=True)
    peak_value   = Column(Float, nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    # when people were last told about this alert (raise, a rise to critical or the hourly reminder). Reset when a send
    # failed, so the next reading tries again
    notified_at  = Column(DateTime(timezone=True), nullable=True)
    # when the condition first began to hold, without a break. A rule alert is raised after its hold, so this is earlier than
    # triggered_at by about for_seconds. Null on alerts of other kinds and on rows from before migration 031
    first_seen_at = Column(DateTime(timezone=True), nullable=True)
    # the figures behind a model alert (migration 031): the counts and median of the window and, when the per-sensor baseline
    # carried the score, the sensor, its latest value and its usual range. Null on every other alert
    evidence = Column(JSONB, nullable=True)
    # a person's verdict on a machine alert (migration 040): true when they confirmed a real fault, false when they said it
    # was not one and null while nobody has said. Only a confirmed model alert keeps its readings out of the model's
    # training: an unconfirmed one must not or a machine whose normal really changed would never be retrained on it
    fault_confirmed = Column(Boolean, nullable=True)

    __table_args__ = (
        # one open system alert of a kind per device (and sensor). A rule alert has its own index below, because a machine
        # may have several rules and each has its own alert
        Index(
            "uq_alerts_open_system",
            "device_id", "kind", text("coalesce(sensor_key, '')"),
            unique=True,
            postgresql_where=text("kind IS NOT NULL AND kind <> 'rule' AND resolved IS NOT TRUE"),
        ),
        # one open alert per machine and rule
        Index(
            "uq_alerts_open_rule",
            "device_id", "rule_id",
            unique=True,
            postgresql_where=text("kind = 'rule' AND resolved IS NOT TRUE"),
        ),
    )
