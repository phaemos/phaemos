"""
Failures after the commit, the notify pool, deadlock retries, the model alert under the unique index, the daily cap under
concurrency, rule metrics, the new hub fields and the migrations that must take no lock when there is nothing to do.
"""

import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import settings
from app.models.alert import Alert, AlertRule
from app.models.device import Device
from app.models.device_health import DeviceHealth
from app.models.maintenance import MaintenanceWindow
from app.models.telemetry import Telemetry
from app.models.ticket import Ticket
from app.routes import telemetry as telemetry_route
from app.schemas.telemetry import TelemetryIngest
from app.services import (
    alert_service, alert_state, cooldown, health_service, liveness_service, ml_service, notify_pool, notify_service,
    rule_metrics, sensor_map, sms_service,
)
from tests.test_alert_notifications import FakeRedis, _owned_device

T0 = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
LONG_AGO = datetime(2000, 1, 1, tzinfo=timezone.utc)
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _at(seconds):
    return T0 + timedelta(seconds=seconds)


def _post(client, device, expect=201, **fields):
    res = client.post(
        "/api/v1/telemetry", json={"device_id": str(device.id), **fields}, headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == expect, res.text
    return res.json()


def _seen(db, device, seconds, **fields):
    payload = TelemetryIngest(device_id=str(device.id), **fields)
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
def mail(monkeypatch, store):
    log = []
    monkeypatch.setattr(notify_service, "send_email_alert", lambda **k: log.append(k) or True)
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    return log


# -- B1: a failure after the commit costs neither the reading nor the notifications ---------------------------

def test_a_failure_in_the_rule_evaluation_keeps_the_reply_the_reading_and_the_queued_notifications(
    client, db, device, mail, monkeypatch, caplog,
):
    # the failed step rolls its own work back. The test's session sits inside the test's outer transaction, so that rollback
    # is replaced here and the earlier rows stay
    monkeypatch.setattr(db, "rollback", lambda: None)
    telemetry_route._logged_after_commit.clear()
    monkeypatch.setattr(health_service, "FAULT_ALERT_AFTER_S", 0)

    def boom(*a, **k):
        raise RuntimeError("a rule broke")

    monkeypatch.setattr(telemetry_route, "evaluate_rules", boom)
    with caplog.at_level("ERROR"):
        body = _post(client, device, temperature=20.0, boot=1, faults={"bme280": "missing"})
        _post(client, device, temperature=20.0, boot=1, faults={"bme280": "missing"})
    assert body["id"]
    assert db.query(Telemetry).filter(Telemetry.device_id == device.id).count() == 2
    # the sensor alert's email, queued before the evaluation failed, was still sent
    assert len(mail) == 1 and "bme280" in mail[0]["body"]
    # logged once with its kind and not once per post
    assert caplog.text.count("evaluating the alert rules failed after the reading was stored (RuntimeError)") == 1


def test_a_failure_in_the_model_alert_evaluation_keeps_the_reply(client, db, device, monkeypatch):
    monkeypatch.setattr(db, "rollback", lambda: None)
    monkeypatch.setattr(telemetry_route, "evaluate_anomaly", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
    assert _post(client, device, temperature=20.0)["id"]
    assert db.query(Telemetry).filter(Telemetry.device_id == device.id).count() == 1


def test_the_window_is_a_minute_when_queued_and_an_hour_only_after_the_send_went_through(db, device, store, mail):
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric="temperature", condition="gt", threshold=50.0, severity="warning"))
    db.flush()
    jobs = []
    notify_pool.run_inline = False
    try:
        orig = notify_pool.submit
        notify_pool.submit = lambda job, critical=False, undo=None: jobs.append(job) or True
        alert_service.evaluate_rules(device, {"temperature": 99.0}, db)
    finally:
        notify_pool.submit = orig
        notify_pool.run_inline = True
    (key,) = [k for k in store.values if ":email:" in k and "alert-notify" in k]
    # queued and not yet sent: a minute
    assert store.ttls[key] == 60
    jobs[0]()
    assert store.ttls[key] == 3600


def test_a_failed_send_while_the_store_is_unreachable_does_not_keep_an_hour(db, device, monkeypatch):
    def broken():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(cooldown, "_client", broken)
    cooldown._local.clear()
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(notify_service, "send_email_alert", lambda **k: False)
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric="temperature", condition="gt", threshold=50.0, severity="warning"))
    db.flush()
    alert_service.evaluate_rules(device, {"temperature": 99.0}, db)
    (key,) = [k for k in cooldown._local if "alert-notify:email" in k]
    assert cooldown._local[key] - time.monotonic() <= 60
    cooldown._local.clear()


# -- rule metrics -----------------------------------------------------------------------------------------------

_RULE = {"metric": "temperature", "condition": "gt", "threshold": 50.0, "severity": "warning"}


