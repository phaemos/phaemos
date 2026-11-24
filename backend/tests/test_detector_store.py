"""
The change detector's state kept on the device row: shared by workers (two separate processes below), reset by a long gap,
cleared by a retrain, a counter accept and a key rotation, bounded, paused in a maintenance window, never stepped twice by
a retried transaction or by a batch stamped at one instant and never a 500 when what is stored is damaged.
"""

import logging

import numpy as np
import pytest

from app.models.telemetry import Telemetry
from app.services import change_detector as cd
from app.services import detector_store, ml_service
from tests.test_change_detector import INTERVAL, _data

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture(scope="module")
def det():
    t, X = _data()
    return cd.fit(X, t, ["load", "temp", "load2"])


def _step(db, device, store, det, t, x):
    """One reading as an ingest post does it: read the state, step it, write it and the next reader sees the database."""
    with detector_store.use(db):
        state = store.get(str(device.id)) or cd.DetectorState()
        raw = cd.step(det, state, t, x, INTERVAL)
        store.put(str(device.id), state)
    db.flush()
    # whoever reads next reads the stored column and not an object in this process
    db.expire(device)
    return raw


def test_two_workers_alternating_on_one_machine_give_the_same_accumulator_as_one(db, device, det):
    t, X = _data(seed=3)
    X = X.copy()
    X[2000:, 1] += 3.0
    one = cd.DetectorState()
    for i in range(2400):
        cd.step(det, one, t[i], X[i], INTERVAL)
    # two workers, each with its own store object, take the readings in turn
    workers = [detector_store.DbStateStore(), detector_store.DbStateStore()]
    for i in range(2400):
        _step(db, device, workers[i % 2], det, t[i], X[i])
    with detector_store.use(db):
        shared = workers[0].get(str(device.id))
    assert np.allclose(shared.s_pos, one.s_pos) and np.allclose(shared.s_neg, one.s_neg)
    assert max(shared.s_pos.max(), shared.s_neg.max()) > 25.0


def test_a_long_gap_restarts_the_stored_state_as_the_detectors_own_rule_says(db, device, det):
    t, X = _data(seed=4)
    X = X.copy()
    X[3000:, 1] += 3.0
    store = detector_store.DbStateStore()
    for i in range(3300):
        _step(db, device, store, det, t[i], X[i])
    with detector_store.use(db):
        assert max(store.get(str(device.id)).s_pos.max(), store.get(str(device.id)).s_neg.max()) > 25.0
    with detector_store.use(db):
        held = store.get(str(device.id))
    later = t[3300] + cd.RESET_GAP_S + 10 * INTERVAL
    # a long silence restarts the smoothed views and its warm up from the stored state and holds the evidence
    assert _step(db, device, store, det, later, X[3300]) == pytest.approx(max(held.s_pos.max(), held.s_neg.max()))
    with detector_store.use(db):
        after = store.get(str(device.id))
    assert after.warm_from == later and np.allclose(after.s_pos, held.s_pos)


def test_the_state_is_about_a_kilobyte_and_round_trips_through_the_column(db, device, det):
    t, X = _data()
    store = detector_store.DbStateStore()
    for i in range(50):
        _step(db, device, store, det, t[i], X[i])
    import json
    assert len(json.dumps(device.detector_state)) < detector_store.MAX_BYTES


def test_without_a_session_the_store_falls_back_to_memory(device):
    store = detector_store.DbStateStore()
    state = cd.DetectorState()
    state.last_t = 5.0
    store.put(str(device.id), state)
    assert store.get(str(device.id)).last_t == 5.0
    assert device.detector_state is None


@pytest.mark.parametrize("damaged", [
    {"smooth": "garbage"}, "not a dict", {"smooth": [[1.0]] * 5000}, {"last_t": "soon"},
])
def test_a_damaged_stored_state_is_refused_replaced_and_logged_and_never_raises(db, device, caplog, damaged):
    device.detector_state = damaged
    db.flush()
    store = detector_store.DbStateStore()
    with caplog.at_level(logging.WARNING), detector_store.use(db):
        assert store.get(str(device.id)) is None
    assert device.detector_state is None
    assert "refused and replaced" in caplog.text


