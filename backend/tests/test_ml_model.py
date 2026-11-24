"""
The anomaly model of services/ml_service.py: the measured boundary, the budget and detection checks, what a retrain
refuses and says, which model scores a reading, the model status and the model file. The machines are simulated by
the evaluation's generator, so these tests need no database.
"""
import io
import time

import joblib
import numpy as np
import pytest

from app.scripts.evaluate_model import ESP, Spec, simulate
from app.services import ml_service as ml
from app.services import model_evaluation as ev
from app.services import training_data as td

SPEC = Spec("a", "esp32", 10, ESP)


def _data(index, name, days=7, node="esp32"):
    spec = Spec(name, node, SPEC.interval_s, SPEC.cols)
    sim = simulate(spec, index, days)
    return td.select_from_arrays(sim.times, sim.X, sim.reasons, spec.interval_s, device_id=name, name=name, node_type=node)


@pytest.fixture(scope="module")
def trained():
    # a week of a 10 s machine is half the fortnight the evaluation learns from, so these models may find too few
    # faults to pass the detection check. That check has its own tests below and is switched off here, so the other
    # tests have a bundle to work with
    patch = pytest.MonkeyPatch()
    patch.setattr(ev, "MAX_MISSED_SHARE", 1.0)
    try:
        datas = [_data(0, "a"), _data(1, "b")]
        return ml.train_bundle(datas, {"esp32": 2}, 2), datas
    finally:
        patch.undo()


@pytest.fixture
def serving(trained, monkeypatch):
    outcome, _ = trained
    monkeypatch.setattr(ml, "_model", outcome.bundle)
    monkeypatch.setattr(ml, "_load_model", lambda: None)
    monkeypatch.setattr(ml, "_problem", None)
    return outcome.bundle


def _reading(node="esp32", **extra):
    base = {"node_type": node, "temperature": 24.0, "humidity": 50.0, "pressure": 1013.0, "vibration_x": 0.05,
            "vibration_y": 0.05, "vibration_z": 1.0, "bus_voltage": 5.0, "current_ma": 150.0, "power_mw": 750.0,
            "sound_level": 40.0, "light_level": 100.0}
    return {**base, **extra}


# -- scikit-learn's own numbers ------------------------------------------------------------------------------------

def test_the_fast_scorer_gives_scikit_learns_numbers():
    from sklearn.ensemble import IsolationForest
    rng = np.random.default_rng(0)
    model = IsolationForest(n_estimators=40, max_samples=256, contamination="auto", random_state=1).fit(rng.normal(size=(2000, 5)))
    probe = rng.normal(size=(300, 5)) * 2.0
    assert np.allclose(ml.raw_scores(model, probe), model.score_samples(probe), atol=1e-9)


def test_contamination_auto_sets_the_unused_offset_at_minus_a_half():
    from sklearn.ensemble import IsolationForest
    model = IsolationForest(contamination="auto", random_state=0).fit(np.random.default_rng(0).normal(size=(300, 3)))
    assert model.offset_ == -0.5
    scores = model.score_samples(np.random.default_rng(1).normal(size=(50, 3)))
    # score_samples is the opposite of the paper's score: between -1 and 0, lower is more abnormal
    assert scores.min() > -1.0 and scores.max() < 0.0


def test_normalise_puts_the_boundary_at_the_threshold_and_the_typical_reading_at_zero():
    class M:
        offset_ = -0.62
        phaemos_typical_decision = 0.12
    out = ml.normalise(M(), np.array([-0.62, -0.5, -0.9]))
    assert out[0] == pytest.approx(ml.ANOMALY_THRESHOLD)
    assert out[1] == pytest.approx(0.0, abs=1e-9)
    assert out[2] == 1.0


# -- training and measuring ------------------------------------------------------------------------------------------

def test_a_retrain_on_clean_readings_is_accepted_with_a_measurement_for_each_model(trained):
    outcome, _ = trained
    assert outcome.status == "trained"
    assert {"machine:a", "machine:b", "esp32", "default", ml.META_KEY} <= set(outcome.bundle)
    for record in outcome.models:
        assert record["state"] == "ready"
        assert record["validation"]["per_week"] <= ev.BUDGET_PER_WEEK
        assert record["heldout_hours"] > 0 and record["rows_fit"] >= ml.MIN_FIT_ROWS
        assert record["rows_heldout"] >= ev.MIN_HELDOUT_ROWS
        # the reported figure is the test part's, with its interval and the test part is at least a day
        assert record["test"]["hours"] >= td.MIN_TEST_HOURS
        assert record["false_alerts_per_week"] == record["test"]["per_week"]
        assert record["false_alerts_per_week_high_95"] >= record["false_alerts_per_week"]
        assert len(record["detection"]["faults"]) == len(ev.FAULT_KINDS)
        assert set(record["rows_refused"]) <= set(td.REFUSAL_REASONS) | {"missing_value"}