def _create(client, device, auth_headers, **over):
    return client.post("/api/v1/alert-rules", json={"device_id": str(device.id), **_RULE, **over}, headers=auth_headers)


@pytest.mark.parametrize("metric", ["node_type", "rssi", "faults", "heap_free", "temprature", "device_id"])
def test_a_rule_on_something_a_post_cannot_carry_as_a_reading_is_refused(client, device, auth_headers, metric):
    assert _create(client, device, auth_headers, metric=metric).status_code == 422


@pytest.mark.parametrize("metric", ["temperature", "vibration_x", "gas_alert", "water_detected", "nano_temp", "vib_clipping", "anomaly_score"])
def test_a_rule_on_a_reading_is_accepted(client, device, auth_headers, metric):
    assert _create(client, device, auth_headers, metric=metric).status_code == 201


@pytest.mark.parametrize("over", [{"condition": "gte"}, {"condition": ""}, {"severity": "fatal"}])
def test_a_rule_with_an_unknown_condition_or_severity_is_refused(client, device, auth_headers, over):
    assert _create(client, device, auth_headers, **over).status_code == 422


def test_an_update_is_checked_too_and_an_old_rule_can_still_be_listed(client, db, device, auth_headers):
    old = AlertRule(for_seconds=0, device_id=device.id, metric="bogus_old", condition="gt", threshold=1.0, severity="warning")
    good = AlertRule(for_seconds=0, device_id=device.id, metric="temperature", condition="gt", threshold=1.0, severity="warning")
    db.add_all([old, good])
    db.flush()
    assert client.put(f"/api/v1/alert-rules/{good.id}", json={"metric": "nonsense"}, headers=auth_headers).status_code == 422
    assert client.put(f"/api/v1/alert-rules/{good.id}", json={"metric": "humidity"}, headers=auth_headers).status_code == 200
    listed = client.get(f"/api/v1/alert-rules?device_id={device.id}", headers=auth_headers)
    assert listed.status_code == 200 and {r["metric"] for r in listed.json()} == {"bogus_old", "humidity"}


def test_the_allowed_metrics_come_from_one_place(client, auth_headers):
    body = client.get("/api/v1/alert-metrics", headers=auth_headers).json()
    keys = [m["key"] for m in body["metrics"]]
    assert keys == list(rule_metrics.RULE_METRICS)
    assert "anomaly_score" in keys and "temperature" in keys and "node_type" not in keys and "rssi" not in keys
    types = {m["key"]: m["type"] for m in body["metrics"]}
    assert types["gas_alert"] == "boolean" and types["temperature"] == "number" and types["anomaly_score"] == "number"
    assert body["conditions"] == ["gt", "lt", "eq"] and body["severities"] == ["info", "warning", "critical"]
    from app.schemas.telemetry import TelemetryIngest as T
    assert set(keys) - {"anomaly_score"} <= set(T.model_fields)


def test_the_metrics_route_needs_a_sign_in(client):
    assert client.get("/api/v1/alert-metrics").status_code == 401


# -- X1: a rule on the anomaly score ------------------------------------------------------------------------------

def test_a_rule_on_the_anomaly_score_fires(client, db, device, stub_score):
    stub_score(0.93)
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric="anomaly_score", condition="gt", threshold=0.5, severity="critical"))
    db.flush()
    _post(client, device, temperature=20.0)
    alert = db.query(Alert).filter(Alert.device_id == device.id, Alert.rule_id.isnot(None)).one()
    assert "anomaly_score is 0.93" in alert.message and alert.severity == "critical"


def test_a_rule_on_the_score_does_not_fire_for_a_reading_that_was_not_scored(client, db, device, stub_score):
    stub_score(None)
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric="anomaly_score", condition="lt", threshold=0.5, severity="warning"))
    db.flush()
    _post(client, device, temperature=20.0)
    assert db.query(Alert).filter(Alert.device_id == device.id).count() == 0


# -- B2: the notify pool ----------------------------------------------------------------------------------------

@pytest.fixture
def real_pool(monkeypatch):
    monkeypatch.setattr(notify_pool, "run_inline", False)
    notify_pool.reset()
    gates = [threading.Event() for _ in range(notify_pool.WORKERS)]
    started = []

    def blocker(gate):
        started.append(1)
        gate.wait(10)

    # fill every worker so nothing queued can run until a gate opens
    for gate in gates:
        notify_pool.submit(partial(blocker, gate))
    deadline = time.time() + 5
    while len(started) < notify_pool.WORKERS and time.time() < deadline:
        time.sleep(0.01)
    assert len(started) == notify_pool.WORKERS
    yield gates
    for gate in gates:
        gate.set()
    time.sleep(0.05)
    notify_pool.reset()


def test_the_sizes_are_stated():
    assert notify_pool.WORKERS == 8 and notify_pool.QUEUE_LIMIT == 200


