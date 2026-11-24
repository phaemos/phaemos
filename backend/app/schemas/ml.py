"""Response models of the anomaly model routes (routes/ml.py)."""

from uuid import UUID

from pydantic import BaseModel


class RetrainStarted(BaseModel):
    detail: str


class ModelStatusSummary(BaseModel):
    # none (no model file), ok, legacy (a file from before this version) or error (it will not load)
    state: str
    trained_at: str | None = None
    # one line per model in service: key, scope, legacy, light, false_alerts_per_week (on the newest held-back readings)
    # and its 95 per cent upper bound, features, trained_at and the detector's boundary and run length (censored when no
    # false crossing was seen: then only its lower bound is known)
    models: list[dict] = []
    # one line per machine the last training saw: device_id, state, scope, over_cap, light, monitored, hours_collected,
    # hours_needed, ambient, interval_s, recorded_interval_s and the reason (learning, refused, withdrawn or light)
    machines: list[dict] = []
    # how many machines get a full model (with the forest). A machine beyond it gets a light model of its own
    max_machine_models: int
    # machines the last training saw that a model scores and those no model scores (each listed in machines with the reason)
    monitored_machines: int = 0
    unmonitored_machines: int = 0
    # the outcome of the latest retrain, accepted or refused, with the reason in words. Null before the first
    last_retrain: dict | None = None
    # when the nightly retrain runs and next will
    schedule: dict


class ScoreReply(BaseModel):
    anomaly_score: float | None = None
    is_anomaly: bool


class MoveAccepted(BaseModel):
    detail: str


class AlertVerdict(BaseModel):
    # true: a person confirmed a real fault. false: a person said it was not one
    fault: bool


class AlertVerdictReply(BaseModel):
    id: UUID
    fault_confirmed: bool | None = None


class AmbientSource(BaseModel):
    # the node whose air temperature is this machine's ambient reference or null for none
    source_id: UUID | None = None


class AmbientSourceReply(BaseModel):
    device_id: UUID
    source_id: UUID | None = None
    detail: str
