"""
The alerting path under load and under failure: the request's database session is closed before notifications run,
a model that cannot be loaded never costs a reading, one open alert of a kind per device, the ingest limit and the
bounds on what a node can make the backend remember.
"""

import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import SessionLocal, engine, get_db
from app.main import app
from app.models.alert import Alert, AlertRule
from app.models.device import Device
from app.models.device_health import DeviceHealth
from app.models.maintenance import MaintenanceWindow
from app.models.telemetry import Telemetry
from app.schemas.telemetry import TelemetryIngest
from app.services import (
    alert_service, cooldown, health_service, ingest_limit, liveness_service, ml_service, notify_service, sensor_map,
    webhook_service,
)
from tests.test_alert_notifications import FakeRedis

T0 = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _at(seconds):
    return T0 + timedelta(seconds=seconds)


def _post(client, device, expect=201, **fields):
    res = client.post(
        "/api/v1/telemetry", json={"device_id": str(device.id), **fields}, headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == expect, res.text
    return res.json()


def _seen(db, device, seconds, **faults):
    payload = TelemetryIngest(device_id=str(device.id), faults=faults)
    return health_service.record_health(db, device, payload, _at(seconds))


@pytest.fixture
def store(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(cooldown, "_client", lambda: fake)
    cooldown._local.clear()
    cooldown._local_daily.clear()
    yield fake
    cooldown._local.clear()
    cooldown._local_daily.clear()


@pytest.fixture
def sent(monkeypatch, store):
    log = {"email": [], "sms": []}
    monkeypatch.setattr(notify_service, "send_email_alert", lambda **k: log["email"].append(k) or True)
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    return log


@pytest.fixture
def clean_model(monkeypatch, tmp_path):
    # a model file of the test's own and none of another test's state
    path = tmp_path / "model.pkl"
    monkeypatch.setattr(ml_service, "MODEL_PATH", str(path))
    monkeypatch.setattr(ml_service, "_model", None)
    monkeypatch.setattr(ml_service, "_problem", None)
    monkeypatch.setattr(ml_service, "_load_failure", None)
    monkeypatch.setattr(ml_service, "_logged", set())
    return path


# -- H1: no connection is held while a notification is in flight ------------------------------------------

def test_the_session_is_closed_before_the_notifications_run(client, db, device, sent, monkeypatch):
    events = []

    def watched_db():
        events.append("open")
        try:
            yield db
        finally:
            events.append("closed")

    app.dependency_overrides[get_db] = watched_db
    monkeypatch.setattr(notify_service, "send_email_alert", lambda **k: events.append("notified") or True)
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric="temperature", condition="gt", threshold=50.0, severity="warning"))
    db.flush()
    _post(client, device, temperature=99.0)
    # the email was sent and only after the session had been closed
    assert "notified" in events
    assert events.index("closed") < events.index("notified")
    assert events == ["open", "closed", "notified"]


def test_no_pool_connection_is_checked_out_while_a_notification_is_in_flight(monkeypatch, store):
    # the real application session and pool, as a hung webhook endpoint would find them
    seen = []
    monkeypatch.setattr(webhook_service, "deliver_all", lambda targets, alert_context: seen.append(engine.pool.checkedout()) or True)
    monkeypatch.setattr(notify_service, "send_email_alert", lambda **k: seen.append(engine.pool.checkedout()) or True)
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    from app.models.webhook import Webhook

    setup = SessionLocal()
    device = Device(name=f"pool-{secrets.token_hex(3)}", api_key=secrets.token_urlsafe(16), link_state="online")
    setup.add(device)
    setup.flush()
    setup.add(AlertRule(for_seconds=0, device_id=device.id, metric="temperature", condition="gt", threshold=50.0, severity="warning"))
    hook = Webhook(name="slow", url="https://hooks.example.com/x", enabled=True)
    setup.add(hook)
    setup.commit()
    device_id, key, hook_id = device.id, device.api_key, hook.id
    setup.close()
    try:
        with TestClient(app) as raw:
            res = raw.post("/api/v1/telemetry", json={"device_id": str(device_id), "temperature": 99.0}, headers={"X-API-Key": key})
        assert res.status_code == 201
        # both vendor calls ran and neither found a connection checked out
        assert len(seen) == 2
        assert seen == [0, 0]
    finally:
        cleanup = SessionLocal()
        cleanup.execute(text("DELETE FROM webhooks WHERE id = CAST(:i AS uuid)"), {"i": str(hook_id)})
        cleanup.execute(text("DELETE FROM devices WHERE id = CAST(:i AS uuid)"), {"i": str(device_id)})
        cleanup.commit()
        cleanup.close()