def test_the_three_parts_never_overlap_in_time(trained):
    _, datas = trained
    for d in datas:
        assert d.fit_times.max() < d.val_times.min() and d.val_times.max() < d.test_times.min()


def test_the_forest_boundary_is_the_stated_quantile_of_the_validation_and_fit_readings(trained):
    outcome, datas = trained
    model = outcome.bundle["machine:a"]
    record = ml._record_of(model)
    cols = model.phaemos_features
    idx = [td.SENSOR_COLS.index(c) for c in cols]
    seg_x = datas[0].val[:, idx]
    keep = ~np.isnan(seg_x).any(axis=1)
    parts = ml.sequence_parts(model, datas[0].val_times[keep], seg_x[keep], datas[0].interval_s, prime=True)
    fit = datas[0].fit[:, idx]
    fit = fit[~np.isnan(fit).any(axis=1)]
    raw_fit = ml._forest_raw(model, ml._derived(model, fit))
    q = record["quantile"]
    median = float(np.median(np.concatenate([parts["forest"], raw_fit])))
    boundary = float(min(np.quantile(parts["forest"], q), np.quantile(raw_fit, q)))
    boundary -= ml.FOREST_MARGIN * (median - boundary)
    assert model.offset_ == pytest.approx(boundary, abs=1e-9)
    # and so at most the stated share of validation readings is beyond it and the typical one sits at 0
    share = float((parts["forest"] <= model.offset_).mean())
    assert share <= q + 1e-9
    assert np.median(ml.normalise(model, parts["forest"])) == pytest.approx(0.0, abs=0.1)


def test_every_model_this_version_trains_carries_the_mark_and_the_scaler(trained):
    outcome, _ = trained
    for key, model in outcome.bundle.items():
        if key == ml.META_KEY:
            continue
        assert model.phaemos_schema == ml.SCHEMA_VERSION
        center, scale = model.phaemos_scaler
        assert len(center) == len(scale) == len(model.phaemos_features)
        assert model.offset_ != -0.5


def test_training_is_deterministic(trained):
    outcome, datas = trained
    again = ml.train_bundle([_data(0, "a"), _data(1, "b")], {"esp32": 2}, 2)
    assert [r["boundary"] for r in again.models] == [r["boundary"] for r in outcome.models]


def test_a_model_over_the_budget_is_refused_and_the_message_says_what_to_do(monkeypatch):
    monkeypatch.setattr(ev, "BUDGET_PER_WEEK", -1.0)
    outcome = ml.train_bundle([_data(0, "a")], {"esp32": 1}, 1)
    assert outcome.status == "refused" and outcome.bundle is None
    message = outcome.models[0]["message"]
    assert "false alerts per machine per week on healthy readings it did not train on" in message
    assert "The model in service is untouched" in message
    assert "Let the machine run a few more normal days and retrain" in message
    assert outcome.models[0]["tightenings"] == len(ev.QUANTILES) - 1


def test_the_boundary_is_tightened_before_a_model_is_refused(monkeypatch):
    calls = []
    real = ev.false_alert_rate

    def counted(segments, fn):
        result = real(segments, fn)
        calls.append(result)
        return result

    monkeypatch.setattr(ev, "false_alert_rate", counted)
    monkeypatch.setattr(ev, "BUDGET_PER_WEEK", -1.0)
    outcome = ml.train_bundle([_data(0, "a")], {"esp32": 1}, 1)
    measured = [r for r in outcome.models if r.get("tightenings") is not None and r.get("validation")]
    # every model that was measured was measured once per quantile and refused after the last
    assert measured and len(calls) == len(ev.QUANTILES) * len(measured)
    assert all(r["tightenings"] == len(ev.QUANTILES) - 1 and r["state"] == "refused" for r in measured)


def test_a_model_whose_detector_boundary_cannot_be_crossed_is_refused(monkeypatch):
    # a cap so low that every measured boundary is above half of it
    monkeypatch.setattr(ml.cd, "S_CAP", 2.0 * ml.DETECTOR_MIN_BOUNDARY * 0.9)
    monkeypatch.setattr(ev, "MAX_MISSED_SHARE", 1.0)
    outcome = ml.train_bundle([_data(0, "a")], {"esp32": 1}, 1)
    record = next(r for r in outcome.models if r["key"] == "machine:a")
    assert record["state"] == "refused" and "could hardly ever raise an alert" in record["message"]
    assert "machine:a" not in (outcome.bundle or {})