def test_an_oversized_state_is_not_stored(db, device):
    state = cd.DetectorState(smooth=np.zeros((2, 2000)))
    with detector_store.use(db):
        detector_store.DbStateStore().put(str(device.id), state)
    assert device.detector_state is None


def test_a_post_with_a_damaged_state_on_the_machine_still_answers_201(client, db, device):
    device.detector_state = {"smooth": "garbage"}
    db.flush()
    res = client.post("/api/v1/telemetry", json={"temperature": 20.0}, headers={"X-API-Key": device.api_key})
    assert res.status_code == 201


def test_a_retrain_clears_every_machines_state(db, device):
    device.detector_state = {"last_t": 1.0}
    db.flush()
    assert detector_store.clear_all(db) >= 1
    db.refresh(device)
    assert device.detector_state is None


def test_accepting_a_counter_and_rotating_the_key_clear_the_state(client, db, device, auth_headers):
    device.detector_state = {"last_t": 1.0}
    db.flush()
    assert client.post(f"/api/v1/devices/{device.id}/accept-counter", headers=auth_headers).status_code == 200
    db.refresh(device)
    assert device.detector_state is None
    device.detector_state = {"last_t": 1.0}
    db.flush()
    assert client.post(f"/api/v1/devices/{device.id}/rotate-key", json={"password": "Admin1234!"}, headers=auth_headers).status_code == 200
    db.refresh(device)
    assert device.detector_state is None


