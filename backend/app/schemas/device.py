from typing import ClassVar
from datetime import datetime, timezone
from uuid import UUID
from pydantic import BaseModel, Field, computed_field, field_validator

from app.services.sensor_map import SENSOR_FIELDS, canonical_key


# --- DeviceCreate ---
# used when a client (e.g. admin UI or POST /devices) registers a new device.
class DeviceCreate(BaseModel):
    # cap string lengths to prevent storage exhaustion from oversized payloads.
    # the columns hold 100 characters, so a longer value is refused here and not with a database error
    name:     str = Field(max_length=100)
    location: str | None = Field(default=None, max_length=100)
    type:     str | None = Field(default=None, max_length=50)
    # allow owner_id at creation time so an admin can assign a device to a
    # technician in a single request rather than needing a follow-up PATCH.
    owner_id: UUID | None = None


# --- DeviceUpdate ---
# all fields are optional so clients can PATCH only the fields they want to change.
class DeviceUpdate(BaseModel):
    name:             str | None = Field(default=None, max_length=100)
    location:         str | None = Field(default=None, max_length=100)
    firmware_version: str | None = Field(default=None, max_length=50)
    owner_id:         UUID | None = None
    # cap individual tag length to prevent oversized values in the ARRAY column.
    tags:             list[str] | None = None
    # how often the node posts, in seconds. Admin only. The liveness thresholds follow it: late after 4 intervals and
    # offline after 12 and the anomaly run window scales with it
    expected_interval_s: int | None = Field(default=None, ge=1, le=86_400)
    # sensor keys that are not expected on this machine. Admin only. A fault reported for one raises no alert
    not_fitted:       list[str] | None = None

    @field_validator("not_fitted")
    @classmethod
    def _known_sensor_keys(cls, value):
        if value is None:
            return None
        keys = []
        for raw in value:
            key = canonical_key(str(raw).strip().lower())
            if key not in SENSOR_FIELDS:
                raise ValueError(f"unknown sensor key: {str(raw)[:40]}")
            if key not in keys:
                keys.append(key)
        if len(keys) > len(SENSOR_FIELDS):
            raise ValueError("too many sensor keys")
        return keys


# --- CannotEvaluateRule ---
# an alert rule whose field is null on every post while its sensor is faulted, so it cannot fire
class CannotEvaluateRule(BaseModel):
    rule_id:    UUID
    metric:     str
    sensor_key: str
    # the fault state of that sensor or not_fitted
    state:      str
    reason:     str


# --- ModelStatus ---
# what the anomaly model is doing for this machine. It never touches the database, so it costs nothing for a list
class ModelStatus(BaseModel):
    # ready (a model scores this machine), learning (not enough clean readings yet, so it is not scored and cannot raise an
    # anomaly alert), legacy (a model file from an earlier version, which scores nothing until a retrain), none (no model
    # scores it: reason says why) or error (the file will not load)
    state:                 str = "none"
    # machine (its own model), node_type, general or null
    scope:                 str | None = None
    # hours of clean readings collected so far and the hours a model needs. Both null when not applicable
    hours_collected:       float | None = None
    hours_needed:          float | None = None
    # the false anomaly alerts per machine per week measured at the last training, null for a legacy model
    false_alerts_per_week: float | None = None
    trained_at:            str | None = None
    # when the last retrain refused this machine's own model and why (the message the retrain gave). Both null when it did not. They
    # are filled from ml_service.model_status when it reports them, so the dashboard need not search GET /ml/status for machine:<id>
    refused_at:            str | None = None
    refusal:               str | None = None
    # false when no model scores this machine (reason says why), the 95 per cent upper bound of false_alerts_per_week, how
    # its own model uses the room and whether that model is a light one (no forest, beyond the cap on full models)
    monitored:             bool = False
    reason:                str | None = None
    false_alerts_per_week_high_95: float | None = None
    ambient:               str | None = None
    light:                 bool = False


# --- DeviceHealthResponse ---
# the latest vitals and fault map a node reported. Null on a device that has never sent health fields.
class DeviceHealthResponse(BaseModel):
    boot_count:       int | None = None
    uptime_s:         int | None = None
    reset_reason:     str | None = None
    rssi:             int | None = None
    heap_free:        int | None = None
    firmware_version: str | None = None
    last_seq:         int | None = None
    # when the node last reported them
    reported_at:      datetime | None = None
    # sensor key -> state for each faulted sensor in the latest post. Empty when all was well
    faults:           dict[str, str] = {}
    # posts lost in total (from gaps in the sequence number) and when the latest gap was seen
    lost_posts:       int = 0
    last_gap_at:      datetime | None = None
    # the latest state and counters of each serial link the hub watches, as it sent them. Empty when it sends none
    links:            dict[str, dict[str, int]] = {}
    # the hub's latest bench counters: at most 16 short names with whole-number values. Empty when it sends none
    diag:             dict[str, int] = {}
    # true while the firmware says its image does not match the board (a monitoring alert is open)
    board_mismatch:   bool = False
    # the threshold rules that cannot be evaluated now because their sensor is faulted or not fitted. The cause is the
    # sensor fault alert, so no alert is raised for the rule itself
    rules_cannot_evaluate: list[CannotEvaluateRule] = []
    # health fields the node sent that were out of bounds or malformed. They were dropped and the reading kept
    dropped_fields:   int = 0
    # true while the node has restarted three times in the last ten minutes
    reset_loop:       bool = False
    # the faults the server found by itself in the latest post: a value outside what the part can measure (out_of_range) or one
    # that stopped moving (stuck), as {sensor key: state}. They are alerted like a fault the node reports. Empty when there are none
    server_faults:    dict[str, str] = {}

    model_config = {"from_attributes": True}