def test_a_critical_job_runs_before_jobs_that_were_queued_earlier(real_pool):
    order = []
    lock = threading.Lock()

    def job(name):
        with lock:
            order.append(name)

    notify_pool.submit(partial(job, "webhook-a"))
    notify_pool.submit(partial(job, "webhook-b"))
    notify_pool.submit(partial(job, "critical-text"), critical=True)
    # one worker is freed. The next job it takes is the critical one, though it was queued last
    real_pool[0].set()
    deadline = time.time() + 5
    while not order and time.time() < deadline:
        time.sleep(0.01)
    assert order[0] == "critical-text"


def test_a_full_queue_drops_the_oldest_normal_job_counts_and_logs_it_and_gives_back_its_undo(real_pool, caplog):
    undone = []
    with caplog.at_level("WARNING"):
        for i in range(notify_pool.QUEUE_LIMIT):
            notify_pool.submit(lambda: None, undo=partial(undone.append, i))
        assert notify_pool.dropped_total == 0
        notify_pool.submit(lambda: None, undo=partial(undone.append, "newest"))
    assert notify_pool.dropped_total == 1
    # the oldest was the one dropped
    assert undone == [0]
    assert "notification queue is full" in caplog.text


def test_a_critical_job_is_never_dropped(real_pool):
    undone = []
    for i in range(notify_pool.QUEUE_LIMIT + 10):
        assert notify_pool.submit(lambda: None, critical=True, undo=partial(undone.append, i)) is True
    assert notify_pool.dropped_total == 0 and undone == []
    # a normal job cannot be queued behind a queue that is all critical and is the one refused
    assert notify_pool.submit(lambda: None, undo=partial(undone.append, "normal")) is False
    assert notify_pool.dropped_total == 1 and undone == ["normal"]


def test_a_full_queue_makes_room_for_a_critical_job_by_dropping_a_normal_one(real_pool):
    for _ in range(notify_pool.QUEUE_LIMIT):
        notify_pool.submit(lambda: None)
    assert notify_pool.submit(lambda: None, critical=True) is True
    assert notify_pool.dropped_total == 1


def test_a_post_and_the_status_check_do_not_wait_while_the_pool_is_full_of_hung_sends(client, db, device, real_pool, mail):
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric="temperature", condition="gt", threshold=50.0, severity="warning"))
    db.flush()
    started = time.time()
    _post(client, device, temperature=99.0)
    # the post answered at once although every worker is held by a hung send. The status check is a plain route that no
    # notification can hold either
    assert time.time() - started < 2


def test_in_a_critical_alert_the_text_is_handed_to_the_pool_before_the_webhook_and_marked_critical(db, store, monkeypatch):
    from app.models.webhook import Webhook

    monkeypatch.setattr(settings, "brevo_api_key", "test-brevo-key")
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    device = _owned_device(db)
    db.add(Webhook(name="slow", url="https://hooks.example.com/x", enabled=True))
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric="temperature", condition="gt", threshold=50.0, severity="critical"))
    db.flush()
    seen = []
    monkeypatch.setattr(notify_pool, "submit", lambda job, critical=False, undo=None: seen.append((job, critical)) or True)
    alert_service.evaluate_rules(device, {"temperature": 99.0}, db)
    functions = [job.args[1] for job, _ in seen]
    assert functions[0] is sms_service.notify_critical
    assert all(critical for _, critical in seen)


def test_a_dropped_send_gives_its_daily_reservation_back(db, device, store, mail):
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric="temperature", condition="gt", threshold=50.0, severity="warning"))
    db.flush()
    notify_pool.run_inline = False
    orig = notify_pool.submit
    # the pool refuses the job and runs its undo
    notify_pool.submit = lambda job, critical=False, undo=None: (undo() if undo else None) or False
    try:
        alert_service.evaluate_rules(device, {"temperature": 99.0}, db)
    finally:
        notify_pool.submit = orig
        notify_pool.run_inline = True
    assert cooldown.daily_used("email") == 0


# -- B3: the daily cap under sends in flight ----------------------------------------------------------------------

def _queue_alerts(db, count, severity):
    for _ in range(count):
        d = _owned_device(db)
        db.add(AlertRule(for_seconds=0, device_id=d.id, metric="temperature", condition="gt", threshold=50.0, severity=severity))
        db.flush()
        alert_service.evaluate_rules(d, {"temperature": 99.0}, db)


