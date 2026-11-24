"""
The sequential change detector (services/change_detector.py): a pure module, so these tests need no database.
A load switches between idle and running, a second sensor follows it with a lag and a third reads the same load. The
detector must expect the lagging sensor from the others and flag a step or a drift in it, stay under a boundary measured
the way production measures it on healthy readings, ignore a reading seen twice and handle gaps.
"""
import numpy as np
import pytest

from app.services import change_detector as cd
from app.services import ml_service as ml

INTERVAL = 10.0


def _data(n=6000, seed=0, interval=INTERVAL):
    rng = np.random.default_rng(seed)
    t = 1_700_000_000.0 + interval * np.arange(n)
    # a machine switching between idle and running. A second sensor that follows it with a lag
    x = np.where((np.arange(n) * interval // 6000) % 2 == 0, 0.1, 1.0) + rng.normal(0, 0.02, n)
    y = np.empty(n)
    y[0] = x[0]
    for i in range(1, n):
        y[i] = y[i - 1] + (1 - np.exp(-interval / 900.0)) * (x[i] - y[i - 1])
    y = 20.0 + 6.0 * y + rng.normal(0, 0.1, n)
    # a second instant sensor of the same load, so the load itself is predictable from the others
    z = 5.0 + 3.0 * (x - 0.1) + rng.normal(0, 0.02, n)
    return t, np.column_stack([x, y, z])


def _measured(det, seeds=(11, 12, 13)):
    """The boundary as ml_service sets it: the 1 in 1,000 quantile of healthy raw scores moved out by the margin."""
    raw = np.concatenate([cd.run(det, *_data(seed=s), INTERVAL) for s in seeds])
    det.typical = float(np.median(raw))
    top = float(np.quantile(raw, 0.999))
    det.boundary = max(top + ml.DETECTOR_MARGIN * (top - det.typical), ml.DETECTOR_MIN_BOUNDARY)
    return det


@pytest.fixture(scope="module")
def det():
    t, X = _data()
    return _measured(cd.fit(X, t, ["load", "temp", "load2"]))


def test_a_sensor_nothing_predicts_is_not_watched_and_one_the_others_explain_is():
    t, X = _data(seed=8)
    noise = np.random.default_rng(80).normal(0, 1.0, len(t))
    fitted = cd.fit(np.column_stack([X, noise]), t, ["load", "temp", "load2", "noise"])
    assert bool(fitted.active[3]) is False
    assert bool(fitted.active[1]) is True


def test_the_quiet_spread_is_read_from_steady_periods_and_not_inflated_by_transitions(det):
    # the lagging sensor's noise is 0.1 in its units. Its quiet spread must be close to that, while its residual during
    # a change of state is several times larger: the spread model carries that as slope
    sd_units = det.quiet_sd[1] * det.scale[1]
    assert 0.05 < sd_units < 0.2
    t, X = _data(seed=1)
    r = cd.residuals(det, t, X)[:, 1] * det.scale[1]
    assert np.percentile(np.abs(r), 99) > 2.0 * sd_units and det.slope[1] > 0.0


def test_healthy_readings_stay_under_the_measured_boundary(det):
    t, X = _data(seed=1)
    assert cd.run(det, t, X, INTERVAL).max() < det.boundary


def test_a_step_of_two_degrees_is_accumulated_past_the_boundary_and_blamed(det):
    t, X = _data(seed=2)
    X = X.copy()
    X[3000:, 1] += 2.0
    state = cd.DetectorState()
    raw = np.array([cd.step(det, state, t[i], X[i], INTERVAL) for i in range(len(t))])
    assert raw[:3000].max() < det.boundary
    crossed = int(np.argmax(raw[3000:] > det.boundary))
    assert raw[3000 + crossed] > det.boundary and crossed * INTERVAL <= 1800
    note = cd.explain(det, state, X[3000 + crossed], t[3000 + crossed])
    assert note["sensor"] == "temp" and note["direction"] == "above" and note["kind"] == "drift"


def test_the_stated_offset_of_a_step_is_close_to_the_true_one(det):
    t, X = _data(seed=2)
    X = X.copy()
    X[3000:, 1] += 2.0
    state = cd.DetectorState()
    for i in range(3000 + 90):
        cd.step(det, state, t[i], X[i], INTERVAL)
    note = cd.explain(det, state, X[3089], t[3089])
    assert 1.5 <= note["offset"] <= 2.6
    # the run began at the step, so the stated minutes are the time since it, within a few minutes
    assert abs(note["minutes"] - 15) <= 4


def test_a_slow_drift_is_caught_and_not_absorbed_before_it_is(det):
    t, X = _data(seed=3)
    X = X.copy()
    ramp = np.clip((np.arange(len(t)) - 2000) / 1800.0, 0, 1)
    X[:, 1] -= 4.0 * ramp
    raw = cd.run(det, t, X, INTERVAL)
    assert raw[:2000].max() < det.boundary
    assert raw[2000:3800].max() > det.boundary
    assert cd.explain(det, _last_state(det, t[:3000], X[:3000]), X[2999], t[2999])["direction"] == "below"


def _last_state(det, t, X):
    state = cd.DetectorState()
    for i in range(len(t)):
        cd.step(det, state, t[i], X[i], INTERVAL)
    return state


def test_accumulation_per_minute_does_not_depend_on_the_posting_interval(det):
    # the same fault seen every 10 s and every 60 s crosses the boundary within the same few minutes
    times = {}
    for interval in (10.0, 60.0):
        t, X = _data(seed=2)
        keep = np.arange(0, len(t), int(interval / INTERVAL))
        t, X = t[keep], X[keep].copy()
        onset = int(30000 / interval)
        X[onset:, 1] += 3.0
        raw = cd.run(det, t, X, interval)
        times[interval] = (t[onset + int(np.argmax(raw[onset:] > det.boundary))] - t[onset]) / 60.0
    assert abs(times[60.0] - times[10.0]) <= 3.0


def test_a_reading_seen_again_or_stamped_at_the_same_instant_adds_nothing(det):
    t, X = _data(seed=2)
    X = X.copy()
    X[3000:, 1] += 3.0
    state = cd.DetectorState()
    for i in range(3100):
        cd.step(det, state, t[i], X[i], INTERVAL)
    before = (state.s_pos.copy(), state.last_t, state.steps)
    # a retried transaction steps the same reading again and a batch stamps 50 readings within microseconds
    cd.step(det, state, t[3099], X[3099], INTERVAL)
    for k in range(50):
        cd.step(det, state, t[3099] + 1e-6 * k, X[3099], INTERVAL)
    assert np.allclose(state.s_pos[1], before[0][1], atol=0.05) and state.steps <= before[2] + 50


def test_a_short_gap_carries_the_state_and_a_long_one_holds_it_through_a_warm_up(det):
    t, X = _data(seed=4)
    X = X.copy()
    X[3000:, 1] += 3.0
    state = cd.DetectorState()
    for i in range(3300):
        cd.step(det, state, t[i], X[i], INTERVAL)
    held = max(state.s_pos.max(), state.s_neg.max())
    assert held > det.boundary
    # a radio outage of two minutes is not a silence: the run goes on
    assert cd.step(det, state, t[3300] + 120.0, X[3300], INTERVAL) >= held
    held = max(state.s_pos.max(), state.s_neg.max())
    # ten minutes is: the smoothed views start again and nothing accumulates during the warm up, but the evidence of the
    # fault is held, so an open alert is not read as calm while the detector cannot see
    later = t[3300] + 120.0 + 600.0
    assert cd.step(det, state, later, X[3301], INTERVAL) == pytest.approx(held)
    assert state.warm_from == later
    assert cd.step(det, state, later + cd.WARMUP_S - 60.0, X[3302], INTERVAL) == pytest.approx(held)
    # after the warm up the fault, still there, accumulates again
    out = 0.0
    for k in range(1, 400):
        out = cd.step(det, state, later + cd.WARMUP_S + 10 * k, X[3302 + k], INTERVAL)
    assert out > held


def test_a_fault_that_ends_clears_within_about_half_an_hour_once_the_boundary_is_measured(det):
    import copy
    measured = copy.deepcopy(det)
    measured.extra["measured"] = True
    t, X = _data(seed=4)
    X = X.copy()
    X[3000:4000, 1] += 5.0
    raw = cd.run(measured, t, X, INTERVAL)
    assert raw[3000:4000].max() <= cd.CAP_BOUNDARIES * measured.boundary + 1e-9
    below = int(np.argmax(raw[4000:] < measured.boundary))
    assert raw[4000 + below] < measured.boundary and below * INTERVAL <= 2400


def test_the_level_follows_a_slow_change_within_its_bound_and_no_further(det):
    t, X = _data(n=20000, seed=6)
    X = X.copy()
    # the room warms by 0.3 degrees an hour for the whole run
    X[:, 1] += 0.3 * (t - t[0]) / 3600.0
    state = cd.DetectorState()
    for i in range(len(t)):
        cd.step(det, state, t[i], X[i], INTERVAL)
    assert abs(state.level[1]) == pytest.approx(det.level_bound[1], rel=1e-6)


def test_one_reading_adds_at_most_the_cap_times_its_minutes(det):
    t, X = _data(seed=6)
    state = cd.DetectorState()
    for i in range(1500):
        cd.step(det, state, t[i], X[i], INTERVAL)
    knock = X[1500].copy()
    knock[1] += 1000.0
    before = max(state.s_pos.max(), state.s_neg.max())
    cd.step(det, state, t[1500], knock, INTERVAL)
    assert max(state.s_pos.max(), state.s_neg.max()) <= before + (cd.Z_CAP - cd.ALLOWANCE) * INTERVAL / 60.0 + 1e-9


def test_the_state_round_trips_through_a_dict_for_a_database_store(det):
    t, X = _data(seed=7)
    state = _last_state(det, t[:1500], X[:1500])
    state.model_id = "abc"
    back = cd.DetectorState.from_dict(state.to_dict())
    assert np.allclose(back.smooth, state.smooth) and back.last_t == state.last_t and back.model_id == "abc"
    assert np.allclose(back.level, state.level) and back.steps == state.steps
    nxt = cd.step(det, back, t[1500], X[1500], INTERVAL)
    assert nxt == pytest.approx(cd.step(det, state, t[1500], X[1500], INTERVAL))


def test_the_memory_store_keeps_a_state_per_machine():
    store = cd.MemoryStateStore()
    assert store.get("a") is None
    s = cd.DetectorState(last_t=5.0)
    store.put("a", s)
    assert store.get("a") is s and store.get("b") is None
    store.clear()
    assert store.get("a") is None


def test_normalise_maps_typical_to_zero_and_the_boundary_to_the_threshold(det):
    det = cd.Detector(det.cols, det.center, det.scale, det.coef, det.quiet_sd, det.slope, det.active, det.level_bound,
                      boundary=20.0, typical=0.0)
    out = cd.normalise(det, np.array([0.0, 10.0, 20.0, 40.0, 1000.0]))
    assert out[0] == 0.0 and out[1] == pytest.approx(0.35) and out[2] == pytest.approx(0.7)
    assert out[3] == pytest.approx(0.85) and out[4] == 1.0


def test_the_daily_profile_has_four_terms_and_repeats_each_day():
    a = cd.time_of_day(1_700_000_000.0)
    assert a.shape == (4,)
    assert np.allclose(a, cd.time_of_day(1_700_000_000.0 + 86400.0))