def test_a_model_with_no_detection_trials_is_refused_and_never_accepted_unchecked(monkeypatch):
    monkeypatch.setattr(ev, "TRIALS", 0)
    outcome = ml.train_bundle([_data(0, "a")], {"esp32": 1}, 1)
    assert outcome.status == "refused"
    assert all("could not be checked for detection" in r["message"] for r in outcome.models if r["state"] == "refused")


def test_a_pooled_model_of_hundreds_of_machines_still_has_detection_trials():
    # with 400 machines of one node type every machine's share of the held-out rows used to be 150, under the 200 a
    # trial needs, so the check ran no trial. The pool keeps a dozen machines' full runs instead
    pool = ml._Pool("the esp32 node type", 400)
    assert len(pool.pick) == ml.td.POOL_HELD_MACHINES and pool.held_share >= 2000


def test_a_model_that_misses_too_many_faults_is_refused_with_the_figures(monkeypatch):
    monkeypatch.setattr(ev, "MAX_MISSED_SHARE", -0.01)
    outcome = ml.train_bundle([_data(0, "a")], {"esp32": 1}, 1)
    assert outcome.status == "refused"
    message = outcome.models[0]["message"]
    assert " faults injected into healthy readings and at least " in message and "The model in service is untouched" in message


def test_a_refused_retrain_keeps_the_models_in_service_and_a_partial_one_carries_them_over(trained, monkeypatch):
    monkeypatch.setattr(ev, "MAX_MISSED_SHARE", 1.0)
    outcome, _ = trained
    carried = outcome.bundle["esp32"]
    previous = {"pico_w": carried, "machine:gone": object(), "default": outcome.bundle["default"]}
    partial = ml.train_bundle([_data(0, "a")], {"esp32": 1}, 1, previous)
    assert partial.status == "trained"
    # a model of a node type this run did not touch stays and a machine that no longer exists is dropped
    assert partial.bundle["pico_w"] is carried and "machine:gone" not in partial.bundle
    assert partial.bundle["machine:a"].phaemos_schema == ml.SCHEMA_VERSION


def test_a_carried_model_older_than_the_limit_is_withdrawn_and_the_machine_is_named_unmonitored(trained, monkeypatch):
    from datetime import datetime, timedelta, timezone
    outcome, _ = trained
    old = outcome.bundle["machine:b"]
    monkeypatch.setattr(ev, "BUDGET_PER_WEEK", -1.0)
    # the limit is seven days, pinned here and not read from the constant
    assert ml.CARRY_MAX_DAYS == 7
    later = datetime.fromisoformat(old.phaemos_trained_at) + timedelta(days=7.5)
    result = ml.train_bundle([_data(1, "b")], {"esp32": 1}, 1, {"machine:b": old}, now=later)
    assert "machine:b" not in (result.bundle or {})
    record = next(r for r in result.models if r["key"] == "machine:b")
    assert "has been withdrawn" in record["message"]
    assert "b" in result.unmonitored
    # within the limit it is carried and the message says when it will be withdrawn
    sooner = datetime.fromisoformat(old.phaemos_trained_at) + timedelta(days=6.5)
    kept = ml.train_bundle([_data(1, "b")], {"esp32": 1}, 1, {"machine:b": old}, now=sooner.astimezone(timezone.utc))
    record = next(r for r in kept.models if r["key"] == "machine:b")
    assert "is withdrawn after" in record["message"] and kept.unmonitored == {}


def test_a_worse_challenger_does_not_replace_the_champion(trained, monkeypatch):
    outcome, _ = trained
    champion = outcome.bundle["machine:a"]
    monkeypatch.setattr(ev, "MAX_MISSED_SHARE", 1.0)
    real = ml.evaluate_on

    def better(model, segments):
        found = real(model, segments)
        # the model in service raised no alert and caught everything on the same newest readings
        found["alerts"] = 0
        found["detection"] = {**found["detection"], "caught": found["detection"]["trials"]}
        return found

    monkeypatch.setattr(ml, "evaluate_on", better)
    real_fit = ml.fit_model

    def worse(scope):
        model, record = real_fit(scope)
        if model is not None and record.get("test"):
            record["test"]["alerts"] = 5
        return model, record

    monkeypatch.setattr(ml, "fit_model", worse)
    result = ml.train_bundle([_data(0, "a")], {"esp32": 1}, 1, {"machine:a": champion})
    assert result.bundle is None or result.bundle.get("machine:a") is champion
    record = next(r for r in result.models if r["key"] == "machine:a")
    assert record["state"] == "refused" and "the model in service is kept" in record["message"]


