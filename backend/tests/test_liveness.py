"""
The liveness sweep: a node that stops posting goes late then offline, a silent node raises one monitoring alert that
resolves itself and an API restart does not make every node look silent. The clock is passed in, so nothing waits.
"""

import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.config import settings
from app.models.alert import Alert
from app.models.device import Device
from app.models.device_health import DeviceHealth
from app.models.maintenance import MaintenanceWindow
from app.models.user import User
from app.services import alert_service, cooldown, liveness_service, notify_service, sms_service
from tests.test_alert_notifications import FakeRedis

T0 = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
# a start time long before every clock below, so no start-up grace applies unless a test asks for it
LONG_AGO = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _sweep(db, seconds, started_at=LONG_AGO):
    return liveness_service.sweep(db, now=T0 + timedelta(seconds=seconds), started_at=started_at)


def _device(db, last_seen=T0, name=None, interval=5, status="online", link_state="online", owner=None):
    d = Device(
        name=name or f"node-{secrets.token_hex(3)}", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32),
        last_seen=last_seen, status=status, link_state=link_state, expected_interval_s=interval,
        owner_id=owner.id if owner else None,
    )
    db.add(d)
    db.flush()
    return d


def _alerts(db, device, **filters):
    return db.query(Alert).filter(Alert.device_id == device.id, Alert.category == "monitoring").filter_by(**filters).all()