def test_the_post_that_queues_notifications_is_the_only_route_with_that_job():
    # the other background task in the API (a retrain) opens its own short session and holds none from the request
    import inspect
    from app.routes import ml, telemetry, webhooks

    assert 'scope="function"' in inspect.getsource(telemetry.ingest_telemetry)
    from app.tasks import model_retrain
    assert "SessionLocal()" in inspect.getsource(model_retrain._audit) and "SessionLocal()" in inspect.getsource(model_retrain.fleet)
    assert "background_tasks.add_task(model_retrain.run_retrain" in inspect.getsource(ml.retrain)
    # the webhook test route has no session of its own for a task either: it queues nothing that reads one
    assert "db." not in inspect.getsource(webhooks.test_webhook_route) if hasattr(webhooks, "test_webhook_route") else True


# -- M5: a model that cannot be used never costs a reading ------------------------------------------------

def test_a_corrupt_model_file_leaves_the_reading_stored_and_unscored(client, db, device, clean_model):
    clean_model.write_bytes(b"this is not a pickle")
    body = _post(client, device, temperature=21.0, humidity=40.0)
    assert body["temperature"] == 21.0 and body["anomaly_score"] is None and body["is_anomaly"] is False
    assert body["quality"]["scoring_error"] == f"the model file could not be loaded ({ml_service.UNSIGNED_REASON})"
    assert list(body["quality"]) == ["scoring_error"]
    assert db.query(Telemetry).filter(Telemetry.device_id == device.id).count() == 1


def test_a_load_failure_is_logged_once_and_not_per_post(client, device, clean_model, caplog):
    clean_model.write_bytes(b"garbage")
    with caplog.at_level("ERROR"):
        for _ in range(5):
            _post(client, device, temperature=21.0)
    assert caplog.text.count("the model file could not be loaded") == 1


_BUNDLE = []


def _trained_bundle():
    """A real bundle made by the training functions (services/ml_service.train_bundle) from synthetic clean readings."""
    if not _BUNDLE:
        import numpy as np
        from app.services import model_evaluation as ev, training_data as td
        rng = np.random.default_rng(3)
        cols = len(td.SENSOR_COLS)

        def block(n):
            X = np.full((n, cols), np.nan)
            X[:, 0] = 20 + rng.normal(0, 1, n)
            X[:, 1] = 50 + rng.normal(0, 3, n)
            return X

        held = block(2500)
        # a validation part and a test part of more than a day after it
        test_times = 1_700_025_000.0 + 10.0 * np.arange(9000)
        data = td.MachineData("m1", "m1", "esp32", 10.0, block(3000), held, 1_700_000_000.0 + 10.0 * np.arange(2500),
                              block(9000), test_times, clean_rows=20000, clean_hours=55.0, span_hours=60.0)
        patch = pytest.MonkeyPatch()
        # the detection check is not what these tests are about
        patch.setattr(ev, "MAX_MISSED_SHARE", 1.0)
        try:
            outcome = ml_service.train_bundle([data], {"esp32": 1}, 1)
        finally:
            patch.undo()
        assert outcome.bundle is not None
        _BUNDLE.append(outcome.bundle)
    return _BUNDLE[0]


def test_a_failed_file_is_not_read_again_until_it_changes(clean_model, monkeypatch):
    clean_model.write_bytes(b"garbage")
    calls = []
    real = ml_service.joblib.load
    monkeypatch.setattr(ml_service.joblib, "load", lambda path: calls.append(path) or real(path))
    for _ in range(4):
        assert ml_service.score_reading({"temperature": 1.0}) == (None, False)
    # an unsigned file is refused on its bytes and never handed to the unpickler at all
    assert len(calls) == 0
    bundle = _trained_bundle()
    ml_service.save_model(bundle)
    os.utime(clean_model, (time.time() + 5, time.time() + 5))
    score, _ = ml_service.score_reading({"node_type": "esp32", "temperature": 21.0, "humidity": 51.0})
    assert score is not None and ml_service.scoring_problem() is None


def test_a_model_that_fails_while_scoring_is_a_null_score_and_not_an_error(client, db, device, clean_model, monkeypatch):
    class _Breaks:
        phaemos_features = ["temperature"]
        phaemos_schema = ml_service.SCHEMA_VERSION

        def score_samples(self, X):
            raise RuntimeError("shape mismatch")

    monkeypatch.setattr(ml_service, "_model", {"default": _Breaks()})
    body = _post(client, device, temperature=21.0)
    assert body["anomaly_score"] is None
    assert body["quality"] == {"scoring_error": "scoring failed (RuntimeError)"}