def test_a_retrain_that_moves_the_normal_too_far_is_refused_until_a_person_accepts(trained, monkeypatch, tmp_path):
    outcome, _ = trained
    champion = outcome.bundle["machine:a"]
    monkeypatch.setattr(ml, "MODEL_PATH", str(tmp_path / "model.pkl"))
    monkeypatch.setattr(ev, "MAX_MISSED_SHARE", 1.0)
    walked = _data(0, "a")
    j = td.SENSOR_COLS.index("temperature")
    for part in (walked.fit, walked.val, walked.test):
        part[:, j] += 6.0
    result = ml.train_bundle([walked], {"esp32": 1}, 1, {"machine:a": champion})
    record = next(r for r in result.models if r["key"] == "machine:a")
    assert record["state"] == "refused" and "a person must accept the move" in record["message"]
    assert "a" in result.moves and (result.bundle or {}).get("machine:a", champion) is champion
    ml.accept_move("a", "admin")
    accepted = ml.train_bundle([walked], {"esp32": 1}, 1, {"machine:a": champion})
    assert accepted.bundle["machine:a"] is not champion and accepted.used_acceptances == ["a"]
    # the accepted model is the new anchor
    assert accepted.bundle["machine:a"].phaemos_anchor is accepted.bundle["machine:a"].phaemos_baseline


def test_a_machine_with_under_24_hours_is_learning_and_is_not_trained():
    short = _data(0, "a", days=1)
    outcome = ml.train_bundle([short], {"esp32": 1}, 1)
    assert outcome.status == "refused" and outcome.bundle is None
    lines = outcome.learning
    assert lines and any(line.startswith("the esp32 node type has ") and line.endswith("so leave it running.") for line in lines)
    assert "a" in outcome.unmonitored


def test_too_few_held_back_readings_keep_a_model_in_learning(monkeypatch):
    monkeypatch.setattr(ev, "MIN_HELDOUT_ROWS", 10 ** 6)
    outcome = ml.train_bundle([_data(0, "a")], {"esp32": 1}, 1)
    assert outcome.status == "refused"
    assert any("needs at least" in r["message"] and "stays in learning" in r["message"] for r in outcome.models)


def test_machines_beyond_the_cap_get_a_light_model_of_their_own(monkeypatch):
    monkeypatch.setattr(ml, "MAX_MACHINE_MODELS", 1)
    monkeypatch.setattr(ev, "MAX_MISSED_SHARE", 1.0)
    outcome = ml.train_bundle([_data(0, "a"), _data(1, "b")], {"esp32": 2}, 2)
    assert hasattr(outcome.bundle["machine:a"], "estimators_")
    light = outcome.bundle["machine:b"]
    assert not hasattr(light, "estimators_") and light.phaemos_detector is not None
    assert outcome.bundle[ml.META_KEY]["machines"]["b"]["scope"] == "machine"
    buf = io.BytesIO()
    joblib.dump(light, buf)
    assert len(buf.getvalue()) < 200_000


def test_the_bundle_stays_small_and_scoring_one_reading_is_fast(serving):
    buf = io.BytesIO()
    joblib.dump(serving, buf)
    models = [m for k, m in serving.items() if k != ml.META_KEY]
    # about 3.6 MB a model with a forest
    assert len(buf.getvalue()) < 4.5e6 * len(models)
    reading = _reading()
    ml.score_reading(reading, device_id="a")
    start = time.perf_counter()
    for _ in range(100):
        ml.score_reading(reading, device_id="a")
    # a generous bound for a loaded machine: scikit-learn's own call took 15 to 25 ms. The measured figure is in the docs
    assert (time.perf_counter() - start) / 100 < 0.01


# -- which model scores a reading ----------------------------------------------------------------------------------------

def test_the_machines_own_model_scores_first_then_its_node_type_then_the_general_one(serving):
    reading = _reading()
    assert ml.score_reading(reading, device_id="a")[0] is not None
    assert ml._local.scored[1] == "machine:a" and ml.used_general_fallback(reading) is False
    ml.score_reading(reading, device_id="unknown-machine")
    assert ml._local.scored[1] == "esp32"
    # a node type with no model of its own goes to the general model when the reading carries its columns
    other = _reading("pico_w")
    assert ml.score_reading(other, device_id="x")[0] is not None
    assert ml._local.scored[1] == "default" and ml.used_general_fallback(other) is False


def test_a_far_off_reading_scores_high_and_an_ordinary_one_low(serving):
    low, flagged_low = ml.score_reading(_reading(), device_id="a")
    high, flagged_high = ml.score_reading(_reading(vibration_x=1.5, vibration_y=1.5, current_ma=1500.0), device_id="a")
    assert low < ml.ANOMALY_THRESHOLD and not flagged_low
    assert high >= ml.ANOMALY_THRESHOLD and flagged_high