@pytest.fixture
def store(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(cooldown, "_client", lambda: fake)
    cooldown._local.clear()
    cooldown._local_daily.clear()
    yield fake
    cooldown._local.clear()
    cooldown._local_daily.clear()


# -- the three states ---------------------------------------------------------------------------

@pytest.mark.parametrize("age,state,status", [
    (0, "online", "online"),
    (20, "online", "online"),
    (21, "late", "online"),
    (60, "late", "online"),
    (61, "offline", "offline"),
    (3000, "offline", "offline"),
])
def test_the_link_state_follows_the_age_of_the_last_post(db, age, state, status):
    device = _device(db)
    _sweep(db, age)
    assert (device.link_state, device.status) == (state, status)


def test_the_thresholds_scale_with_the_expected_interval(db):
    device = _device(db, interval=30)
    _sweep(db, 120)
    assert device.link_state == "online"
    _sweep(db, 121)
    assert device.link_state == "late"
    _sweep(db, 360)
    assert device.link_state == "late"
    _sweep(db, 361)
    assert device.link_state == "offline"


def test_the_sweep_counts_each_state_it_looked_at(db):
    _device(db, last_seen=T0)
    _device(db, last_seen=T0 - timedelta(seconds=30))
    _device(db, last_seen=T0 - timedelta(seconds=90))
    summary = _sweep(db, 0)
    # a device that is online and fresh has nothing to change, so the pass does not read it
    assert (summary["online"], summary["late"], summary["offline"]) == (0, 1, 1)


def test_a_device_that_never_posted_is_left_alone(db):
    device = _device(db, last_seen=None, status="offline", link_state="offline")
    _sweep(db, 9999)
    assert (device.status, device.link_state) == ("offline", "offline")
    assert _alerts(db, device) == []


def test_a_post_sets_the_node_online_at_once(client, db, device):
    device.last_seen = datetime.now(timezone.utc) - timedelta(minutes=10)
    device.link_state = "offline"
    device.status = "offline"
    db.flush()
    res = client.post("/api/v1/telemetry", json={"device_id": str(device.id), "temperature": 20.0}, headers={"X-API-Key": device.api_key})
    assert res.status_code == 201
    db.refresh(device)
    assert (device.link_state, device.status) == ("online", "online")


def test_status_stays_two_valued_and_returns_with_the_link(db):
    device = _device(db)
    _sweep(db, 40)
    # late is still "online" to an older client
    assert (device.link_state, device.status) == ("late", "online")
    _sweep(db, 100)
    assert (device.link_state, device.status) == ("offline", "offline")
    # the node posts again: the sweep that finds it fresh sets both back
    device.last_seen = T0 + timedelta(seconds=105)
    _sweep(db, 106)
    assert (device.link_state, device.status) == ("online", "online")


def test_a_status_set_by_hand_is_not_overwritten_while_the_node_is_fine(db):
    device = _device(db, status="fault")
    _sweep(db, 1)
    assert device.status == "fault"


# -- the monitoring alert -----------------------------------------------------------------------

def test_the_alert_opens_once_after_two_minutes_silent(db):
    device = _device(db, name="Pump 1")
    _sweep(db, 119)
    assert _alerts(db, device) == []
    summary = _sweep(db, 120)
    assert summary["alerts_opened"] == 1
    for later in (125, 140, 600):
        assert _sweep(db, later)["alerts_opened"] == 0
    (alert,) = _alerts(db, device)
    assert alert.message == "Pump 1 has not reported for 2 minutes"
    assert alert.category == "monitoring" and alert.severity == "warning"
    assert alert.rule_id is None and alert.resolved is False


def test_a_device_silent_for_over_a_day_is_offline_but_raises_nothing_new(db):
    # a machine that stopped long ago, found by the first sweep after an upgrade
    device = _device(db, last_seen=T0 - timedelta(days=30))
    _sweep(db, 0)
    assert device.link_state == "offline"
    assert _alerts(db, device) == []


def test_no_alert_is_raised_during_a_maintenance_window(db):
    device = _device(db)
    # the window is judged at the sweep's own clock
    db.add(MaintenanceWindow(
        device_id=device.id, label="service", start_at=T0, end_at=T0 + timedelta(hours=2),
        suppress_alerts=True,
    ))
    db.flush()
    _sweep(db, 600)
    # the link state still shows the truth. Only the alert is held back
    assert device.link_state == "offline"
    assert _alerts(db, device) == []


def test_the_alert_resolves_itself_when_the_node_posts_and_records_the_outage(client, db, device):
    seen = datetime.now(timezone.utc) - timedelta(minutes=7)
    device.last_seen = seen
    device.link_state = "online"
    device.status = "online"
    db.flush()
    summary = liveness_service.sweep(db, now=datetime.now(timezone.utc), started_at=LONG_AGO)
    assert summary["alerts_opened"] == 1
    (alert,) = _alerts(db, device)
    assert alert.resolved is False

    res = client.post("/api/v1/telemetry", json={"device_id": str(device.id), "temperature": 20.0}, headers={"X-API-Key": device.api_key})
    assert res.status_code == 201
    db.refresh(alert)
    db.refresh(device)
    assert alert.resolved is True and alert.resolved_at is not None
    assert alert.message.startswith(f"{device.name} has not reported for 2 minutes")
    assert "back online after 7 min" in alert.message
    assert device.link_state == "online"

    # and a node that goes quiet again opens a fresh alert and not a second one on the old row
    again = liveness_service.sweep(db, now=datetime.now(timezone.utc) + timedelta(minutes=5), started_at=LONG_AGO)
    assert again["alerts_opened"] == 1
    assert len(_alerts(db, device)) == 2
    assert len(_alerts(db, device, resolved=False)) == 1


def test_a_post_when_no_alert_was_open_changes_no_alert(client, db, device):
    device.last_seen = datetime.now(timezone.utc) - timedelta(seconds=30)
    device.link_state = "late"
    db.flush()
    res = client.post("/api/v1/telemetry", json={"device_id": str(device.id), "temperature": 20.0}, headers={"X-API-Key": device.api_key})
    assert res.status_code == 201
    assert _alerts(db, device) == []


def test_the_sweep_resolves_the_alert_if_the_node_came_back_another_way(db):
    device = _device(db)
    _sweep(db, 200)
    (alert,) = _alerts(db, device)
    device.last_seen = T0 + timedelta(seconds=250)
    _sweep(db, 251)
    db.refresh(alert)
    assert alert.resolved is True
    assert "back online after" in alert.message


# -- the start-up grace -------------------------------------------------------------------------

def test_after_a_restart_every_device_gets_a_full_interval_of_grace(db):
    # the API was down for an hour, so every device's last post is an hour old
    devices = [_device(db, last_seen=T0 - timedelta(hours=1)) for _ in range(6)]
    for seconds in (1, 5, 20):
        summary = _sweep(db, seconds, started_at=T0)
        assert summary["offline"] == 0 and summary["late"] == 0
    assert all(d.link_state == "online" and d.status == "online" for d in devices)
    assert all(_alerts(db, d) == [] for d in devices)


def test_the_same_devices_without_the_grace_would_all_be_offline(db):
    devices = [_device(db, last_seen=T0 - timedelta(hours=1)) for _ in range(6)]
    summary = _sweep(db, 1, started_at=LONG_AGO)
    assert summary["offline"] == 6
    assert all(d.status == "offline" for d in devices)


def test_a_device_that_stays_silent_after_a_restart_is_held_then_judged_by_its_real_age(db):
    device = _device(db, last_seen=T0 - timedelta(hours=1))
    _sweep(db, 30, started_at=T0)
    # still inside the grace: bad news is held back
    assert device.link_state == "online" and _alerts(db, device) == []
    _sweep(db, 61, started_at=T0)
    # the grace is over. It is judged by the real age (an hour), not by the time since the restart
    assert device.link_state == "offline" and device.status == "offline"
    assert len(_alerts(db, device)) == 1


def test_a_device_that_posts_after_the_restart_is_judged_from_its_own_post(db):
    device = _device(db, last_seen=T0 + timedelta(seconds=10))
    _sweep(db, 70, started_at=T0)
    # 60 seconds since its post is late. The restart does not hide that
    assert device.link_state == "late"


def test_a_device_silent_for_three_days_with_an_open_alert_stays_offline_across_a_restart(db, sent):
    device = _device(db, last_seen=T0 - timedelta(days=3), status="offline", link_state="offline")
    alert = Alert(
        device_id=device.id, message=f"{device.name} has not reported for 2 minutes", severity="warning",
        resolved=False, category="monitoring",
    )
    db.add(alert)
    db.flush()
    for seconds in (15, 30, 61, 120, 300):
        summary = _sweep(db, seconds, started_at=T0)
        assert summary["alerts_opened"] == 0 and summary["alerts_resolved"] == 0
        assert (device.link_state, device.status) == ("offline", "offline")
        assert alert.resolved is False
    assert len(_alerts(db, device)) == 1
    assert "back online" not in alert.message
    assert sent["email"] == []


def test_a_device_silent_for_a_year_raises_no_alert_after_a_restart(db, sent):
    device = _device(db, last_seen=T0 - timedelta(days=365), status="offline", link_state="offline")
    for seconds in (15, 61, 120, 300, 3600):
        _sweep(db, seconds, started_at=T0)
    assert _alerts(db, device) == []
    assert sent["email"] == []
    assert device.link_state == "offline"


def test_one_worker_restarting_does_not_flap_the_alert_of_a_dead_device(db, sent):
    # worker A has run for a long time. Worker B has just restarted. Both sweep the same dead device
    device = _device(db, last_seen=T0 - timedelta(days=3), status="offline", link_state="offline")
    alert = Alert(
        device_id=device.id, message=f"{device.name} has not reported for 2 minutes", severity="warning",
        resolved=False, category="monitoring",
    )
    db.add(alert)
    db.flush()
    for seconds in (15, 30, 45):
        liveness_service.sweep(db, now=T0 + timedelta(seconds=seconds), started_at=LONG_AGO)
        liveness_service.sweep(db, now=T0 + timedelta(seconds=seconds), started_at=T0)
        assert alert.resolved is False
        assert device.link_state == "offline"
    assert len(_alerts(db, device)) == 1
    assert sent["email"] == []


def test_a_live_node_is_never_held_back_from_online_by_the_grace(db):
    # good news needs a real post and is not delayed by the grace
    device = _device(db, last_seen=T0 + timedelta(seconds=5), status="offline", link_state="offline")
    _sweep(db, 6, started_at=T0)
    assert (device.link_state, device.status) == ("online", "online")


def test_the_start_time_is_set_when_the_scheduler_starts(monkeypatch):
    monkeypatch.setattr(liveness_service, "_started_at", None)
    liveness_service.mark_started(T0)
    assert liveness_service._started_at == T0


# -- notification -----------------------------------------------------------------------------

@pytest.fixture
def sent(monkeypatch, store):
    log = {"email": [], "sms": []}
    monkeypatch.setattr(notify_service, "send_email_alert", lambda **k: log["email"].append(k) or True)
    monkeypatch.setattr(sms_service, "notify_critical", lambda **k: log["sms"].append(k) or True)
    monkeypatch.setattr(sms_service, "notify_anomaly", lambda **k: log["sms"].append(k) or True)
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "brevo_api_key", "test-brevo-key")
    return log