def test_the_no_scored_reading_alert_says_the_model_could_not_be_used(db, device, clean_model):
    clean_model.write_bytes(b"garbage")
    ml_service.score_reading({"temperature": 1.0})
    health_service.track_scoring(db, device, {"temperature": 1.0}, False, _at(0))
    note = health_service.track_scoring(db, device, {"temperature": 1.0}, False, _at(600))
    assert note[0] == "unscored"
    assert "the model could not be used (the model file could not be loaded (" in note[1]


def test_the_previous_model_file_is_the_fallback(clean_model):
    bundle = _trained_bundle()
    ml_service.save_model(bundle)
    ml_service.save_model(bundle)
    previous = Path(str(clean_model) + ".prev")
    assert previous.exists()
    clean_model.write_bytes(b"truncated")
    ml_service._model = None
    score, _ = ml_service.score_reading({"node_type": "esp32", "temperature": 21.0, "humidity": 51.0})
    assert score is not None
    assert ml_service.scoring_problem() is None


def test_the_model_file_is_written_atomically(clean_model, monkeypatch):
    bundle = _trained_bundle()
    ml_service.save_model(bundle)
    good = clean_model.read_bytes()

    def dies_half_way(obj, handle):
        handle.write(b"half")
        raise OSError("disk full")

    monkeypatch.setattr(ml_service.joblib, "dump", dies_half_way)
    with pytest.raises(OSError):
        ml_service.save_model(bundle)
    # the file in place is untouched and no temporary file is left behind
    assert clean_model.read_bytes() == good
    assert [p.name for p in clean_model.parent.iterdir() if p.name.startswith(".model-")] == []


def test_a_broken_file_in_place_does_not_replace_the_good_previous_copy(clean_model):
    bundle = _trained_bundle()
    ml_service.save_model(bundle)
    ml_service.save_model(bundle)
    previous = Path(str(clean_model) + ".prev")
    good_copy = previous.read_bytes()
    clean_model.write_bytes(b"broken")
    ml_service.save_model(bundle)
    assert previous.read_bytes() == good_copy


def test_the_status_reports_the_model_state(client, clean_model):
    assert client.get("/status").json()["model"] == "none"
    clean_model.write_bytes(b"garbage")
    assert client.get("/status").json()["model"] == "error"


def test_deploy_fails_when_the_status_says_the_model_is_in_error():
    script = (Path(__file__).resolve().parents[2] / "infra" / "scripts" / "deploy.sh")
    if not script.exists():
        pytest.skip("infra/ is not in this container")
    text_ = script.read_text()
    assert '"model":"error"' in text_ and "fail " in text_[text_.index('"model":"error"'):][:400]


# -- M6: what a node can make the backend remember ---------------------------------------------------------

def test_new_sensor_keys_in_every_post_do_not_grow_the_tracking_record(db, device):
    for step in range(60):
        faults = {f"bogus{step}_{i}": "missing" for i in range(sensor_map.MAX_FAULT_ENTRIES)}
        _seen(db, device, step * 5, **faults)
    track = db.get(DeviceHealth, device.id).sensor_track
    unknown = [k for k in track if k not in sensor_map.SENSOR_FIELDS]
    assert len(unknown) <= health_service.MAX_UNKNOWN_TRACKED
    assert len(track) <= health_service.MAX_UNKNOWN_TRACKED + len(sensor_map.SENSOR_FIELDS)
    # the unknown keys are still shown in the latest faults
    assert len(db.get(DeviceHealth, device.id).faults) == sensor_map.MAX_FAULT_ENTRIES


def test_a_known_sensor_that_flaps_keeps_a_bounded_list(db, device):
    for step in range(200):
        _seen(db, device, step * 5, **({"bme280": "missing"} if step % 2 == 0 else {}))
    flips = db.get(DeviceHealth, device.id).sensor_track["bme280"]["flips"]
    assert len(flips) <= health_service.MAX_FLIPS_KEPT
    assert len(flips) > health_service.FLAP_LIMIT