def test_sixty_alerts_in_flight_at_once_cannot_pass_a_cap_of_fifty(db, store, mail, monkeypatch):
    monkeypatch.setattr(settings, "alert_email_daily_cap", 50)
    # the sender is chosen when a job runs, so it can fail later although the jobs were queued while it worked
    outcome = {"ok": True}
    monkeypatch.setattr(notify_service, "send_email_alert", lambda **k: outcome["ok"])
    jobs = []
    monkeypatch.setattr(notify_pool, "submit", lambda job, critical=False, undo=None: jobs.append((job, undo)) or True)
    # sixty warnings: a fifth of the cap (10) is kept for critical alerts, so warnings stop at forty
    _queue_alerts(db, 60, "warning")
    assert len(jobs) == 40
    assert cooldown.daily_used("email") == 40
    # sixty critical alerts take what is left, which is the reserve. The total is the cap and no more
    _queue_alerts(db, 60, "critical")
    assert len(jobs) == 50
    assert cooldown.daily_used("email") == 50
    # sends that then fail give their reservations back
    outcome["ok"] = False
    for job, _ in jobs[:10]:
        job()
    assert cooldown.daily_used("email") == 40


def test_sixty_reservations_racing_never_pass_the_cap_or_the_warnings_the_reserve(db, monkeypatch):
    # sixty threads reserve at the same moment, half of them critical. The count is one atomic step, so the total can never pass
    # the cap whatever the order. Warnings never get into the reserve
    monkeypatch.setattr(cooldown, "_redis_down_until", time.monotonic() + 1000)
    cooldown._local_daily.clear()
    devices = []
    for _ in range(60):
        d = Device(name="racer", api_key=secrets.token_urlsafe(32))
        db.add(d)
        devices.append(d)
    db.flush()
    barrier = threading.Barrier(60)
    won = {"warning": 0, "critical": 0}
    lock = threading.Lock()

    def reserve(device, critical):
        barrier.wait()
        held, _, _ = alert_service.reserve_daily_send("email", device, 1, 50, critical)
        if held is not None:
            with lock:
                won["critical" if critical else "warning"] += 1

    threads = [threading.Thread(target=reserve, args=(d, i % 2 == 0)) for i, d in enumerate(devices)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert cooldown.daily_used("email") == won["warning"] + won["critical"] <= 50
    assert won["warning"] <= 30
    assert won["critical"] <= 30
    # the warnings alone can reach forty and the critical alerts the rest, so the total lies between forty and the cap
    assert 40 <= won["warning"] + won["critical"] <= 50
    cooldown._local_daily.clear()


def test_reserve_is_all_or_nothing_for_several_recipients(store):
    assert cooldown.reserve_daily("email", 2, 3) is True
    assert cooldown.reserve_daily("email", 2, 3) is False
    assert cooldown.daily_used("email") == 2


# -- B4: lock order, a bounded wait and a retry on a deadlock ---------------------------------------------------

def _lock_error(code):
    class _Orig(Exception):
        pgcode = code

    return OperationalError("SELECT 1", {}, _Orig("deadlock detected"))


@pytest.mark.parametrize("code", ["40P01", "40001", "55P03"])
def test_a_post_that_hits_a_lock_problem_is_run_again_once_and_the_reading_is_stored(client, db, device, monkeypatch, code):
    # nothing has been written when the stand-in fails and the test's own transaction must survive the route's rollback
    monkeypatch.setattr(db, "rollback", lambda: None)
    real = telemetry_route._store_reading
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise _lock_error(code)
        return real(*args, **kwargs)

    monkeypatch.setattr(telemetry_route, "_store_reading", flaky)
    _post(client, device, temperature=20.0)
    assert len(calls) == 2
    assert db.query(Telemetry).filter(Telemetry.device_id == device.id).count() == 1


def test_a_second_lock_failure_is_not_hidden(client, db, device, monkeypatch):
    monkeypatch.setattr(db, "rollback", lambda: None)
    monkeypatch.setattr(telemetry_route, "_store_reading", lambda *a, **k: (_ for _ in ()).throw(_lock_error("40P01")))
    # the app answers a database error with a 500 (its error handler), so the failure is visible and not turned into a 201
    _post(client, device, expect=500, temperature=20.0)


def test_another_database_error_is_not_retried(client, db, device, monkeypatch):
    monkeypatch.setattr(db, "rollback", lambda: None)
    calls = []
    monkeypatch.setattr(telemetry_route, "_store_reading", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(_lock_error("23505")))
    _post(client, device, expect=500, temperature=20.0)
    assert len(calls) == 1


def test_a_post_locks_the_device_row_first_then_the_advisory_lock_with_a_bounded_wait(client, db, device):
    from sqlalchemy import event

    seen = []
    conn = db.get_bind()

    def record(conn_, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", record)
    try:
        _post(client, device, temperature=20.0)
    finally:
        event.remove(conn, "before_cursor_execute", record)
    timeout = next(i for i, q in enumerate(seen) if "SET LOCAL lock_timeout" in q)
    row_lock = next(i for i, q in enumerate(seen) if "FOR NO KEY UPDATE" in q and "FROM devices" in q)
    advisory = next(i for i, q in enumerate(seen) if "pg_advisory_xact_lock" in q)
    first_write = next(i for i, q in enumerate(seen) if q.startswith("INSERT INTO telemetry") or q.startswith("UPDATE devices"))
    # the sweep also takes the device row first, so the two paths can never wait on each other's second lock
    assert timeout < row_lock < advisory < first_write


def test_the_device_is_read_again_under_its_lock(client, db, device, monkeypatch):
    # the database says the node is offline and has an open silent-node alert. The copy loaded before the lock says online
    device.link_state, device.status = "offline", "offline"
    device.last_seen = datetime.now(timezone.utc) - timedelta(minutes=5)
    alert = Alert(device_id=device.id, message=f"{device.name} has not reported for 2 minutes", severity="warning",
                  resolved=False, category="monitoring", kind="offline")
    db.add(alert)
    db.flush()
    real = telemetry_route.get_device_by_api_key

    def stale(api_key, session):
        found = real(api_key, session)
        found.link_state = "online"
        # a copy that is out of date and no longer tied to the session, as one loaded before the lock would be. (The test's
        # session autoflushes, which would otherwise write the stale value to the database before the re-read)
        session.expunge(found)
        return found

    monkeypatch.setattr(telemetry_route, "get_device_by_api_key", stale)
    _post(client, device, temperature=20.0)
    db.refresh(alert)
    # the post worked from the row as the database holds it, so it saw the node come back and closed the alert
    assert alert.resolved is True and "back online after" in alert.message


def test_the_lock_timeout_is_stated():
    assert alert_state.LOCK_TIMEOUT == "5s"


# -- B5: the model's alert under the lock and the index ---------------------------------------------------------

def _rows(db, device, n=3):
    now = datetime.now(timezone.utc)
    for i in range(n):
        db.add(Telemetry(device_id=device.id, temperature=25.0, anomaly_score=0.9, is_anomaly=True,
                         recorded_at=now - timedelta(seconds=i)))
    db.flush()


def test_the_model_alert_has_a_kind_and_one_ticket(db, device, old_three_in_a_row):
    _rows(db, device)
    alert_service.evaluate_anomaly(device, db)
    alert = db.query(Alert).filter(Alert.device_id == device.id).one()
    assert alert.kind == "anomaly" and alert.category == "machine"
    assert db.query(Ticket).filter(Ticket.device_id == device.id).count() == 1


def test_a_second_evaluation_that_does_not_see_the_open_alert_raises_neither_an_alert_nor_a_ticket(db, device, monkeypatch, old_three_in_a_row):
    # the other post's alert is open but this evaluation's lookup does not see it, as when two posts race
    db.add(Alert(device_id=device.id, message="another post's alert", severity="warning", resolved=False, kind="anomaly"))
    db.flush()
    monkeypatch.setattr(alert_service, "_open_anomaly_alert", lambda *a, **k: None)
    _rows(db, device)
    alert_service.evaluate_anomaly(device, db)
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.resolved.is_(False)).count() == 1
    assert db.query(Ticket).filter(Ticket.device_id == device.id).count() == 0


def test_the_model_alert_takes_the_device_lock(db, device):
    from sqlalchemy import event

    seen = []
    conn = db.get_bind()

    def record(conn_, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    _rows(db, device)
    event.listen(conn, "before_cursor_execute", record)
    try:
        alert_service.evaluate_anomaly(device, db)
    finally:
        event.remove(conn, "before_cursor_execute", record)
    assert any("pg_advisory_xact_lock" in q for q in seen)


# -- B9, the summary, add_alert, resolved NOT NULL ---------------------------------------------------------

@pytest.fixture
def clean_model(monkeypatch, tmp_path):
    path = tmp_path / "model.pkl"
    monkeypatch.setattr(ml_service, "MODEL_PATH", str(path))
    monkeypatch.setattr(ml_service, "_model", None)
    monkeypatch.setattr(ml_service, "_problem", None)
    monkeypatch.setattr(ml_service, "_load_failure", None)
    monkeypatch.setattr(ml_service, "_logged", set())
    return path


def test_a_broken_model_file_deleted_by_hand_stops_being_a_problem(clean_model):
    clean_model.write_bytes(b"garbage")
    assert ml_service.score_reading({"temperature": 1.0}) == (None, False)
    assert ml_service.model_state() == "error"
    clean_model.unlink()
    assert ml_service.score_reading({"temperature": 1.0}) == (0.0, False)
    assert ml_service.scoring_problem() is None and ml_service.model_state() == "none"


def test_the_summary_counts_the_worse_of_the_stored_state_and_the_age(client, db, auth_headers):
    now = datetime.now(timezone.utc)

    def make(link, age, interval=5):
        d = Device(name=secrets.token_hex(3), api_key=secrets.token_urlsafe(16), link_state=link,
                   last_seen=now - timedelta(seconds=age), expected_interval_s=interval)
        db.add(d)

    make("online", 1)         # fresh: online
    make("online", 30)        # stored online, 30 s old at 5 s: late
    make("online", 100)       # stored online, 100 s old: offline
    make("late", 1)           # stored late stays late
    make("offline", 1)        # stored offline stays offline
    make("online", 100, 30)   # 100 s at a 30 s interval is still online
    db.flush()
    counts = client.get("/api/v1/health/summary", headers=auth_headers).json()["link_states"]
    assert counts == {"online": 2, "late": 2, "offline": 2}


def test_effective_link_state_for_a_device_that_never_posted_is_its_stored_state():
    assert liveness_service.effective_link_state("offline", None, 5, datetime.now(timezone.utc)) == "offline"
    assert liveness_service.effective_link_state("bogus", None, 5, datetime.now(timezone.utc)) == "offline"


def test_add_alert_absorbs_only_the_open_alert_refusal(db, device):
    def make(**over):
        return Alert(device_id=device.id, message="a", severity="warning", resolved=False, category="monitoring",
                     sensor_key="x", kind="sensor", **over)

    assert alert_state.add_alert(db, make()) is True
    assert alert_state.add_alert(db, make()) is False
    # a missing machine is a foreign key failure, which is raised and not reported as a duplicate
    import uuid

    with pytest.raises(IntegrityError):
        alert_state.add_alert(db, Alert(device_id=uuid.uuid4(), message="a", severity="warning", resolved=False,
                                        category="monitoring", sensor_key="y", kind="sensor"))


def test_a_not_null_failure_is_raised_too(db, device):
    with pytest.raises(IntegrityError):
        alert_state.add_alert(db, Alert(device_id=None, message="a", severity="warning", resolved=False,
                                        category="monitoring", sensor_key="z", kind="sensor"))


def test_resolved_cannot_be_null(db, device):
    # written with SQL so the model's own default cannot fill it in
    with pytest.raises(IntegrityError):
        db.execute(
            text("INSERT INTO alerts (id, device_id, message, resolved) VALUES (gen_random_uuid(), CAST(:d AS uuid), 'x', NULL)"),
            {"d": str(device.id)},
        )


def test_the_unique_violation_is_recognised_by_its_index_name(db, device):
    first = Alert(device_id=device.id, message="a", severity="warning", resolved=False, category="monitoring", kind="offline")
    db.add(first)
    db.flush()
    db.add(Alert(device_id=device.id, message="b", severity="warning", resolved=False, category="monitoring", kind="offline"))
    with pytest.raises(IntegrityError) as caught:
        db.flush()
    assert alert_state.is_open_alert_violation(caught.value) is True
    db.rollback()


# -- L9: a hand resolve --------------------------------------------------------------------------------------------

def test_a_hand_resolve_of_a_system_alert_is_recorded_in_its_message(client, db, device, auth_headers):
    alert = Alert(device_id=device.id, message="x has not reported for 2 minutes", severity="warning", resolved=False,
                  category="monitoring", kind="offline")
    db.add(alert)
    db.flush()
    res = client.patch(f"/api/v1/alerts/{alert.id}/resolve", headers=auth_headers)
    assert res.status_code == 200 and res.json()["message"].endswith("(resolved by hand)")
    # a rule alert is not changed
    rule_alert = Alert(device_id=device.id, message="hot", severity="warning", resolved=False)
    db.add(rule_alert)
    db.flush()
    assert client.patch(f"/api/v1/alerts/{rule_alert.id}/resolve", headers=auth_headers).json()["message"] == "hot"


def test_a_silent_node_alert_resolved_by_hand_is_not_raised_again_for_an_hour(db, device):
    device.last_seen = T0 - timedelta(seconds=300)
    device.link_state = "offline"
    device.status = "offline"
    db.flush()
    liveness_service.sweep(db, now=T0, started_at=LONG_AGO)
    alert = db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "offline").one()
    alert.resolved, alert.resolved_at = True, T0 + timedelta(seconds=5)
    alert.message += " (resolved by hand)"
    db.flush()
    liveness_service.sweep(db, now=T0 + timedelta(seconds=20), started_at=LONG_AGO)
    liveness_service.sweep(db, now=T0 + timedelta(minutes=59), started_at=LONG_AGO)
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "offline").count() == 1
    # an hour on, the node is still silent and a new alert is raised
    liveness_service.sweep(db, now=T0 + timedelta(hours=1, minutes=5), started_at=LONG_AGO)
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "offline", Alert.resolved.is_(False)).count() == 1