def test_a_silent_node_emails_a_warning_and_never_texts(db, sent):
    owner = User(name="Owner", email=f"o-{secrets.token_hex(3)}@example.com", password_hash="x", role="admin", phone_number="+447700900000", phone_confirmed_at=datetime.now(timezone.utc))
    db.add(owner)
    db.flush()
    _device(db, name="Pump 1", owner=owner)
    _sweep(db, 300)
    _sweep(db, 330)
    assert len(sent["email"]) == 1
    assert sent["email"][0]["subject"] == "PHAEMOS [WARNING] Pump 1"
    assert sent["email"][0]["body"] == "Pump 1 has not reported for 2 minutes"
    assert sent["sms"] == []


def test_a_notification_is_sent_after_the_commit_not_inside_the_locked_pass(db, sent, monkeypatch):
    seen = []
    monkeypatch.setattr(db, "commit", lambda: seen.append(("commit", len(sent["email"]))))
    _device(db)
    _sweep(db, 300)
    assert seen == [("commit", 0)]
    assert len(sent["email"]) == 1


def test_the_alert_service_helper_uses_the_hourly_window(db, sent, store):
    device = _device(db)
    alert_service.notify_monitoring(None, device, "offline", "x")
    alert_service.notify_monitoring(None, device, "offline", "x")
    assert len(sent["email"]) == 1
    assert any("monitoring-offline" in key for key, _, _ in store.set_calls)