def test_a_node_type_still_learning_is_not_handed_to_the_general_model(serving, monkeypatch):
    bundle = dict(serving)
    bundle[ml.META_KEY] = {**serving[ml.META_KEY], "learning_node_types": {"pico_w": 5.0}}
    monkeypatch.setattr(ml, "_model", bundle)
    assert ml.score_reading({"node_type": "pico_w", "temperature": 24.0}, device_id="x") == (None, False)


# -- the model status ------------------------------------------------------------------------------------------------------

KEYS = {"state", "scope", "hours_collected", "hours_needed", "false_alerts_per_week", "false_alerts_per_week_high_95",
        "trained_at", "refusal", "refused_at", "monitored", "reason", "ambient", "light"}


def test_status_when_there_is_no_model_file(monkeypatch):
    monkeypatch.setattr(ml, "_model", None)
    monkeypatch.setattr(ml, "_load_model", lambda: None)
    monkeypatch.setattr(ml, "_problem", None)
    status = ml.model_status("a", "esp32")
    assert set(status) == KEYS and status["state"] == "none" and status["scope"] is None


def test_status_when_the_file_will_not_load(monkeypatch):
    monkeypatch.setattr(ml, "_load_model", lambda: None)
    monkeypatch.setattr(ml, "_problem", "the model file could not be loaded (ValueError)")
    assert ml.model_status("a", "esp32")["state"] == "error"


def test_status_for_a_machine_with_its_own_model(serving):
    status = ml.model_status("a", "esp32")
    assert set(status) == KEYS
    assert status["state"] == "ready" and status["scope"] == "machine" and status["monitored"] is True
    # a node that posts every 10 s needs five days: the test part alone must hold a day
    assert status["hours_needed"] == pytest.approx(td.hours_needed(10), abs=0.05) and status["hours_collected"] >= 24.0
    assert status["false_alerts_per_week"] is not None and status["false_alerts_per_week_high_95"] >= status["false_alerts_per_week"]
    assert status["trained_at"].startswith("20")
    # the simulated ESP32 has no machine temperature beside its air temperature, so it has no ambient reference
    assert status["ambient"] == ml.NO_AMBIENT_REASON


def test_status_for_a_machine_served_by_its_node_type_or_the_general_model(serving):
    assert ml.model_status("new-machine", "esp32")["scope"] == "node_type"
    assert ml.model_status("new-machine", "pico_w")["scope"] == "general"


def test_status_for_a_machine_with_too_little_data_is_learning_with_the_hours(serving, monkeypatch):
    bundle = {k: v for k, v in serving.items() if k not in ("esp32", "default")}
    bundle[ml.META_KEY] = {**serving[ml.META_KEY], "machines": {"c": {"clean_hours": 9.5, "node_type": "esp32"}}}
    monkeypatch.setattr(ml, "_model", bundle)
    status = ml.model_status("c", "esp32")
    assert status["state"] == "learning" and status["hours_collected"] == 9.5
    assert status["hours_needed"] == ml.td.hours_needed(5.0)
    assert status["scope"] is None and status["false_alerts_per_week"] is None and status["monitored"] is False


class _Old:
    phaemos_schema = 2
    phaemos_features = ["temperature"]
    offset_ = 0.0

    def score_samples(self, X):
        return np.full(len(X), -0.4)


def test_an_old_bundle_scores_nothing_and_is_reported_as_legacy(monkeypatch):
    monkeypatch.setattr(ml, "_model", {"default": _Old()})
    monkeypatch.setattr(ml, "_load_model", lambda: None)
    monkeypatch.setattr(ml, "_problem", None)
    status = ml.model_status("a", "esp32")
    assert status["state"] == "legacy" and status["monitored"] is False
    assert ml.score_reading({"temperature": 25.0}, device_id="a") == (None, False)
    assert "earlier version" in ml.scoring_problem()
    assert ml.model_state() == "legacy"


# -- the model file ---------------------------------------------------------------------------------------------------------

def test_the_file_round_trips_keeps_the_previous_one_and_falls_back_to_it(serving, monkeypatch, tmp_path):
    path = tmp_path / "model.pkl"
    monkeypatch.setattr(ml, "MODEL_PATH", str(path))
    monkeypatch.undo()
    monkeypatch.setattr(ml, "MODEL_PATH", str(path))
    ml.save_model(serving)
    ml.save_model(serving)
    assert path.exists() and (tmp_path / "model.pkl.prev").exists()
    path.write_bytes(b"not a model")
    monkeypatch.setattr(ml, "_model", None)
    monkeypatch.setattr(ml, "_load_failure", None)
    monkeypatch.setattr(ml, "_loaded_mtime", None)
    ml._load_model()
    assert ml._model is not None and ml._problem is None
    assert ml.score_reading(_reading(), device_id="a")[0] is not None
    monkeypatch.setattr(ml, "_model", None)