def test_a_device_may_post_sixty_times_a_minute_and_no_more(client, db, device, monkeypatch):
    # the fastest healthy node posts every 2 seconds, which is 30 a minute. The limit is twice that
    assert ingest_limit.MAX_POSTS == 60 and ingest_limit.WINDOW_SECONDS == 60
    assert 60 >= 2 * (60 // 2)
    monkeypatch.setattr(ingest_limit, "MAX_POSTS", 4)
    for _ in range(4):
        _post(client, device, temperature=20.0)
    res = client.post(
        "/api/v1/telemetry", json={"device_id": str(device.id), "temperature": 20.0}, headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == 429
    wait = int(res.headers["Retry-After"])
    assert 1 <= wait <= 60
    # the refused post stored nothing
    assert db.query(Telemetry).filter(Telemetry.device_id == device.id).count() == 4


def test_the_limit_is_per_device(client, db, device, monkeypatch):
    other = Device(name="other", api_key=secrets.token_urlsafe(16))
    db.add(other)
    db.flush()
    monkeypatch.setattr(ingest_limit, "MAX_POSTS", 2)
    for _ in range(2):
        _post(client, device, temperature=20.0)
    _post(client, device, expect=429, temperature=20.0)
    _post(client, other, temperature=20.0)


def test_the_window_slides(client, device, monkeypatch):
    clock = [1000.0]
    # only this module's clock is replaced, not the time module everything else shares
    monkeypatch.setattr(ingest_limit, "time", type("Clock", (), {"monotonic": staticmethod(lambda: clock[0])}))
    monkeypatch.setattr(ingest_limit, "MAX_POSTS", 2)
    _post(client, device, temperature=20.0)
    _post(client, device, temperature=20.0)
    _post(client, device, expect=429, temperature=20.0)
    clock[0] += 61
    _post(client, device, temperature=20.0)


def test_a_wrong_key_is_not_counted_against_a_device(client, device, monkeypatch):
    monkeypatch.setattr(ingest_limit, "MAX_POSTS", 1)
    client.post("/api/v1/telemetry", json={"device_id": str(device.id)}, headers={"X-API-Key": "wrong"})
    _post(client, device, temperature=20.0)


def test_a_healthy_node_at_its_fastest_interval_never_meets_the_limit(client, device):
    for _ in range(30):
        _post(client, device, temperature=20.0)


# -- M8: one open alert of a kind per device and a reading is never lost to a race ----------------------------

def _open_alert(db, device, kind="sensor", sensor_key="bme280", category="monitoring", resolved=False, message="x"):
    alert = Alert(
        device_id=device.id, message=message, severity="warning", resolved=resolved, category=category,
        sensor_key=sensor_key, kind=kind,
    )
    db.add(alert)
    return alert


def test_the_database_refuses_a_second_open_alert_of_the_same_kind_and_sensor(db, device):
    _open_alert(db, device)
    db.flush()
    _open_alert(db, device)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_other_sensors_other_kinds_resolved_alerts_and_rule_alerts_are_not_limited(db, device):
    _open_alert(db, device, sensor_key="bme280")
    _open_alert(db, device, sensor_key="ldr")
    _open_alert(db, device, kind="offline", sensor_key=None)
    _open_alert(db, device, kind="reset_loop", sensor_key=None)
    _open_alert(db, device, kind="unscored", sensor_key=None)
    _open_alert(db, device, sensor_key="bme280", resolved=True)
    _open_alert(db, device, sensor_key="bme280", resolved=True)
    # rule and model alerts have no kind and are written once for every breaching reading
    for _ in range(3):
        _open_alert(db, device, kind=None, sensor_key=None, category="machine")
    db.flush()


def test_add_alert_returns_false_for_a_duplicate_and_leaves_the_rest_of_the_transaction_alone(db, device):
    assert health_service.add_alert(db, Alert(
        device_id=device.id, message="a", severity="warning", resolved=False, category="monitoring", sensor_key="x", kind="sensor",
    )) is True
    db.add(Telemetry(device_id=device.id, temperature=1.0, recorded_at=datetime.now(timezone.utc)))
    assert health_service.add_alert(db, Alert(
        device_id=device.id, message="b", severity="warning", resolved=False, category="monitoring", sensor_key="x", kind="sensor",
    )) is False
    db.flush()
    assert db.query(Telemetry).filter(Telemetry.device_id == device.id).count() == 1
    assert db.query(Alert).filter(Alert.device_id == device.id).count() == 1


def test_a_post_that_loses_the_race_for_a_fault_alert_still_stores_the_reading(client, db, device, monkeypatch):
    monkeypatch.setattr(health_service, "FAULT_ALERT_AFTER_S", 0)
    # the other post has already opened the alert and this one's check does not see it
    _open_alert(db, device)
    db.flush()
    monkeypatch.setattr(health_service, "_open_sensor_alert", lambda *a, **k: None)
    body = _post(client, device, temperature=22.0, boot=1, faults={"bme280": "missing"})
    assert body["id"]
    assert db.query(Telemetry).filter(Telemetry.device_id == device.id).count() == 1
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.sensor_key == "bme280", Alert.resolved.is_(False)).count() == 1


def test_a_post_that_loses_the_race_for_the_restart_loop_alert_still_stores_the_reading(client, db, device, monkeypatch):
    _open_alert(db, device, kind="reset_loop", sensor_key=None, message=f"{device.name} {health_service.RESET_LOOP_SUFFIX}")
    db.flush()
    monkeypatch.setattr(health_service, "open_alert_of_kind", lambda *a, **k: None)
    for boot in (1, 2, 3, 4):
        _post(client, device, temperature=20.0, boot=boot, up=3)
    assert db.query(Telemetry).filter(Telemetry.device_id == device.id).count() == 4
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "reset_loop", Alert.resolved.is_(False)).count() == 1