def test_a_sensor_alert_resolved_by_hand_while_the_fault_goes_on_returns_as_a_new_alert_that_says_so(db, device):
    for seconds in (0, 60):
        _seen(db, device, seconds, faults={"bme280": "missing"})
    alert = db.query(Alert).filter(Alert.device_id == device.id, Alert.sensor_key == "bme280").one()
    alert.resolved, alert.resolved_at = True, _at(70)
    alert.message += " (resolved by hand)"
    db.flush()
    # inside the hour nothing is raised and the fault goes on
    _seen(db, device, 600, faults={"bme280": "missing"})
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.resolved.is_(False)).count() == 0
    result = _seen(db, device, 4000, faults={"bme280": "missing"})
    fresh = db.query(Alert).filter(Alert.device_id == device.id, Alert.resolved.is_(False)).one()
    assert fresh.message.endswith("(an earlier alert for this fault was resolved by hand)")
    assert result.notify and result.notify[0][0] == "sensor-bme280"


def test_a_sensor_alert_resolved_by_hand_after_the_fault_ended_is_not_raised_again(db, device):
    for seconds in (0, 60):
        _seen(db, device, seconds, faults={"bme280": "missing"})
    # the sensor reports ok: a post that carries health fields and no fault
    for seconds in (100, 200):
        _seen(db, device, seconds, faults={})
    _seen(db, device, 5000, faults={})
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.resolved.is_(False)).count() == 0