# -- the restart-loop alert clears ------------------------------------------------------------------

def test_the_restart_loop_alert_clears_when_the_boots_stop(db):
    device = _device(db, last_seen=T0)
    boots = [(T0 - timedelta(minutes=m)).isoformat() for m in (3, 2, 1)]
    db.add(DeviceHealth(device_id=device.id, boot_count=9, boot_events=boots))
    alert = Alert(
        device_id=device.id, message=f"{device.name} has restarted 3 times in 10 minutes", severity="warning",
        resolved=False, category="monitoring",
    )
    db.add(alert)
    db.flush()
    # still looping: the alert stays
    device.last_seen = T0 + timedelta(seconds=1)
    _sweep(db, 2)
    assert alert.resolved is False
    # eleven minutes on, with the node still posting and no new boot
    device.last_seen = T0 + timedelta(minutes=11, seconds=-1)
    _sweep(db, 11 * 60)
    assert alert.resolved is True


# -- the locks and the cost of a pass -------------------------------------------------------------

def _statements(db):
    from sqlalchemy import event
    seen = []
    conn = db.get_bind()

    def record(conn_, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", record)
    return seen, lambda: event.remove(conn, "before_cursor_execute", record)


def test_the_sweep_locks_without_blocking_posts(db):
    _device(db, last_seen=T0 - timedelta(seconds=90))
    seen, stop = _statements(db)
    try:
        _sweep(db, 0)
    finally:
        stop()
    locking = [q for q in seen if "FOR NO KEY UPDATE" in q]
    assert len(locking) == 1
    # only the devices table and skipping rows a post holds
    assert "OF devices" in locking[0] and "SKIP LOCKED" in locking[0]
    assert not [q for q in seen if "FOR UPDATE" in q.replace("FOR NO KEY UPDATE", "")]


def test_the_sweep_runs_a_fixed_number_of_queries_whatever_the_fleet_size(db):
    def cost(n):
        for _ in range(n):
            _device(db, last_seen=T0 - timedelta(seconds=300))
        seen, stop = _statements(db)
        try:
            _sweep(db, 0)
        finally:
            stop()
        return len(seen)

    small = cost(3)
    # thirty more devices, all offline and needing an alert and an update
    large = cost(30)
    assert large == small
    assert small <= 9


def test_the_sweep_reads_only_the_devices_that_can_need_a_change(db):
    fresh = _device(db, last_seen=T0, link_state="online")
    stale = _device(db, last_seen=T0 - timedelta(seconds=300), link_state="online")
    summary = _sweep(db, 0)
    assert summary["offline"] == 1 and summary["online"] == 0
    assert fresh.link_state == "online"
    assert stale.link_state == "offline"


def test_the_sweep_with_nothing_to_do_runs_one_query(db):
    _device(db, last_seen=T0)
    seen, stop = _statements(db)
    try:
        _sweep(db, 0)
    finally:
        stop()
    # the candidate read and the one statement that closes rule alerts whose readings stopped
    assert len(seen) == 2


def test_one_bad_device_does_not_stop_the_pass(db, monkeypatch, caplog):
    first = _device(db, last_seen=T0 - timedelta(seconds=300), name="first")
    second = _device(db, last_seen=T0 - timedelta(seconds=300), name="second")
    real = liveness_service._sweep_device
    calls = []

    def flaky(db_, device, *args, **kwargs):
        calls.append(device.name)
        if device.name == "first":
            raise RuntimeError("secret row value")
        return real(db_, device, *args, **kwargs)

    monkeypatch.setattr(liveness_service, "_sweep_device", flaky)
    with caplog.at_level("WARNING"):
        _sweep(db, 0)
    # the error type is logged and the text, which could hold a row value, is not
    assert "RuntimeError" in caplog.text and "secret row value" not in caplog.text
    assert sorted(calls) == ["first", "second"]
    assert second.link_state == "offline"
    assert first.link_state == "online"


def test_the_outage_length_of_an_alert_closed_by_the_sweep_is_the_real_outage(db):
    device = _device(db, last_seen=T0, name="Pump 1")
    _sweep(db, 300)
    (alert,) = _alerts(db, device)
    # the alert opened two minutes into the silence. The node came back at T0 + 600 and the sweep notices a few
    # seconds later. The outage is the ten minutes and not the seconds since the node's latest post
    alert.triggered_at = T0 + timedelta(seconds=120)
    db.flush()
    device.last_seen = T0 + timedelta(seconds=600)
    _sweep(db, 605)
    db.refresh(alert)
    assert alert.message.endswith("(back online after 10 min 0 s)")


# -- the lock -----------------------------------------------------------------------------------

class _KeepOpen:
    # lets the job close its session without ending the test's own transaction
    def __init__(self, session):
        self._session = session

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._session, name)