def test_the_device_lock_makes_a_second_connection_wait(db, device):
    from tests.conftest import _engine

    health_service.lock_device(db, device.id)
    key = f"phaemos:device-state:{device.id}"
    probe = text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))")
    with _engine.connect() as other:
        # the same device is held by the first transaction, another device is free
        assert other.execute(probe, {"k": key}).scalar() is False
        assert other.execute(probe, {"k": key + "-another"}).scalar() is True
        other.rollback()


def test_a_post_takes_the_device_lock_before_it_writes_anything(client, db, device):
    seen = []
    conn = db.get_bind()

    def record(conn_, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", record)
    try:
        _post(client, device, temperature=20.0, boot=1)
    finally:
        event.remove(conn, "before_cursor_execute", record)
    lock = next(i for i, q in enumerate(seen) if "pg_advisory_xact_lock" in q)
    first_write = next(i for i, q in enumerate(seen) if q.startswith("INSERT INTO telemetry") or q.startswith("UPDATE devices"))
    assert lock < first_write


def test_the_migration_resolves_older_duplicates_and_keeps_the_newest(db, device):
    migration = (Path(__file__).resolve().parents[1] / "migrations" / "020_open_alert_unique.sql")
    # the statements are told apart by the semicolon. The guards end in the \\gexec command instead, which stands in for one here
    source = re.sub(r"--[^\n]*", "", migration.read_text()).replace("\\gexec", ";")
    statements = [s.strip() for s in source.split(";") if s.strip().upper().startswith("UPDATE")]
    assert len(statements) == 2
    # the index exists in the test database (the models create it), so drop it to build the state an old database has
    db.execute(text("DROP INDEX IF EXISTS uq_alerts_open_system"))
    older = Alert(device_id=device.id, message=f"{device.name} has not reported for 2 minutes", severity="warning",
                  resolved=False, category="monitoring", triggered_at=T0)
    newer = Alert(device_id=device.id, message=f"{device.name} has not reported for 2 minutes", severity="warning",
                  resolved=False, category="monitoring", triggered_at=T0 + timedelta(hours=1))
    sensor_old = Alert(device_id=device.id, message="s", severity="warning", resolved=False, category="monitoring",
                       sensor_key="bme280", triggered_at=T0)
    sensor_new = Alert(device_id=device.id, message="s", severity="warning", resolved=False, category="monitoring",
                       sensor_key="bme280", triggered_at=T0 + timedelta(minutes=5))
    other_sensor = Alert(device_id=device.id, message="s", severity="warning", resolved=False, category="monitoring",
                         sensor_key="ldr", triggered_at=T0)
    machine = Alert(device_id=device.id, message="hot", severity="warning", resolved=False, triggered_at=T0)
    db.add_all([older, newer, sensor_old, sensor_new, other_sensor, machine])
    db.flush()
    for statement in statements:
        db.execute(text(statement))
    for alert in (older, newer, sensor_old, sensor_new, other_sensor, machine):
        db.refresh(alert)
    assert (older.kind, newer.kind, sensor_old.kind, other_sensor.kind, machine.kind) == ("offline", "offline", "sensor", "sensor", None)
    assert older.resolved is True and "newer alert of the same kind" in older.message
    assert newer.resolved is False
    assert sensor_old.resolved is True and sensor_new.resolved is False and other_sensor.resolved is False
    assert machine.resolved is False
    # the index can now be built, as the migration does
    db.execute(text(
        "CREATE UNIQUE INDEX uq_alerts_open_system ON alerts (device_id, kind, coalesce(sensor_key, '')) "
        "WHERE kind IS NOT NULL AND kind <> 'rule' AND resolved IS NOT TRUE"
    ))


def test_the_migration_builds_the_index_concurrently_with_a_lock_timeout():
    text_ = (Path(__file__).resolve().parents[1] / "migrations" / "020_open_alert_unique.sql").read_text()
    assert "SET lock_timeout" in text_
    assert "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_alerts_open_kind" in text_
    assert "NOT i.indisvalid" in text_


# -- the lows ---------------------------------------------------------------------------------------------------

def test_a_fault_does_not_raise_a_second_alert_for_the_same_cause(client, db, device, monkeypatch):
    class _Model:
        phaemos_features = ["temperature", "humidity"]
        phaemos_schema = ml_service.SCHEMA_VERSION
        offset_ = 0.0
        phaemos_typical_decision = 0.1

        def score_samples(self, X):
            return [-0.5] * len(X)

    monkeypatch.setattr(ml_service, "_model", {"default": _Model()})
    monkeypatch.setattr(health_service, "FAULT_ALERT_AFTER_S", 0)
    monkeypatch.setattr(health_service, "UNSCORED_ALERT_AFTER_S", 0)
    _post(client, device, temperature=20.0, humidity=40.0, boot=1, faults={"bme280": "missing"})
    _post(client, device, temperature=20.0, humidity=40.0, boot=1, faults={"bme280": "missing"})
    alerts = db.query(Alert).filter(Alert.device_id == device.id).all()
    assert [a.sensor_key for a in alerts] == ["bme280"]


def test_a_missing_input_that_no_fault_explains_still_raises_the_no_scored_reading_alert(client, db, device, monkeypatch):
    class _Model:
        phaemos_features = ["temperature", "humidity"]
        phaemos_schema = ml_service.SCHEMA_VERSION
        offset_ = 0.0
        phaemos_typical_decision = 0.1

        def score_samples(self, X):
            return [-0.5] * len(X)

    monkeypatch.setattr(ml_service, "_model", {"default": _Model()})
    monkeypatch.setattr(health_service, "UNSCORED_ALERT_AFTER_S", 0)
    _post(client, device, temperature=20.0)
    (alert,) = db.query(Alert).filter(Alert.device_id == device.id).all()
    assert alert.kind == "unscored" and "humidity" in alert.message


def test_a_recovered_sensor_that_is_still_intermittent_stops_saying_it_is_not_answering(db, device):
    _seen(db, device, 0, bme280="missing")
    _seen(db, device, 60, bme280="missing")
    (alert,) = db.query(Alert).filter(Alert.device_id == device.id).all()
    assert "not answering" in alert.message
    for seconds, faults in ((100, {}), (110, {"bme280": "missing"}), (120, {}), (130, {"bme280": "missing"}), (140, {})):
        _seen(db, device, seconds, **faults)
    # six changes in the hour and the sensor is back: the alert is kept and its words say why
    assert alert.resolved is False
    assert "intermittent" in alert.message and "not answering" not in alert.message


def test_a_node_that_reports_the_state_intermittent_is_an_ordinary_fault(db, device):
    # nothing treats the state specially: it opens after a minute like any other and has its own words
    for seconds in (0, 60):
        _seen(db, device, seconds, nano_link="intermittent")
    (alert,) = db.query(Alert).filter(Alert.device_id == device.id).all()
    assert alert.message.endswith("sensor nano_link is dropping in and out (intermittent)")


def test_a_node_type_that_does_not_fit_its_column_is_dropped_and_the_reading_kept(client, db, device):
    body = _post(client, device, temperature=20.0, node_type="x" * 21)
    assert body["node_type"] is None and body["temperature"] == 20.0
    assert body["quality"] == {"dropped_values": ["node_type"]}
    body = _post(client, device, temperature=20.0, node_type="es\u0000p")
    assert body["node_type"] is None
    assert _post(client, device, temperature=20.0, node_type="esp32")["node_type"] == "esp32"
    assert db.query(Telemetry).filter(Telemetry.device_id == device.id).count() == 3


def test_a_number_given_as_a_string_gets_the_same_range_check(client, device):
    body = _post(client, device, vib_peak="99")
    assert body["vib_peak"] is None
    assert body["quality"] == {"dropped_values": ["vib_peak"], "faults": {"stm32_mpu6050": "out_of_range"}}
    assert _post(client, device, vib_peak="0.5")["vib_peak"] == 0.5


def test_an_admin_sets_how_often_a_node_posts_and_the_thresholds_follow(client, db, device, auth_headers):
    res = client.patch(f"/api/v1/devices/{device.id}", json={"expected_interval_s": 30}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["expected_interval_s"] == 30
    device.last_seen = T0 - timedelta(seconds=100)
    device.link_state = "online"
    db.flush()
    # 100 s with a 30 s interval is not yet late (the limit is 120 s). At 5 s it would be
    liveness_service.sweep(db, now=T0, started_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert device.link_state == "online"
    liveness_service.sweep(db, now=T0 + timedelta(seconds=30), started_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert device.link_state == "late"


@pytest.mark.parametrize("value", [0, -1, 86_401, "often"])
def test_the_interval_is_bounded(client, device, auth_headers, value):
    assert client.patch(f"/api/v1/devices/{device.id}", json={"expected_interval_s": value}, headers=auth_headers).status_code == 422


def test_the_interval_is_an_admin_field(client, db, device):
    from tests.test_fault_alerts import _headers, _user

    tech = _user(db, "iv-tech@test.com", "technician")
    own = Device(name="own", api_key=secrets.token_urlsafe(16), owner_id=tech.id)
    db.add(own)
    db.flush()
    assert client.patch(f"/api/v1/devices/{own.id}", json={"expected_interval_s": 10}, headers=_headers(tech)).status_code == 403


def _scored_rows(db, device, ages):
    now = datetime.now(timezone.utc)
    for age in ages:
        db.add(Telemetry(device_id=device.id, temperature=25.0, anomaly_score=0.9, is_anomaly=True,
                         recorded_at=now - timedelta(seconds=age)))
    db.flush()


def _capture_decide(monkeypatch):
    seen = {}

    def decide(points, open_alert_since, last_resolved_at, now, interval_s):
        seen.update(points=points, interval=interval_s, open=open_alert_since)
        return alert_service.anomaly_decision.Decision("none")

    monkeypatch.setattr(alert_service.anomaly_decision, "decide", decide)
    return seen


def test_the_history_the_decision_gets_covers_a_slow_nodes_longer_window(db, device, monkeypatch):
    seen = _capture_decide(monkeypatch)
    device.expected_interval_s = 60
    # the clear window is 120 intervals (two hours at 60 s) and a raise window of 24 intervals more: a reading 20 minutes
    # old is evidence, one two and a half hours old is not
    _scored_rows(db, device, [9000, 1200, 10])
    alert_service.evaluate_anomaly(device, db)
    assert len(seen["points"]) == 2 and seen["interval"] == 60


def test_a_fast_nodes_history_is_the_half_hour_calm_and_one_raise_window(db, device, monkeypatch):
    seen = _capture_decide(monkeypatch)
    device.expected_interval_s = 5
    # 1,800 s of calm and a 120 s raise window
    _scored_rows(db, device, [1950, 1800, 10])
    alert_service.evaluate_anomaly(device, db)
    assert len(seen["points"]) == 2
    # oldest first and newest last, as the decision expects
    assert seen["points"][0][0] < seen["points"][1][0]


def test_unscored_readings_are_left_out_of_what_the_decision_gets(db, device, monkeypatch):
    seen = _capture_decide(monkeypatch)
    now = datetime.now(timezone.utc)
    db.add(Telemetry(device_id=device.id, temperature=1.0, anomaly_score=0.4, recorded_at=now - timedelta(seconds=20)))
    db.add(Telemetry(device_id=device.id, temperature=1.0, anomaly_score=None, recorded_at=now - timedelta(seconds=10)))
    db.flush()
    alert_service.evaluate_anomaly(device, db)
    assert [round(score, 1) for _, score in seen["points"]] == [0.4]


def test_resolved_rule_alerts_are_already_covered_by_the_twelve_month_rule():
    # a rule alert has rule_id set and kind null and the alerts rule matches on resolved and its age alone
    from app.tasks import retention
    import inspect

    source = inspect.getsource(retention.run_retention)
    assert "resolved IS TRUE AND COALESCE(resolved_at, triggered_at)" in source
    assert "rule_id" not in source


# -- the vibration clipping warning ----------------------------------------------------------------------------

def _clip(db, device, seconds, value):
    return health_service.track_clipping(db, device, {"vib_clipping": value}, _at(seconds))


def _clip_alerts(db, device, **filters):
    return db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "clipping").filter_by(**filters).all()


def test_clipping_opens_one_machine_warning_and_keeps_the_vibration_values(client, db, device, sent):
    body = _post(client, device, vibration_x=0.4, stm32_vib_x=15.9, vib_peak=30.0, vib_clipping=True)
    assert body["vib_clipping"] is True
    # a reading and not a fault: the vibration values are kept
    assert body["stm32_vib_x"] == 15.9 and body["vib_peak"] == 30.0 and body["vibration_x"] == 0.4
    (alert,) = _clip_alerts(db, device)
    assert alert.category == "machine" and alert.severity == "warning" and alert.rule_id is None
    assert alert.message == f"{device.name}: vibration is beyond the sensor's range"
    _post(client, device, vib_clipping=True)
    _post(client, device, vib_clipping=True)
    assert len(_clip_alerts(db, device)) == 1
    # one email on the hourly window for the device and kind
    assert [e["body"] for e in sent["email"]] == [alert.message]


def test_the_clipping_warning_resolves_after_a_minute_without_it(db, device):
    assert _clip(db, device, 0, True) is not None
    assert _clip(db, device, 30, False) is None
    assert _clip(db, device, 59, None) is None
    (alert,) = _clip_alerts(db, device)
    assert alert.resolved is False
    _clip(db, device, 61, False)
    assert alert.resolved is True and alert.message.endswith("(resolved: no clipping for a minute)")
    assert device.clipping_alerted is False


def test_clipping_that_comes_back_inside_the_minute_keeps_the_same_alert(db, device):
    _clip(db, device, 0, True)
    _clip(db, device, 40, False)
    _clip(db, device, 50, True)
    _clip(db, device, 100, False)
    (alert,) = _clip_alerts(db, device)
    # the last clipping was at 50, so 100 is only 50 seconds on
    assert alert.resolved is False
    _clip(db, device, 111, False)
    assert alert.resolved is True


def test_clipping_after_a_resolved_one_opens_a_new_warning(db, device):
    _clip(db, device, 0, True)
    _clip(db, device, 100, False)
    assert _clip(db, device, 500, True) is not None
    assert len(_clip_alerts(db, device)) == 2 and len(_clip_alerts(db, device, resolved=False)) == 1


def test_no_clipping_warning_opens_in_a_maintenance_window(db, device):
    now = datetime.now(timezone.utc)
    db.add(MaintenanceWindow(device_id=device.id, label="x", start_at=now - timedelta(hours=1),
                             end_at=now + timedelta(hours=1), suppress_alerts=True))
    db.flush()
    assert _clip(db, device, 0, True) is None
    assert _clip_alerts(db, device) == []


def test_clipping_is_stored_ored_in_buckets_and_exported(client, db, device, auth_headers):
    now = datetime.now(timezone.utc)
    base = now.replace(minute=10, second=0, microsecond=0) - timedelta(hours=2)
    for i, flag in enumerate([False, True, False]):
        db.add(Telemetry(device_id=device.id, vib_clipping=flag, recorded_at=base + timedelta(seconds=i)))
    db.flush()
    start = (base - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (base + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (row,) = client.get(f"/api/v1/telemetry/{device.id}?bucket=3600&from_ts={start}&to_ts={end}", headers=auth_headers).json()
    assert row["vib_clipping"] is True
    export = client.get(f"/api/v1/telemetry/export?device_id={device.id}&from_ts={start}", headers=auth_headers)
    assert "vib_clipping" in export.text.splitlines()[0]


def test_a_dead_vibration_link_stops_the_clipping_flag_too(client, device):
    body = _post(client, device, vib_clipping=True, stm32_vib_x=1.0, faults={"stm32_link": "silent"})
    assert body["vib_clipping"] is None and body["stm32_vib_x"] is None


def test_a_node_that_never_sends_clipping_stores_null_and_raises_nothing(client, db, device):
    assert _post(client, device, temperature=20.0)["vib_clipping"] is None
    assert db.query(Alert).filter(Alert.device_id == device.id).count() == 0


# -- the water input ---------------------------------------------------------------------------------------------

def test_an_unplugged_moisture_input_stops_the_level_and_keeps_the_leak_flag(client, db, device):
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric="water_detected", condition="eq", threshold=1.0, severity="critical"))
    db.flush()
    body = _post(client, device, moisture_level=12.0, water_detected=True, faults={"fc28": "unplugged"})
    assert body["moisture_level"] is None
    assert body["water_detected"] is True
    assert body["quality"]["faults"] == {"fc28": "unplugged"}
    assert body["quality"]["rejected"] == {"moisture_level": 12.0}
    # the leak rule fired
    alert = db.query(Alert).filter(Alert.device_id == device.id).one()
    assert "water_detected" in alert.message


@pytest.mark.parametrize("state", ["stuck", "missing", "out_of_range", "intermittent"])
def test_any_other_state_of_the_water_sensor_stops_both_fields(client, device, state):
    body = _post(client, device, moisture_level=300.0, water_detected=True, faults={"fc28": state})
    assert body["moisture_level"] is None and body["water_detected"] is None


def test_the_partial_state_table_is_general(monkeypatch):
    assert sensor_map.faulted_fields({"fc28": "unplugged"}) == {"moisture_level"}
    assert sensor_map.faulted_fields({"fc28": "stuck"}) == {"moisture_level", "water_detected"}
    monkeypatch.setitem(sensor_map.PARTIAL_STATE_FIELDS, ("mq2", "unplugged"), ("gas_level",))
    assert sensor_map.faulted_fields({"mq2": "unplugged"}) == {"gas_level"}
    assert sensor_map.faulted_fields({"mq2": "missing"}) == {"gas_level", "gas_alert"}
    assert sensor_map.state_fields("stm32", "silent") == sensor_map.SENSOR_FIELDS["stm32_link"]


def test_a_water_rule_is_not_listed_as_unable_to_fire_when_only_the_level_is_stopped():
    class _Rule:
        id = "r"
        metric = "water_detected"

    class _Level(_Rule):
        metric = "moisture_level"

    assert health_service.cannot_evaluate([_Rule()], {"fc28": "unplugged"}, []) == []
    (listed,) = health_service.cannot_evaluate([_Level()], {"fc28": "unplugged"}, [])
    assert listed["metric"] == "moisture_level" and listed["state"] == "unplugged"
    assert len(health_service.cannot_evaluate([_Rule()], {"fc28": "stuck"}, [])) == 1