# -- the new hub fields -------------------------------------------------------------------------------------------

DIAG = {"posts": 1200, "bodiesReplaced": 3, "bodyTooBig": 0, "stackLoop": 2100, "stackNet": 1800, "minHeap": 98000,
        "maxBlock": 54000}


def test_diag_is_stored_and_returned(client, db, device, auth_headers):
    _post(client, device, temperature=20.0, boot=1, diag=DIAG)
    assert db.get(DeviceHealth, device.id).diag == DIAG
    health = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()["health"]
    assert health["diag"] == DIAG
    # a later post replaces it and one that leaves it out keeps it
    _post(client, device, temperature=20.0, boot=1, diag={"posts": 1300})
    _post(client, device, temperature=20.0, boot=1)
    assert db.get(DeviceHealth, device.id).diag == {"posts": 1300}


@pytest.mark.parametrize("bad", [
    {"posts": -1}, {"posts": 1.5}, {"posts": "many"}, {"posts": True}, {"posts": 4_294_967_296}, {"a" * 25: 1},
    {"bad name": 1}, {"1st": 1}, {"nul\u0000": 1},
])
def test_a_bad_diag_entry_is_dropped_the_rest_kept_and_diag_is_named(client, db, device, bad):
    body = _post(client, device, temperature=20.0, boot=1, diag={"good": 5, **bad})
    assert body["quality"] == {"dropped_health": ["diag"]}
    assert db.get(DeviceHealth, device.id).diag == {"good": 5}