def test_a_newer_file_written_by_another_worker_is_picked_up(serving, monkeypatch, tmp_path):
    path = tmp_path / "model.pkl"
    monkeypatch.undo()
    monkeypatch.setattr(ml, "MODEL_PATH", str(path))
    ml.save_model(serving)
    monkeypatch.setattr(ml, "_model", None)
    ml._load_model()
    first = ml._loaded_mtime
    assert first is not None
    ml.save_model({"default": serving["default"]})
    import os
    os.utime(path, (first + 5, first + 5))
    monkeypatch.setattr(ml, "_next_check", 0.0)
    ml._maybe_reload()
    assert "machine:a" not in ml._model
    monkeypatch.setattr(ml, "_model", None)
    monkeypatch.setattr(ml, "_loaded_mtime", None)


# -- the change detector in the model ---------------------------------------------------------------------------------

def test_a_machine_model_carries_a_detector_with_a_measured_and_censored_boundary(trained):
    outcome, _ = trained
    model = outcome.bundle["machine:a"]
    detector = model.phaemos_detector
    assert ml.DETECTOR_MIN_BOUNDARY <= detector.boundary <= ml.DETECTOR_MAX_BOUNDARY_SHARE * ml.cd.S_CAP
    assert detector.extra["interval_s"] == 10
    arl = ml._record_of(model)["detector"]
    # with no false crossing seen the run length is censored: only a lower bound is stated, a third of the hours
    if arl["crossings"] == 0:
        assert arl["censored"] is True and arl["arl_hours"] is None
        assert arl["arl_hours_lower_95"] == pytest.approx(arl["hours_watched"] / 2.996, rel=0.01)
    # node type and general models are pooled over machines and have none
    assert not hasattr(outcome.bundle["esp32"], "phaemos_detector")


def test_the_run_length_bound_is_the_poisson_one():
    zero = ml.arl_bounds(0, 41.7)
    assert zero["censored"] and zero["arl_hours"] is None and zero["arl_hours_lower_95"] == pytest.approx(13.9, abs=0.05)
    two = ml.arl_bounds(2, 100.0)
    assert two["arl_hours"] == 50.0 and two["arl_hours_lower_95"] == pytest.approx(100.0 / 6.296, abs=0.05)