def test_two_workers_do_not_both_run_the_sweep(db, store):
    device = _device(db)
    factory = lambda: _KeepOpen(db)  # noqa: E731
    assert liveness_service.run_sweep_job(factory, now=T0 + timedelta(seconds=300)) is True
    first = [c for c in store.set_calls if c[0] == liveness_service.LOCK_KEY]
    assert first and first[0][1] is True and first[0][2] == liveness_service.LOCK_SECONDS
    # a second worker a moment later finds the lock taken and does nothing
    device.link_state = "online"
    assert liveness_service.run_sweep_job(factory, now=T0 + timedelta(seconds=300)) is False
    assert device.link_state == "online"


def test_the_lock_falls_back_to_process_memory_when_redis_is_down(db, monkeypatch):
    def broken():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(cooldown, "_client", broken)
    cooldown._local.clear()
    factory = lambda: _KeepOpen(db)  # noqa: E731
    assert liveness_service.run_sweep_job(factory, now=T0) is True
    assert liveness_service.run_sweep_job(factory, now=T0) is False
    cooldown._local.clear()


def test_a_failed_pass_is_logged_and_does_not_raise(db, store, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("database gone")

    monkeypatch.setattr(liveness_service, "sweep", boom)
    rolled = []
    session = SimpleNamespace(rollback=lambda: rolled.append(True), close=lambda: None)
    with caplog.at_level("WARNING"):
        assert liveness_service.run_sweep_job(lambda: session, now=T0) is False
    assert rolled == [True]
    assert "RuntimeError" in caplog.text and "database gone" not in caplog.text


def test_the_sweep_runs_on_the_retention_scheduler(monkeypatch):
    from app.tasks import retention

    jobs = {}

    class _Scheduler:
        def __init__(self, **kwargs):
            pass

        def add_job(self, func, **kwargs):
            jobs[kwargs["id"]] = (func, kwargs)

        def start(self):
            pass

    monkeypatch.setattr(retention, "BackgroundScheduler", _Scheduler)
    monkeypatch.setattr(liveness_service, "_started_at", None)
    retention.start_retention_scheduler()
    # every job is named on purpose, so a job added without a decision about it fails here
    assert set(jobs) == {"retention_cleanup", "liveness_sweep", "model_retrain"}
    assert jobs["retention_cleanup"][0] is retention.run_retention
    func, kwargs = jobs["liveness_sweep"]
    assert func is liveness_service.run_sweep_job
    assert kwargs["seconds"] == liveness_service.SWEEP_INTERVAL_S and kwargs["max_instances"] == 1
    assert liveness_service._started_at is not None