def test_a_backlog_reading_never_reaches_the_scorer(client, db, device, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.routes import telemetry as route

    calls = []
    monkeypatch.setattr(route, "score_reading", lambda *a, **k: calls.append(k) or (0.1, False))
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    client.post("/api/v1/telemetry/batch", json={"readings": [{"temperature": 20.0, "observed_at": old.isoformat()}] * 3 + [{"temperature": 20.0}]},
                headers={"X-API-Key": device.api_key})
    # only the live reading was scored and at its own time
    assert len(calls) == 1 and calls[0]["device_id"] == device.id and calls[0]["at"] is not None
    assert db.query(Telemetry).filter(Telemetry.device_id == device.id).count() == 4


def test_the_store_is_installed_for_the_scorer_and_keeps_memory_as_its_fallback():
    store = ml_service.state_store()
    assert isinstance(store, detector_store.DbStateStore)
    assert isinstance(store.fallback, cd.MemoryStateStore)


# -- two processes, one machine -------------------------------------------------------------------------------------------

TOTAL = 400


def _worker(device_id: str, url: str, out) -> None:
    """One API worker in a process of its own: lock the device row, step the stored state once, commit, until done."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.main  # noqa: F401  (registers every model, so the device's relationships resolve in a fresh process)
    from app.models.device import Device as DeviceRow

    t, X = _data(seed=3)
    X = X.copy()
    X[200:, 1] += 3.0
    t0, X0 = _data()
    det = cd.fit(X0, t0, ["load", "temp", "load2"])
    engine = create_engine(url)
    session = sessionmaker(bind=engine)()
    store = detector_store.DbStateStore()
    mine = 0
    try:
        while True:
            # the row lock the ingest post takes (routes/telemetry.py _lock_device): the device row only
            row = session.query(DeviceRow).filter(DeviceRow.id == device_id).with_for_update(of=DeviceRow).one()
            with detector_store.use(session):
                state = store.get(device_id) or cd.DetectorState()
                i = state.steps
                if i >= TOTAL:
                    session.commit()
                    break
                cd.step(det, state, float(t[i]), X[i], INTERVAL)
                store.put(device_id, state)
            del row
            session.commit()
            mine += 1
    finally:
        session.close()
        engine.dispose()
    out.put(mine)


def test_two_processes_share_one_machines_state_without_splitting_or_resetting_it(det):
    import multiprocessing
    import os

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from app.models.device import Device as DeviceRow

    url = os.environ["DATABASE_URL"]
    engine = create_engine(url)
    session = sessionmaker(bind=engine)()
    row = DeviceRow(name="two-process test", type="esp32", api_key="two-process-" + os.urandom(8).hex())
    session.add(row)
    session.commit()
    device_id = str(row.id)
    try:
        ctx = multiprocessing.get_context("spawn")
        out = ctx.Queue()
        workers = [ctx.Process(target=_worker, args=(device_id, url, out)) for _ in range(2)]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=300)
        counts = [out.get(timeout=5) for _ in workers]
        session.expire_all()
        stored = cd.DetectorState.from_dict(session.get(DeviceRow, row.id).detector_state)
        # both processes did real work and every reading stepped the one shared state exactly once
        assert all(c > 0 for c in counts) and sum(counts) == TOTAL and stored.steps == TOTAL
        t, X = _data(seed=3)
        X = X.copy()
        X[200:, 1] += 3.0
        one = cd.DetectorState()
        for i in range(TOTAL):
            cd.step(det, one, float(t[i]), X[i], INTERVAL)
        assert np.allclose(stored.s_pos, one.s_pos) and np.allclose(stored.s_neg, one.s_neg)
        assert np.allclose(stored.level, one.level) and stored.last_t == one.last_t
    finally:
        session.execute(text("DELETE FROM devices WHERE id = :id"), {"id": row.id})
        session.commit()
        session.close()
        engine.dispose()


# -- the time a reading is scored at --------------------------------------------------------------------------------------

class _StandIn:
    """A machine model with only a detector, scored through the real score_reading. Module level so it pickles."""

    offset_ = -0.5
    phaemos_typical_decision = 1.0
    phaemos_has_forest = False

    def __init__(self, det):
        self.phaemos_features = ["temperature", "current_ma", "humidity"]
        self.phaemos_schema = ml_service.SCHEMA_VERSION
        self.phaemos_detector = det
        self.phaemos_id = "stand-in"
        self.phaemos_interval_s = INTERVAL

    def score_samples(self, X):
        return np.full(len(X), 0.5)


@pytest.fixture
def scored_machine(device, det, monkeypatch):
    import copy
    detector = copy.deepcopy(det)
    detector.cols = ["temperature", "current_ma", "humidity"]
    detector.boundary, detector.typical = 20.0, 0.0
    bundle = {f"machine:{device.id}": _StandIn(detector), ml_service.META_KEY: {"machines": {}}}
    monkeypatch.setattr(ml_service, "_model", bundle)
    monkeypatch.setattr(ml_service, "_load_model", lambda: None)
    monkeypatch.setattr(ml_service, "_maybe_reload", lambda: None)
    monkeypatch.setattr(ml_service, "_problem", None)
    return device


def _reading(i, X, hot=0.0):
    return {"temperature": float(X[i, 0]), "current_ma": float(X[i, 1]) + hot, "humidity": float(X[i, 2])}


def test_a_batch_stamped_at_one_instant_does_not_accumulate(db, scored_machine):
    from datetime import datetime, timedelta, timezone
    t, X = _data(seed=5)
    store = detector_store.DbStateStore()
    start = datetime.now(timezone.utc) - timedelta(seconds=INTERVAL * 2000)
    with detector_store.use(db):
        for i in range(1000):
            ml_service.score_reading(_reading(i, X), device_id=scored_machine.id, at=start + timedelta(seconds=INTERVAL * i))
        # fifty readings far out of line, stamped a microsecond apart as a batch without observed_at is. The first of them
        # comes an interval after the last reading and counts as one reading. The other 49 must add nothing
        moment = start + timedelta(seconds=INTERVAL * 1000)
        ml_service.score_reading(_reading(1000, X, hot=50.0), device_id=scored_machine.id, at=moment)
        before = store.get(str(scored_machine.id))
        for k in range(1, 50):
            ml_service.score_reading(_reading(1000, X, hot=50.0), device_id=scored_machine.id,
                                     at=moment + timedelta(microseconds=k))
        after = store.get(str(scored_machine.id))
    assert np.allclose(after.s_pos, before.s_pos, atol=0.01) and np.allclose(after.s_neg, before.s_neg, atol=0.01)


def test_a_retried_transaction_steps_the_detector_once(db, scored_machine):
    from datetime import datetime, timedelta, timezone
    t, X = _data(seed=5)
    start = datetime.now(timezone.utc) - timedelta(seconds=INTERVAL * 2000)
    with detector_store.use(db):
        for i in range(300):
            ml_service.score_reading(_reading(i, X), device_id=scored_machine.id, at=start + timedelta(seconds=INTERVAL * i))
    db.flush()
    steps = cd.DetectorState.from_dict(scored_machine.detector_state).steps
    moment = start + timedelta(seconds=INTERVAL * 300)
    # the first attempt scores the reading and is rolled back (a deadlock), the second runs again
    nested = db.begin_nested()
    with detector_store.use(db):
        ml_service.score_reading(_reading(300, X), device_id=scored_machine.id, at=moment)
    db.flush()
    nested.rollback()
    db.expire(scored_machine)
    assert cd.DetectorState.from_dict(scored_machine.detector_state).steps == steps
    with detector_store.use(db):
        ml_service.score_reading(_reading(300, X), device_id=scored_machine.id, at=moment)
        # and the same reading scored a second time in one transaction moves nothing
        ml_service.score_reading(_reading(300, X), device_id=scored_machine.id, at=moment)
    db.flush()
    assert cd.DetectorState.from_dict(scored_machine.detector_state).steps == steps + 1


def test_a_maintenance_window_pauses_the_detector_and_its_end_starts_a_warm_up(db, scored_machine):
    from datetime import datetime, timedelta, timezone

    from app.models.maintenance import MaintenanceWindow

    t, X = _data(seed=5)
    start = datetime.now(timezone.utc) - timedelta(seconds=INTERVAL * 3000)
    db.add(MaintenanceWindow(device_id=scored_machine.id, label="service", start_at=start + timedelta(seconds=INTERVAL * 1000),
                             end_at=start + timedelta(seconds=INTERVAL * 1500)))
    db.flush()
    store = detector_store.DbStateStore()
    with detector_store.use(db):
        for i in range(1000):
            ml_service.score_reading(_reading(i, X), device_id=scored_machine.id, at=start + timedelta(seconds=INTERVAL * i))
        steps = store.get(str(scored_machine.id)).steps
        # the machine is worked on: readings far out of line, which the detector must not accumulate
        for i in range(1000, 1500):
            ml_service.score_reading(_reading(i, X, hot=80.0), device_id=scored_machine.id,
                                     at=start + timedelta(seconds=INTERVAL * i))
        paused = store.get(str(scored_machine.id))
        assert paused.steps == steps and paused.s_pos is None
        # the first reading after the window starts a fresh run with its warm up: nothing carried from the window
        ml_service.score_reading(_reading(1501, X), device_id=scored_machine.id, at=start + timedelta(seconds=INTERVAL * 1501))
        after = store.get(str(scored_machine.id))
    assert after.s_pos.max() == 0.0 and after.warm_from == pytest.approx((start + timedelta(seconds=INTERVAL * 1501)).timestamp())


def test_a_live_reading_is_scored_at_its_own_time_and_not_the_servers(client, db, device, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.routes import telemetry as route

    calls = []
    monkeypatch.setattr(route, "score_reading", lambda *a, **k: calls.append(k) or (0.1, False))
    taken = datetime.now(timezone.utc) - timedelta(seconds=20)
    res = client.post("/api/v1/telemetry", json={"temperature": 20.0, "observed_at": taken.isoformat()},
                      headers={"X-API-Key": device.api_key})
    assert res.status_code == 201
    # 20 s old is still live, so it is scored and at the moment it was taken
    assert len(calls) == 1 and abs((calls[0]["at"] - taken).total_seconds()) < 0.01