def test_scoring_in_order_keeps_a_state_per_machine_and_never_touches_another(serving, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.services import change_detector as cd
    store = cd.MemoryStateStore()
    monkeypatch.setattr(ml, "_state_store", store)
    start = datetime(2031, 1, 1, tzinfo=timezone.utc)
    for i in range(5):
        ml.score_reading(_reading(), device_id="a", at=start + timedelta(seconds=10 * i))
    assert store.get("a") is not None and store.get("b") is None
    assert store.get("a").last_t == (start + timedelta(seconds=40)).timestamp()
    # a manual test score leaves the state alone
    ml.score_reading(_reading(), device_id="a", at=start + timedelta(seconds=999), track=False)
    assert store.get("a").last_t == (start + timedelta(seconds=40)).timestamp()


def test_a_sensor_that_drifts_away_from_what_the_load_expects_is_scored_and_explained(serving, trained, monkeypatch):
    from datetime import datetime, timezone
    from app.services import change_detector as cd
    store = cd.MemoryStateStore()
    monkeypatch.setattr(ml, "_state_store", store)
    _, datas = trained
    model = serving["machine:a"]
    cols = model.phaemos_features
    idx = [td.SENSOR_COLS.index(c) for c in cols]
    rows = datas[0].test[:, idx]
    times = datas[0].test_times
    keep = ~np.isnan(rows).any(axis=1)
    rows, times = rows[keep][:1500], times[keep][:1500]
    rows = rows.copy()
    j = cols.index("temperature")
    # a real stretch of the machine, then its temperature two degrees above what it was for the second half
    rows[800:, j] += 2.0
    # a machine in service: its slow levels have followed it, so they start where its first hour of readings is
    state = ml._fresh_state(model)
    first = times < times[0] + 3600.0
    state.level, state.base_level = ml._present_levels(model, times[first], ml._derived(model, rows[first]))
    store.put("a", state)
    flagged = []
    for i in range(len(rows)):
        reading = {**{c: float(rows[i, k]) for k, c in enumerate(cols)}, "node_type": "esp32"}
        flagged.append(ml.score_reading(reading, device_id="a", at=datetime.fromtimestamp(times[i], tz=timezone.utc))[1])
    # a week of a 10 s machine gives a short validation part, so a healthy stretch can cross now and then (the test part's
    # figure says so). The fault must stand clear of it: flagged far more often after the step than before and blamed
    before, after = np.mean(flagged[200:800]), np.mean(flagged[900:])
    assert after >= 0.8 and after - before >= 0.5
    note = ml.explain_reading(reading, device_id="a")
    assert note is not None and note["sensor"] == "temperature" and note["direction"] == "above"


def test_a_state_left_by_another_model_is_not_fed_to_this_one(serving, monkeypatch):
    from app.services import change_detector as cd
    store = cd.MemoryStateStore()
    # the state a three column model left: a retrain changed the columns
    store.put("a", cd.DetectorState(smooth=np.zeros((2, 3)), last_t=1.0, warm_from=0.0, s_pos=np.zeros(3), s_neg=np.zeros(3),
                                    since_pos=np.zeros(3), since_neg=np.zeros(3), model_id="another-model"))
    monkeypatch.setattr(ml, "_state_store", store)
    score, _ = ml.score_reading(_reading(), device_id="a")
    assert score is not None and ml.scoring_problem() is None and ml.model_state() == "ok"
    assert store.get("a").model_id == serving["machine:a"].phaemos_id


def test_a_scoring_failure_on_one_machine_is_that_readings_problem_and_not_the_fleets(serving, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("shapes do not match")
    monkeypatch.setattr(ml, "score_step", broken)
    assert ml.score_reading(_reading(), device_id="a") == (None, False)
    assert ml.scoring_problem() == "scoring failed (ValueError)"
    assert ml.model_state() == "ok" and ml.model_status("b", "esp32")["state"] == "ready"
    # another machine scored next is not marked
    assert ml.score_reading(_reading(), device_id="unknown")[0] is not None and ml.scoring_problem() is None


# -- refusals and the cap on machine models, as the status shows them ------------------------------------------------

def test_a_machine_whose_model_the_last_retrain_refused_carries_the_message_and_the_time(serving, monkeypatch, tmp_path):
    monkeypatch.setattr(ml, "MODEL_PATH", str(tmp_path / "model.pkl"))
    monkeypatch.setattr(ml, "_refusal_cache", {"mtime": None, "data": {}})
    ml.save_last_retrain({
        "status": "refused", "finished_at": "2031-05-04T03:30:00+00:00",
        "models": [{"key": "machine:c", "state": "refused", "message": "c caught 1 of 20 faults"},
                   {"key": "machine:d", "state": "ready", "message": ""}],
    })
    c = ml.model_status("c", "esp32")
    assert c["refusal"] == "c caught 1 of 20 faults" and c["refused_at"] == "2031-05-04T03:30:00+00:00"
    d = ml.model_status("d", "esp32")
    assert d["refusal"] is None and d["refused_at"] is None
    assert set(c) == KEYS


def test_a_machine_beyond_the_cap_is_monitored_by_its_light_model_and_says_why(monkeypatch):
    monkeypatch.setattr(ml, "MAX_MACHINE_MODELS", 1)
    monkeypatch.setattr(ev, "MAX_MISSED_SHARE", 1.0)
    outcome = ml.train_bundle([_data(0, "a"), _data(1, "b")], {"esp32": 2}, 2)
    monkeypatch.setattr(ml, "_model", outcome.bundle)
    monkeypatch.setattr(ml, "_load_model", lambda: None)
    monkeypatch.setattr(ml, "_problem", None)
    over = ml.model_status("b", "esp32")
    assert over["state"] == "ready" and over["scope"] == "machine" and over["light"] is True and over["monitored"] is True
    rows = {r["device_id"]: r for r in ml.machine_report()}
    assert rows["a"]["over_cap"] is False and rows["a"]["light"] is False
    assert rows["b"]["over_cap"] is True and "light model of its own" in rows["b"]["reason"]
    summary = ml.bundle_summary()
    assert summary["max_machine_models"] == 1 and summary["monitored_machines"] == 2 and summary["unmonitored_machines"] == 0


def test_a_machine_with_no_working_model_is_shown_plainly_as_unmonitored(serving, monkeypatch):
    bundle = {k: v for k, v in serving.items() if k not in ("esp32", "default")}
    bundle[ml.META_KEY] = {**serving[ml.META_KEY],
                           "machines": {"z": {"clean_hours": 200.0, "hours_needed": 120.0, "node_type": "esp32"}},
                           "unmonitored": {"z": "its own model was refused: it caught 2 of 20 faults"}}
    monkeypatch.setattr(ml, "_model", bundle)
    status = ml.model_status("z", "esp32")
    assert status["state"] == "none" and status["monitored"] is False
    assert "caught 2 of 20 faults" in status["reason"]
    # its readings are unscored and say why, which is what the no-scored-reading alert and the row's quality carry
    assert ml.score_reading(_reading(), device_id="z") == (None, False)
    assert ml.scoring_problem().startswith("no model is in service for this machine")
    assert ml.bundle_summary()["unmonitored_machines"] == 1


def test_the_cap_is_a_setting():
    from app.config import settings
    assert ml.MAX_MACHINE_MODELS == settings.ml_max_machine_models == 24


# -- a machine's state across a retrain and from a cold start ---------------------------------------------------------

def _stepped(model, data, n=600):
    cols = model.phaemos_features
    idx = [td.SENSOR_COLS.index(c) for c in cols]
    X = data.test[:, idx]
    keep = ~np.isnan(X).any(axis=1)
    X, t = X[keep][:n], data.test_times[keep][:n]
    state = ml._fresh_state(model)
    ml.sequence_parts(model, t, X, data.interval_s, state=state)
    return state, t, X


def test_a_retrain_with_the_same_sensors_carries_the_state_and_its_evidence(trained):
    import copy
    outcome, datas = trained
    model = outcome.bundle["machine:a"]
    state, t, X = _stepped(model, datas[0])
    state.s_pos = state.s_pos + 0.5 * model.phaemos_detector.boundary
    new = copy.deepcopy(model)
    new.phaemos_id = "the next night's model"
    new.phaemos_detector.scale = new.phaemos_detector.scale * 1.2
    new.phaemos_detector.boundary = model.phaemos_detector.boundary * 1.5
    carried = ml.carry_state(state, new)
    assert carried is not None and carried.model_id == "the next night's model"
    # the smoothed views are the same readings in the new units, so no warm-up is needed
    old_raw = state.smooth * model.phaemos_detector.scale + model.phaemos_detector.center
    new_raw = carried.smooth * new.phaemos_detector.scale + new.phaemos_detector.center
    assert np.allclose(old_raw, new_raw) and carried.warm_from == state.warm_from
    # an alert that was building keeps its share of the boundary
    assert np.allclose(carried.s_pos / new.phaemos_detector.boundary, state.s_pos / model.phaemos_detector.boundary)


def test_a_retrain_that_changes_the_sensors_or_their_scales_starts_cold(trained):
    import copy
    outcome, datas = trained
    model = outcome.bundle["machine:a"]
    state, _, _ = _stepped(model, datas[0])
    wider = copy.deepcopy(model)
    wider.phaemos_detector.scale = wider.phaemos_detector.scale * (ml.CARRY_SCALE_FACTOR + 0.5)
    assert ml.carry_state(state, wider) is None
    other = copy.deepcopy(model)
    other.phaemos_detector.cols = list(reversed(other.phaemos_detector.cols))
    assert ml.carry_state(state, other) is None


def test_a_cold_start_takes_its_levels_from_the_machines_own_readings(trained):
    from app.services import change_detector as cd
    outcome, datas = trained
    model = outcome.bundle["machine:a"]
    det = model.phaemos_detector
    cols = model.phaemos_features
    idx = [td.SENSOR_COLS.index(c) for c in cols]
    X = datas[0].test[:, idx]
    keep = ~np.isnan(X).any(axis=1)
    X, t = X[keep], datas[0].test_times[keep]
    warm = t < t[0] + cd.WARMUP_S - 60.0
    X, t = X[warm], t[warm]
    state = ml._fresh_state(model)
    assert state.level is None and state.base_level is None
    ml.sequence_parts(model, t, X, datas[0].interval_s, state=state)
    # over the warm-up the level is the running mean of this machine's own residuals (the first reading only seeds the
    # smoothed views), clipped to its bound and nothing from training
    r = cd.residuals(det, t, X)[1:]
    expected = np.clip(np.clip(r, -cd.Z_CAP * det.quiet_sd, cd.Z_CAP * det.quiet_sd).mean(axis=0),
                       -det.level_bound, det.level_bound) * det.active
    assert state.cold is True and state.warm_n == len(t) - 1
    assert np.allclose(state.level, expected, atol=0.05 * np.maximum(det.level_bound, 1e-6))


def test_a_site_reference_is_the_reference_only_for_a_machine_that_has_none_of_its_own():
    esp = ["temperature", "humidity", "pressure", "current_ma", td.AMBIENT_REF]
    plan = ml.ambient_plan(ml.machine_columns(esp))
    assert plan["source"] == "site" and plan["rise"] == ["temperature"]
    assert set(plan["context"]) == {td.AMBIENT_REF, "humidity", "pressure"}
    # a node with its own pair keeps it and a node with no temperature has no use for the room's
    own = ["temperature", "contact_temp", "humidity", td.AMBIENT_REF]
    assert td.AMBIENT_REF not in ml.machine_columns(own) and ml.ambient_plan(ml.machine_columns(own))["source"] == "own"
    assert ml.machine_columns(["vibration_x", "vibration_y", td.AMBIENT_REF]) == ["vibration_x", "vibration_y"]
    assert ml.ambient_plan(["temperature", "humidity"]) is None