# --- DeviceResponse ---
# shape of the data the API sends back to the client after reading from the DB.
class DeviceResponse(BaseModel):
    # UUID avoids leaking record counts and stays unique across distributed nodes.
    id:         UUID
    name:       str
    # NULL in the DB means the device has not reported a value yet.
    location:   str | None
    type:       str | None
    status:     str
    # last_seen is set by the backend when a device posts telemetry; None = never seen.
    last_seen:        datetime | None
    firmware_version: str | None = None
    created_at:       datetime
    owner_id:         UUID | None = None
    # the owner's name, because only admins can list users. Never an email or phone number.
    owner_name:       str | None = None
    tags:             list[str] = []
    # sensor keys an admin marked as not fitted on this machine
    not_fitted:       list[str] = []
    # the sensor keys the hub's firmware says it was built without, as it last reported them. Kept apart from the admin's
    # list. A fault on a key in either list is shown as not fitted and raises no alert. Filled by GET /devices and
    # GET /devices/{id}, empty elsewhere
    not_fitted_by_firmware: list[str] = []
    # how often the node posts and what the age of its last post makes it: online, late or offline;
    # a post sets online at once. The liveness sweep moves it on, so it can lag by up to its 15 second interval
    expected_interval_s: int = 5
    link_state:       str = "offline"
    # the latest vitals, filled by GET /devices and GET /devices/{id}. Null elsewhere and for a node that sends none
    health:           DeviceHealthResponse | None = None
    # the anomaly model's state for this machine. Filled by GET /devices and GET /devices/{id}
    model:            ModelStatus | None = None
    # replay protection (migration 031). True once the machine has sent the (boot, seq) pair: from then on every post must carry
    # a newer one. last_boot and last_seq are the last pair accepted. replay_refused counts the posts refused for an old pair
    # since the last accepted one and replay_refused_at is when the latest was refused
    replay_protected: bool = False
    last_boot:        int | None = None
    last_seq:         int | None = None
    replay_refused:   int = 0
    replay_refused_at: datetime | None = None
    # set when the counter rose by more than a restart or lost posts explain (see services/replay.py). It says what happened and
    # that the key may be known to someone else. Null otherwise
    counter_jump_at:  datetime | None = None
    counter_jump_note: str | None = None

    # a streak of refusals this long is shown with the hint to accept a new counter
    REPLAY_STREAK_HINT: ClassVar[int] = 3

    @computed_field
    @property
    def replay_warning(self) -> str | None:
        if not self.counter_jump_note:
            return None
        return (
            f"The counter rose too fast: {self.counter_jump_note}. A counter that was pushed up can mean the key is known to someone "
            "else. Rotate this machine's key"
        )

    @computed_field
    @property
    def replay_recovery(self) -> str | None:
        """The text for the accept-counter action. Null for a machine that is not protected."""
        if not self.replay_protected:
            return None
        return (
            "Accepting a new counter lets this machine post again after a wiped flash. If the counter was pushed up and not "
            "wiped, rotate the machine's key as well: someone else may hold it"
        )

    @computed_field
    @property
    def replay_status(self) -> str:
        """One plain sentence for the health panel: protected, not protected or locked out by an old counter."""
        if not self.replay_protected:
            return "no replay protection: this machine does not send boot and seq"
        if self.replay_refused >= self.REPLAY_STREAK_HINT:
            return (
                f"{self.replay_refused} posts in a row were refused for an old counter. If this machine's flash was wiped "
                "an admin can accept a new counter for it"
            )
        return "protected: every post must carry a newer boot and seq"

    @computed_field
    @property
    def seconds_since_last_post(self) -> int | None:
        # worked out when the response is built. None for a device that has never posted
        if self.last_seen is None:
            return None
        seen = self.last_seen if self.last_seen.tzinfo else self.last_seen.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - seen).total_seconds()))

    # from_attributes=True lets Pydantic read fields from ORM objects (SQLAlchemy rows),
    # not just plain dicts - required when returning DB model instances directly.
    model_config = {"from_attributes": True}


# --- DeviceWithKey ---
# extends DeviceResponse to include the raw API key - returned once at creation only.
class DeviceWithKey(DeviceResponse):
    # inheriting from DeviceResponse reuses all validated fields without repeating them.
    api_key: str