def test_diag_keeps_at_most_sixteen_keys(client, db, device):
    body = _post(client, device, boot=1, diag={f"k{i}": i for i in range(30)})
    assert len(db.get(DeviceHealth, device.id).diag) == 16
    assert body["quality"] == {"dropped_health": ["diag"]}


def test_a_diag_that_is_not_an_object_is_dropped_whole_and_the_last_stays(client, db, device):
    _post(client, device, boot=1, diag={"posts": 1})
    body = _post(client, device, boot=1, diag=[1, 2])
    assert body["quality"] == {"dropped_health": ["diag"]}
    assert db.get(DeviceHealth, device.id).diag == {"posts": 1}


def test_board_mismatch_opens_one_monitoring_alert_and_resolves_when_it_stops(client, db, device, mail):
    _post(client, device, boot=1, board_mismatch=True)
    _post(client, device, boot=1, board_mismatch=True)
    alert = db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "board_mismatch").one()
    assert alert.category == "monitoring" and alert.severity == "warning" and alert.resolved is False
    assert alert.message == f"{device.name}: the firmware image does not match this board"
    assert [m["body"] for m in mail] == [alert.message]
    assert db.get(DeviceHealth, device.id).board_mismatch is True
    _post(client, device, boot=1, board_mismatch=False)
    db.refresh(alert)
    assert alert.resolved is True and db.get(DeviceHealth, device.id).board_mismatch is False


def test_board_mismatch_is_held_back_in_a_maintenance_window(db, device):
    now = datetime.now(timezone.utc)
    db.add(MaintenanceWindow(device_id=device.id, label="x", start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1),
                             suppress_alerts=True))
    db.flush()
    _seen(db, device, 0, board_mismatch=True)
    assert db.query(Alert).filter(Alert.device_id == device.id).count() == 0


def test_a_board_mismatch_that_is_not_a_boolean_is_dropped_and_changes_nothing(client, db, device):
    _post(client, device, boot=1, board_mismatch=True)
    body = _post(client, device, boot=1, board_mismatch="yes")
    assert body["quality"] == {"dropped_health": ["board_mismatch"]}
    assert db.get(DeviceHealth, device.id).board_mismatch is True


