"""
A reading that lacks a feature its model needs is not scored. It counts as neither normal nor anomalous, so a node
that drops a sensor cannot open an anomaly alert and training leaves such rows out.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.models.alert import Alert
from app.models.telemetry import Telemetry
from app.models.ticket import Ticket
from app.services import alert_service, ml_service


# the alert service is run with the old three-in-a-row decision, so these tests are about scored and unscored rows and not the maths
pytestmark = pytest.mark.usefixtures("old_three_in_a_row")


class _AlwaysAnomalous:
    # stands in for a trained model that finds every complete reading anomalous. It records what it was asked to
    # score, so a test can see that an incomplete reading never reached it
    phaemos_features = ["temperature", "humidity"]
    phaemos_schema = ml_service.SCHEMA_VERSION
    offset_ = 0.0
    phaemos_typical_decision = 0.1

    def __init__(self, features=None):
        self.matrices = []
        if features is not None:
            self.phaemos_features = features

    def score_samples(self, X):
        self.matrices.append(np.array(X))
        return np.full(len(X), -0.5)


@pytest.fixture
def model(monkeypatch):
    fake = _AlwaysAnomalous()
    monkeypatch.setattr(ml_service, "_model", {"default": fake})
    return fake


def _post(client, device, **fields):
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), **fields},
        headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == 201
    return res.json()


def _open(db, device):
    return db.query(Alert).filter(Alert.device_id == device.id, Alert.resolved.is_(False)).all()


# -- scoring ----------------------------------------------------------------------------------

def test_a_missing_feature_gives_a_null_score_and_no_flag(model):
    assert ml_service.score_reading({"temperature": 25.0}) == (None, False)
    # the model was never asked, so no zero was made up for the missing humidity
    assert model.matrices == []


def test_a_present_zero_is_a_measurement(model):
    score, flagged = ml_service.score_reading({"temperature": 0.0, "humidity": 0.0})
    assert score is not None and flagged is True
    assert model.matrices[0].tolist() == [[0.0, 0.0]]


def test_a_complete_reading_is_scored(model):
    score, flagged = ml_service.score_reading({"temperature": 25.0, "humidity": 50.0})
    assert score == 1.0 and flagged is True


def test_a_node_type_with_no_model_and_no_default_is_not_scored(monkeypatch):
    monkeypatch.setattr(ml_service, "_model", {"esp32": _AlwaysAnomalous()})
    assert ml_service.score_reading({"node_type": "pico_w", "temperature": 1.0, "humidity": 1.0}) == (None, False)


def test_without_any_model_the_pass_through_is_unchanged(monkeypatch):
    monkeypatch.setattr(ml_service, "_model", None)
    monkeypatch.setattr(ml_service, "_load_model", lambda: None)
    assert ml_service.score_reading({"temperature": 25.0}) == (0.0, False)


# -- training ---------------------------------------------------------------------------------

def _mixed_fleet(n=60):
    # an esp32 with vibration and current and a pico with humidity and light: no row has all six of the old features
    esp = [{"node_type": "esp32", "temperature": 24.0 + i % 3, "vibration_x": 0.2, "vibration_y": 0.2, "current_ma": 300.0}
           for i in range(n)]
    pico = [{"node_type": "pico_w", "temperature": 21.0 + i % 3, "humidity": 45.0, "light_level": 300.0} for i in range(n)]
    return esp + pico


def test_training_leaves_out_rows_with_a_missing_feature_and_counts_them():
    cols = ["temperature", "humidity"]
    fit = np.full((100, len(ml_service.SENSOR_COLS)), np.nan)
    fit[:, 0], fit[:, 1] = 20.0, 50.0
    fit[:5, 1] = np.nan
    scope = ml_service._scope_from("m", "machine", "m", cols, [fit], [], 1.0, 1.0, {})
    assert len(scope.fit) == 95 and scope.refused == {"missing_value": 5}


def test_training_with_no_sensor_readings_at_all_is_refused_so_the_old_model_is_kept():
    from app.services import training_data as td
    empty = np.empty((0, len(ml_service.SENSOR_COLS)))
    data = td.MachineData("a", "a", "esp32", 5.0, empty, empty, np.empty(0))
    outcome = ml_service.train_bundle([data], {"esp32": 1}, 1)
    assert outcome.status == "refused" and outcome.bundle is None


def test_the_general_model_uses_the_columns_most_rows_carry():
    assert ml_service.general_features(_mixed_fleet()) == ["temperature"]


def test_the_share_for_the_general_model_is_stated_and_applied():
    assert ml_service.GENERAL_PRESENCE == 0.9
    rows = [{"temperature": 20.0, "humidity": 50.0} for _ in range(91)] + [{"temperature": 20.0} for _ in range(9)]
    # humidity is on 91 per cent of rows and stays. At 89 per cent it would go
    assert ml_service.general_features(rows) == ["temperature", "humidity"]
    assert ml_service.general_features(rows[:80] + rows[91:]) == ["temperature"]


def test_when_no_column_is_common_enough_the_most_common_one_is_used():
    rows = [{"humidity": 50.0}] * 4 + [{"light_level": 5.0}] * 3 + [{"temperature": 20.0}] * 3
    assert ml_service.general_features(rows) == ["humidity"]
    assert ml_service.general_features([{"node_type": "x"}]) == []


def test_a_node_type_without_a_model_of_its_own_is_scored_by_the_general_one(monkeypatch):
    monkeypatch.setattr(ml_service, "_model", {"default": _AlwaysAnomalous(["temperature"])})
    score, _ = ml_service.score_reading({"node_type": "nano", "temperature": 22.0})
    assert score is not None


# -- the run of three -------------------------------------------------------------------------

def test_rows_missing_a_feature_never_open_an_anomaly_ticket(client, db, device, model):
    for _ in range(5):
        body = _post(client, device, temperature=25.0)
        assert body["anomaly_score"] is None
        assert body["is_anomaly"] is False
    assert _open(db, device) == []
    assert db.query(Ticket).filter(Ticket.device_id == device.id).count() == 0


def test_three_scored_anomalous_rows_still_open_the_alert_and_ticket(client, db, device, model):
    for _ in range(3):
        _post(client, device, temperature=25.0, humidity=50.0)
    alerts = _open(db, device)
    assert len(alerts) == 1
    assert alerts[0].category == "machine"
    assert db.query(Ticket).filter(Ticket.device_id == device.id).count() == 1


def test_unscored_rows_between_scored_ones_do_not_break_or_extend_the_run(client, db, device, model):
    _post(client, device, temperature=25.0, humidity=50.0)
    _post(client, device, temperature=25.0)
    _post(client, device, temperature=25.0, humidity=50.0)
    # two scored rows and one unscored: not yet a run of three
    assert _open(db, device) == []
    _post(client, device, temperature=25.0, humidity=50.0)
    assert len(_open(db, device)) == 1


def test_an_unscored_row_does_not_clear_an_open_alert(client, db, device, model):
    for _ in range(3):
        _post(client, device, temperature=25.0, humidity=50.0)
    for _ in range(3):
        _post(client, device, temperature=25.0)
    assert len(_open(db, device)) == 1


def _scored(db, device, score, age_s):
    db.add(Telemetry(
        device_id=device.id, temperature=25.0, anomaly_score=score, is_anomaly=(score or 0.0) >= 0.7,
        recorded_at=datetime.now(timezone.utc) - timedelta(seconds=age_s),
    ))
    db.flush()


def test_scored_rows_older_than_a_minute_are_ignored(db, device):
    _scored(db, device, 0.9, age_s=300)
    _scored(db, device, 0.9, age_s=200)
    _scored(db, device, 0.9, age_s=5)
    alert_service.evaluate_anomaly(device, db)
    assert _open(db, device) == []


def test_three_recent_scored_rows_count_whatever_lies_between(db, device):
    _scored(db, device, 0.9, age_s=30)
    _scored(db, device, None, age_s=20)
    _scored(db, device, 0.9, age_s=10)
    _scored(db, device, 0.9, age_s=1)
    alert_service.evaluate_anomaly(device, db)
    assert len(_open(db, device)) == 1


# -- the node type's model, the general model and the fallback between them ----------------------

def test_the_general_model_scores_a_reading_the_node_models_lacks_a_column_for(monkeypatch):
    own = _AlwaysAnomalous(["temperature", "humidity", "distance_mm"])
    general = _AlwaysAnomalous(["temperature"])
    monkeypatch.setattr(ml_service, "_model", {"esp32": own, "default": general})
    reading = {"node_type": "esp32", "temperature": 25.0, "humidity": 50.0}
    assert ml_service.score_reading(reading) == (1.0, True)
    assert own.matrices == [] and len(general.matrices) == 1
    assert ml_service.used_general_fallback(reading) is True


def test_the_node_models_own_model_is_used_when_it_can_score(monkeypatch):
    own = _AlwaysAnomalous(["temperature"])
    general = _AlwaysAnomalous(["temperature"])
    monkeypatch.setattr(ml_service, "_model", {"esp32": own, "default": general})
    reading = {"node_type": "esp32", "temperature": 25.0}
    ml_service.score_reading(reading)
    assert len(own.matrices) == 1 and general.matrices == []
    assert ml_service.used_general_fallback(reading) is False


def test_a_reading_neither_model_can_score_is_not_scored_and_names_what_is_missing(monkeypatch):
    own = _AlwaysAnomalous(["temperature", "humidity", "distance_mm"])
    general = _AlwaysAnomalous(["temperature", "humidity"])
    monkeypatch.setattr(ml_service, "_model", {"esp32": own, "default": general})
    reading = {"node_type": "esp32", "temperature": 25.0}
    assert ml_service.score_reading(reading) == (None, False)
    assert ml_service.missing_features(reading) == ["humidity", "distance_mm"]


def test_no_missing_inputs_are_reported_when_a_model_can_score(monkeypatch):
    monkeypatch.setattr(ml_service, "_model", {"default": _AlwaysAnomalous()})
    assert ml_service.missing_features({"temperature": 1.0, "humidity": 2.0}) == []
    monkeypatch.setattr(ml_service, "_model", None)
    assert ml_service.missing_features({"temperature": 1.0}) == []


def test_the_row_records_that_the_general_model_scored_it(client, db, device, monkeypatch):
    own = _AlwaysAnomalous(["temperature", "humidity", "distance_mm"])
    monkeypatch.setattr(ml_service, "_model", {"esp32": own, "default": _AlwaysAnomalous()})
    body = _post(client, device, node_type="esp32", temperature=25.0, humidity=50.0)
    assert body["anomaly_score"] == 1.0
    assert body["quality"] == {"scored_by": "general"}


def test_a_node_with_a_dropped_sensor_is_still_scored_through_the_general_model(client, db, device, monkeypatch):
    # the old trap: a node model trained with distance_mm present went dark when the sensor stopped for good
    own = _AlwaysAnomalous(["temperature", "humidity", "distance_mm"])
    monkeypatch.setattr(ml_service, "_model", {"esp32": own, "default": _AlwaysAnomalous()})
    for _ in range(3):
        _post(client, device, node_type="esp32", temperature=95.0, humidity=50.0)
    assert len(_open(db, device)) == 1


# -- a model file from before this change ---------------------------------------------------------

class _Legacy(_AlwaysAnomalous):
    # a model saved before the mark existed
    phaemos_schema = None


def _legacy_model():
    return _Legacy()


def test_an_old_model_file_scores_nothing_and_says_to_retrain(monkeypatch):
    # a bundle from before the mark is no longer served with its old meaning: it filled a missing value with zero and its
    # limits were not measured the way they are now. It scores nothing until a retrain and says so
    monkeypatch.setattr(ml_service, "_model", {"default": _legacy_model()})
    assert ml_service.score_reading({"temperature": 25.0, "humidity": 50.0}) == (None, False)
    assert ml_service.score_reading({"temperature": 25.0}) == (None, False)
    assert "until a retrain" in ml_service.scoring_problem()


def test_a_new_model_file_leaves_the_same_reading_unscored(monkeypatch):
    monkeypatch.setattr(ml_service, "_model", {"default": _AlwaysAnomalous()})
    assert ml_service.score_reading({"temperature": 25.0}) == (None, False)


class _OldFileModel:
    # a model object saved by an earlier version: it can score but carries no phaemos_schema mark. Module level so it
    # can be pickled
    phaemos_features = ["temperature", "humidity"]
    offset_ = 0.0

    def score_samples(self, X):
        return [-0.5] * len(X)


def test_loading_an_old_model_file_logs_a_warning(monkeypatch, tmp_path, caplog):
    import joblib
    path = tmp_path / "model.pkl"
    joblib.dump({"default": _OldFileModel()}, path)
    monkeypatch.setattr(ml_service, "MODEL_PATH", str(path))
    monkeypatch.setattr(ml_service, "_model", None)
    monkeypatch.setattr(ml_service, "_load_failure", None)
    monkeypatch.setattr(ml_service, "_problem", None)
    with caplog.at_level("WARNING"):
        ml_service._load_model()
    assert "retrain" in caplog.text
    ml_service._model = None