def test_the_sensors_a_firmware_was_built_without_are_kept_apart_and_never_raise_a_fault(client, db, device, auth_headers):
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric="distance_mm", condition="gt", threshold=5.0, severity="warning"))
    device.not_fitted = ["ldr"]
    db.flush()
    _post(client, device, boot=1, not_fitted=["vl53l0x", "STM32", "toaster", "vl53l0x"], faults={"vl53l0x": "missing", "nano_link": "silent"})
    row = db.get(DeviceHealth, device.id)
    # canonical keys, each once, unknown ones dropped and named
    assert row.not_fitted_by_firmware == ["vl53l0x", "stm32_link"]
    body = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()
    assert body["not_fitted"] == ["ldr"]
    assert body["not_fitted_by_firmware"] == ["vl53l0x", "stm32_link"]
    assert body["health"]["faults"] == {"vl53l0x": "not_fitted", "nano_link": "silent"}
    (listed,) = body["health"]["rules_cannot_evaluate"]
    assert listed["state"] == "not_fitted" and listed["sensor_key"] == "vl53l0x"
    # the sensor alert for a key the firmware was built without is never raised
    for seconds in (0, 60, 600):
        _seen(db, device, seconds, faults={"vl53l0x": "missing"})
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.sensor_key == "vl53l0x").count() == 0


def test_not_fitted_posted_once_is_kept_across_posts_that_leave_it_out(client, db, device):
    _post(client, device, boot=1, not_fitted=["vl53l0x"])
    _post(client, device, boot=1)
    assert db.get(DeviceHealth, device.id).not_fitted_by_firmware == ["vl53l0x"]
    _post(client, device, boot=1, not_fitted=[])
    assert db.get(DeviceHealth, device.id).not_fitted_by_firmware == []


def test_a_not_fitted_that_is_not_a_list_is_dropped_whole(client, db, device):
    _post(client, device, boot=1, not_fitted=["vl53l0x"])
    body = _post(client, device, boot=1, not_fitted="vl53l0x")
    assert body["quality"] == {"dropped_health": ["not_fitted"]}
    assert db.get(DeviceHealth, device.id).not_fitted_by_firmware == ["vl53l0x"]


def test_the_fault_entry_cap_follows_the_key_list():
    assert sensor_map.MAX_FAULT_ENTRIES >= len(sensor_map.SENSOR_FIELDS) + 16
    every_key = {key: "missing" for key in sensor_map.SENSOR_FIELDS}
    assert sensor_map.clean_faults(every_key) == every_key


def test_links_still_accept_fmt():
    payload = TelemetryIngest(device_id="x", links={"nano": {"ok": 1, "fmt": 2}})
    assert payload.links == {"nano": {"ok": 1, "fmt": 2}}


# -- migrations that must take no lock when there is nothing to do ------------------------------------------------

_GUARDED = re.compile(r"SELECT \$q\$(.*?)\$q\$\s*(WHERE.*?)\\gexec", re.S)


@pytest.mark.parametrize("name", [
    "012_health.sql", "015_fault_alerts_and_links.sql", "020_open_alert_unique.sql", "021_vibration_clipping.sql",
    "028_alert_state.sql", "029_stateful_rule_alerts.sql",
])
def test_no_alter_table_is_sent_unguarded(name):
    source = re.sub(r"--[^\n]*", "", (MIGRATIONS / name).read_text())
    unguarded = _GUARDED.sub("", source)
    assert "ALTER TABLE" not in unguarded
    assert _GUARDED.search(source)


@pytest.mark.parametrize("name", [
    "012_health.sql", "015_fault_alerts_and_links.sql", "020_open_alert_unique.sql", "021_vibration_clipping.sql",
    "028_alert_state.sql", "029_stateful_rule_alerts.sql",
])
def test_every_guard_finds_nothing_to_do_on_an_up_to_date_database(db, name):
    source = re.sub(r"--[^\n]*", "", (MIGRATIONS / name).read_text())
    for statement, guard in _GUARDED.findall(source):
        rows = db.execute(text(f"SELECT 1 {guard.strip()}")).all()
        assert rows == [], f"{name}: a guard would still send {statement.strip()[:60]!r}"


def test_the_not_null_change_is_made_in_steps_that_hold_no_long_lock():
    # the statements, with the comments left out so the words in the header cannot be mistaken for them
    source = re.sub(r"--[^\n]*", "", (MIGRATIONS / "028_alert_state.sql").read_text())
    assert "NOT VALID" in source and "VALIDATE CONSTRAINT" in source and "SET NOT NULL" in source
    assert source.index("NOT VALID") < source.index("VALIDATE CONSTRAINT") < source.index("SET NOT NULL")
    assert source.index("SET NOT NULL") < source.index("DROP CONSTRAINT alerts_resolved_not_null")
    assert "SET lock_timeout" in source
