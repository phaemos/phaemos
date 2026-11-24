import itertools
import logging
import secrets
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import BackgroundTasks

from app.config import settings
from app.models.alert import Alert, AlertRule
from app.models.device import Device
from app.models.telemetry import Telemetry
from app.models.user import User
from app.services import alert_service, cooldown, email_service, notify_service, sms_service

READING = {"temperature": 99.0}


class FakeRedis:
    # an in-memory stand-in for the Redis calls the cooldown makes. set records its
    # expiry and honours nx, so a test fails if the code stops passing either.
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.expire_at = {}
        self.set_calls = []

    def set(self, key, value, nx=False, ex=None):
        self.set_calls.append((key, nx, ex))
        if nx and key in self.values:
            return None
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def delete(self, key):
        self.values.pop(key, None)
        self.ttls.pop(key, None)

    def incrby(self, key, amount):
        self.values[key] = int(self.values.get(key, 0)) + amount
        return self.values[key]

    def expireat(self, key, timestamp):
        self.expire_at[key] = timestamp

    def decrby(self, key, amount):
        self.values[key] = int(self.values.get(key, 0)) - amount
        return self.values[key]

    def get(self, key):
        return self.values.get(key)

    def expire(self, key, seconds):
        # a key that exists has its life cut to this many seconds
        if key in self.values:
            self.ttls[key] = seconds

    def expire_now(self, key):
        # simulates the key's time to live running out
        self.values.pop(key, None)


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
def sent(monkeypatch):
    # records what would have gone to each vendor-facing function. Discord and
    # webhooks are silenced so nothing leaves the test. A fake returns what the
    # real function does: True once the message was handed over.
    log = {"email": [], "sms": [], "anomaly_sms": [], "result": True}
    monkeypatch.setattr(notify_service, "send_discord_alert", lambda *a, **k: None)
    monkeypatch.setattr(alert_service.webhook_service, "notify_all", lambda *a, **k: None)
    monkeypatch.setattr(notify_service, "send_email_alert", lambda **k: log["email"].append(k) or log["result"])
    monkeypatch.setattr(sms_service, "notify_critical", lambda **k: log["sms"].append(k) or log["result"])
    monkeypatch.setattr(sms_service, "notify_anomaly", lambda **k: log["anomaly_sms"].append(k) or log["result"])
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "brevo_api_key", "test-brevo-key")
    return log


def _rule(db, device, severity, metric="temperature"):
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric=metric, condition="gt", threshold=50.0, severity=severity))
    db.flush()


def _owned_device(db, phone="+447700900000"):
    owner = User(name="Owner", email=f"owner-{secrets.token_hex(4)}@example.com", password_hash="x", role="admin", phone_number=phone,
                 phone_confirmed_at=datetime.now(timezone.utc) if phone else None)
    db.add(owner)
    db.flush()
    device = Device(name="Pump", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32), owner_id=owner.id)
    db.add(device)
    db.flush()
    return device


def _anomalous_run(db, device, score=0.95):
    now = datetime.now(timezone.utc)
    for i in range(3):
        db.add(Telemetry(device_id=device.id, temperature=25.0, anomaly_score=score, is_anomaly=True,
                         recorded_at=now - timedelta(seconds=i)))
    db.flush()


def test_the_repeat_window_is_a_named_hour():
    assert alert_service.NOTIFY_COOLDOWN_SECONDS == 60 * 60


def test_the_first_breach_notifies_at_once_then_repeats_are_held(db, device, store, sent):
    _rule(db, device, "warning")
    for _ in range(5):
        alert_service.evaluate_rules(device, READING, db)
    assert len(sent["email"]) == 1
    assert sent["email"][0]["subject"] == "PHAEMOS [WARNING] Test ESP32"
    # the window key is taken with nx and an hour of life
    # the window is taken for the retry wait when the send is queued and extended to the hour once it went through
    window = [c for c in store.set_calls if ":email:" in c[0]]
    assert window and all(nx and ex == alert_service.FAILED_SEND_RETRY_SECONDS for _, nx, ex in window)
    assert all(ttl == 3600 for k, ttl in store.ttls.items() if ":email:" in k and "alert-notify" in k)


def _expire_window(store, channel):
    # the store has no clock, so a minute or an hour passing is the key running out
    for key in _window_keys(store, channel):
        store.expire_now(key)


def _tick(db, device, now, seconds):
    when = now + timedelta(seconds=seconds)
    alert_service.evaluate_rules(device, READING, db, now=when)
    return when


def test_the_window_ends(db, device, store, sent):
    # the window alone does not send again: a reminder needs the alert's own hour as well. Both must have passed
    t0 = datetime.now(timezone.utc)
    _rule(db, device, "warning")
    alert_service.evaluate_rules(device, READING, db, now=t0)
    assert len(sent["email"]) == 1
    # the window ends but the alert was told about a minute ago: no reminder
    _expire_window(store, "email")
    _tick(db, device, t0, 60)
    assert len(sent["email"]) == 1
    # an hour on with the window gone as well: the reminder goes
    _expire_window(store, "email")
    _tick(db, device, t0, alert_service.REMINDER_SECONDS)
    assert len(sent["email"]) == 2


def test_a_critical_breach_texts_once_per_window(db, store, sent):
    device = _owned_device(db)
    _rule(db, device, "critical")
    for _ in range(4):
        alert_service.evaluate_rules(device, READING, db)
    assert len(sent["sms"]) == 1
    assert sent["sms"][0]["phone_number"] == "+447700900000"
    assert len(sent["email"]) == 1


def test_each_device_and_metric_has_its_own_window(db, store, sent):
    device = _owned_device(db)
    _rule(db, device, "critical", "temperature")
    _rule(db, device, "critical", "humidity")
    alert_service.evaluate_rules(device, {"temperature": 99.0, "humidity": 99.0}, db)
    assert len(sent["sms"]) == 2
    other = _owned_device(db)
    _rule(db, other, "critical", "temperature")
    alert_service.evaluate_rules(other, READING, db)
    assert len(sent["sms"]) == 3


def test_a_warning_then_a_critical_on_one_metric_both_notify(db, device, store, sent):
    _rule(db, device, "warning")
    alert_service.evaluate_rules(device, READING, db)
    _rule(db, device, "critical")
    alert_service.evaluate_rules(device, READING, db)
    subjects = [mail["subject"] for mail in sent["email"]]
    assert "PHAEMOS [WARNING] Test ESP32" in subjects
    assert "PHAEMOS [CRITICAL] Test ESP32" in subjects


def test_a_breach_that_goes_on_keeps_one_alert_and_counts_the_readings(db, device, store, sent):
    _rule(db, device, "warning")
    for _ in range(3):
        alert_service.evaluate_rules(device, READING, db)
    # one row for the whole breach, updated in place
    alert = db.query(Alert).filter(Alert.device_id == device.id).one()
    assert alert.kind == "rule" and alert.occurrences == 3 and alert.last_value == 99.0 and alert.peak_value == 99.0


def test_info_alerts_send_no_email(db, device, store, sent):
    _rule(db, device, "info")
    alert_service.evaluate_rules(device, READING, db)
    assert sent["email"] == []


def test_no_alert_address_means_no_email_and_no_store_call(db, device, store, sent, monkeypatch):
    monkeypatch.setattr(settings, "alert_email_to", " , ")
    _rule(db, device, "warning")
    alert_service.evaluate_rules(device, READING, db)
    assert sent["email"] == []
    assert store.set_calls == []


def test_no_resend_key_means_no_email_and_no_store_call(db, device, store, sent, monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "placeholder")
    _rule(db, device, "warning")
    alert_service.evaluate_rules(device, READING, db)
    assert sent["email"] == []
    assert store.set_calls == []


def test_no_brevo_key_means_no_sms_and_no_store_call(db, store, sent, monkeypatch):
    monkeypatch.setattr(settings, "brevo_api_key", "")
    device = _owned_device(db)
    _rule(db, device, "critical")
    alert_service.evaluate_rules(device, READING, db)
    assert sent["sms"] == []
    assert all(":sms:" not in key for key, _, _ in store.set_calls)


def test_a_warning_never_texts(db, store, sent):
    device = _owned_device(db)
    _rule(db, device, "warning")
    alert_service.evaluate_rules(device, READING, db)
    assert sent["sms"] == []


def test_owner_without_a_phone_number_gets_no_text(db, store, sent):
    device = _owned_device(db, phone=None)
    _rule(db, device, "critical")
    alert_service.evaluate_rules(device, READING, db)
    assert sent["sms"] == []


# -- a failed send keeps a short window, not the whole hour and not none -----------------------------

def _window_keys(store, channel):
    return [k for k in store.values if f":{channel}:" in k and "alert-notify" in k]


def test_a_failed_email_is_not_retried_on_the_next_reading_but_after_a_minute(db, device, store, sent, forget_failed):
    t0 = datetime.now(timezone.utc)
    _rule(db, device, "warning")
    sent["result"] = False
    alert_service.evaluate_rules(device, READING, db, now=t0)
    # the failed send marks the alert as not yet told about, as the real hook does
    assert len(set(forget_failed())) == 1
    (key,) = _window_keys(store, "email")
    # the window now lives for a minute and no longer
    assert store.ttls[key] == alert_service.FAILED_SEND_RETRY_SECONDS == 60
    sent["result"] = True
    # the alert is open and untold, yet no reading inside the minute sends: the window holds
    for seconds in (5, 10, 15, 55):
        _tick(db, device, t0, seconds)
    assert len(sent["email"]) == 1
    # a minute on the window has run out: the next reading tries once and it goes through
    _expire_window(store, "email")
    t1 = _tick(db, device, t0, 61)
    assert len(sent["email"]) == 2
    assert store.ttls[key] == alert_service.NOTIFY_COOLDOWN_SECONDS
    # and from then no reading sends, even with the window gone, until the alert's hour is up
    _expire_window(store, "email")
    for seconds in (5, 10, 600, 3000):
        _tick(db, device, t1, seconds)
    assert len(sent["email"]) == 2
    _tick(db, device, t1, alert_service.REMINDER_SECONDS - 1)
    assert len(sent["email"]) == 2
    _tick(db, device, t1, alert_service.REMINDER_SECONDS)
    assert len(sent["email"]) == 3


def test_a_failed_text_waits_a_minute_before_the_next_try(db, store, sent, forget_failed):
    t0 = datetime.now(timezone.utc)
    device = _owned_device(db)
    _rule(db, device, "critical")
    sent["result"] = False
    alert_service.evaluate_rules(device, READING, db, now=t0)
    assert len(sent["sms"]) == 1
    assert len(set(forget_failed())) == 1
    sent["result"] = True
    for seconds in (5, 10, 30, 59):
        _tick(db, device, t0, seconds)
    assert len(sent["sms"]) == 1
    _expire_window(store, "sms")
    t1 = _tick(db, device, t0, 61)
    assert len(sent["sms"]) == 2
    # told now: nothing more per reading and a reminder only when the hour is up
    _expire_window(store, "sms")
    _tick(db, device, t1, 120)
    assert len(sent["sms"]) == 2
    _tick(db, device, t1, alert_service.REMINDER_SECONDS)
    assert len(sent["sms"]) == 3


def test_a_sender_that_raises_never_holds_the_hour(store):
    # the window is taken for the retry wait when a send is queued, as the dispatch does
    cooldown.acquire("k", alert_service.FAILED_SEND_RETRY_SECONDS)

    def boom(**kwargs):
        raise RuntimeError("down")

    alert_service._run_guarded("k", boom)
    # a send that raised leaves the window as it was queued: a minute and still held so it is not retried at once
    assert store.ttls["k"] == 60
    assert cooldown.acquire("k", 3600) is False
    # one that goes through extends it to the hour
    alert_service._run_guarded("k", lambda **kwargs: True)
    assert store.ttls["k"] == alert_service.NOTIFY_COOLDOWN_SECONDS


def test_shorten_cuts_a_key_in_redis_and_in_memory(store):
    cooldown.acquire("k", 3600)
    cooldown.shorten("k", 60)
    assert store.ttls["k"] == 60
    assert "k" in cooldown._local


def test_release_frees_a_key_in_redis_and_in_memory(store):
    assert cooldown.acquire("k", 60) is True
    assert cooldown.acquire("k", 60) is False
    cooldown.release("k")
    assert cooldown.acquire("k", 60) is True


# -- daily caps -----------------------------------------------------------------------------

def test_the_daily_email_cap_counts_recipients_and_stops_sends(db, store, sent, monkeypatch):
    monkeypatch.setattr(settings, "alert_email_to", "a@example.com, b@example.com")
    monkeypatch.setattr(settings, "alert_email_daily_cap", 4)
    devices = [_owned_device(db) for _ in range(3)]
    for d in devices:
        _rule(db, d, "warning")
        alert_service.evaluate_rules(d, READING, db)
    # two devices use the four slots, the third is skipped
    assert len(sent["email"]) == 2


def test_the_daily_sms_cap_stops_texts_across_devices(db, store, sent, monkeypatch):
    monkeypatch.setattr(settings, "alert_sms_daily_cap", 2)
    for _ in range(4):
        d = _owned_device(db)
        _rule(db, d, "critical")
        alert_service.evaluate_rules(d, READING, db)
    assert len(sent["sms"]) == 2


def test_the_cap_logs_one_warning_for_the_day(db, store, sent, monkeypatch, caplog):
    monkeypatch.setattr(settings, "alert_sms_daily_cap", 1)
    with caplog.at_level(logging.WARNING):
        for _ in range(4):
            d = _owned_device(db)
            _rule(db, d, "critical")
            alert_service.evaluate_rules(d, READING, db)
    assert caplog.text.count("alert sms paused until 00:00 UTC") == 1


# -- the daily cap is charged when the vendor accepts a message ----------------------------------

def test_a_failed_send_does_not_use_up_the_daily_cap(db, store, sent, monkeypatch):
    monkeypatch.setattr(settings, "alert_email_to", "a@example.com, b@example.com")
    monkeypatch.setattr(settings, "alert_email_daily_cap", 4)
    sent["result"] = False
    # a long vendor outage: many readings and many machines, every send fails
    for _ in range(10):
        d = _owned_device(db)
        _rule(db, d, "warning")
        alert_service.evaluate_rules(d, READING, db)
    assert cooldown.daily_used("email") == 0
    # the vendor comes back and every alert goes out up to the cap
    sent["result"] = True
    sent["email"].clear()
    for _ in range(3):
        d = _owned_device(db)
        _rule(db, d, "warning")
        alert_service.evaluate_rules(d, READING, db)
    assert len(sent["email"]) == 2
    assert cooldown.daily_used("email") == 4


def test_the_sms_cap_is_charged_on_acceptance_too(db, store, sent, monkeypatch):
    monkeypatch.setattr(settings, "alert_sms_daily_cap", 2)
    sent["result"] = False
    for _ in range(5):
        d = _owned_device(db)
        _rule(db, d, "critical")
        alert_service.evaluate_rules(d, READING, db)
    assert cooldown.daily_used("sms") == 0
    sent["result"] = True
    sent["sms"].clear()
    for _ in range(4):
        d = _owned_device(db)
        _rule(db, d, "critical")
        alert_service.evaluate_rules(d, READING, db)
    assert len(sent["sms"]) == 2


def test_reaching_the_cap_is_recorded_once_a_day_in_the_log_and_the_audit_log(db, store, sent, monkeypatch, caplog, cap_audit):
    monkeypatch.setattr(settings, "alert_email_daily_cap", 1)
    with caplog.at_level(logging.WARNING):
        for _ in range(4):
            d = _owned_device(db)
            _rule(db, d, "warning")
            alert_service.evaluate_rules(d, READING, db)
    assert caplog.text.count("alert email paused until 00:00 UTC: the daily limit of 1 was reached") == 1
    assert cap_audit == [("email", 1)]
    assert len(sent["email"]) == 1


def test_the_audit_entry_for_the_cap_says_what_happened(monkeypatch):
    # the real writer, with the database call stood in for by a recorder
    seen = []
    from app import db as db_module
    from app.services import audit_service

    class _Session:
        def close(self):
            seen.append("closed")

    monkeypatch.setattr(db_module, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(audit_service, "log_action", lambda *a, **k: seen.append(a))
    alert_service._REAL_WRITE_CAP_AUDIT("sms", 20)
    (call, closed) = seen
    assert call[1:] == (
        "system", "alert_cap_reached", "sms", None, "sms alerts paused until 00:00 UTC: the daily limit of 20 was reached",
    )
    assert closed == "closed"


def test_the_daily_count_key_expires_at_the_end_of_the_utc_day(store):
    now = datetime(2030, 3, 4, 22, 30, tzinfo=timezone.utc)
    assert cooldown.take_daily("sms", 5, now=now) is True
    key = "phaemos:alert-daily:sms:20300304"
    assert key in store.expire_at
    assert store.expire_at[key] == int(datetime(2030, 3, 5, tzinfo=timezone.utc).timestamp())


def test_a_new_utc_day_starts_the_count_again(store):
    day_one = datetime(2030, 3, 4, 23, 59, tzinfo=timezone.utc)
    day_two = day_one + timedelta(minutes=2)
    assert cooldown.take_daily("sms", 1, now=day_one) is True
    assert cooldown.take_daily("sms", 1, now=day_one) is False
    assert cooldown.take_daily("sms", 1, now=day_two) is True


def test_the_daily_cap_defaults():
    assert type(settings).model_fields["alert_email_daily_cap"].default == 50
    assert type(settings).model_fields["alert_sms_daily_cap"].default == 20


def test_an_unreachable_redis_falls_back_to_process_memory(db, device, sent, monkeypatch):
    def broken():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(cooldown, "_client", broken)
    cooldown._local.clear()
    cooldown._local_daily.clear()
    _rule(db, device, "warning")
    for _ in range(3):
        alert_service.evaluate_rules(device, READING, db)
    assert len(sent["email"]) == 1
    cooldown._local.clear()
    cooldown._local_daily.clear()


def test_the_daily_cap_also_holds_without_redis(monkeypatch):
    def broken():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(cooldown, "_client", broken)
    cooldown._local_daily.clear()
    results = [cooldown.take_daily("email", 2) for _ in range(3)]
    assert results == [True, True, False]
    cooldown._local_daily.clear()


def test_local_cooldown_expires(monkeypatch):
    clock = itertools.count(0, 100)
    monkeypatch.setattr(cooldown.time, "monotonic", lambda: next(clock))
    cooldown._local.clear()
    assert cooldown._acquire_local("k", 150) is True
    assert cooldown._acquire_local("k", 150) is False
    assert cooldown._acquire_local("k", 150) is True
    cooldown._local.clear()


# -- background dispatch -----------------------------------------------------------------------

def test_with_background_tasks_nothing_is_sent_until_the_tasks_run(db, store, sent):
    device = _owned_device(db)
    _rule(db, device, "critical")
    tasks = BackgroundTasks()
    alert_service.evaluate_rules(device, READING, db, tasks)
    assert sent["email"] == [] and sent["sms"] == []
    assert len(tasks.tasks) == 2
    import asyncio
    asyncio.run(tasks())
    assert len(sent["email"]) == 1 and len(sent["sms"]) == 1


# -- the anomaly path --------------------------------------------------------------------------

def test_a_critical_anomaly_emails_and_texts_the_owner(db, store, sent, old_three_in_a_row):
    device = _owned_device(db)
    _anomalous_run(db, device, score=0.95)
    alert_service.evaluate_anomaly(device, db)
    assert len(sent["email"]) == 1
    assert len(sent["anomaly_sms"]) == 1
    assert sent["anomaly_sms"][0]["phone_number"] == "+447700900000"
    assert sent["anomaly_sms"][0]["score"] == pytest.approx(0.95)
    assert any("anomaly" in key for key, _, _ in store.set_calls)


def test_a_warning_anomaly_emails_but_does_not_text(db, store, sent, old_three_in_a_row):
    device = _owned_device(db)
    _anomalous_run(db, device, score=0.75)
    alert_service.evaluate_anomaly(device, db)
    assert len(sent["email"]) == 1
    assert sent["anomaly_sms"] == []


def test_an_anomaly_is_held_by_the_same_window_and_caps(db, store, sent, monkeypatch, old_three_in_a_row):
    device = _owned_device(db)
    _anomalous_run(db, device)
    alert_service.evaluate_anomaly(device, db)
    # a fresh alert after the open one is resolved, inside the same window
    db.query(Alert).filter(Alert.device_id == device.id).update({"resolved": True})
    db.flush()
    alert_service.evaluate_anomaly(device, db)
    assert len(sent["email"]) == 1
    assert len(sent["anomaly_sms"]) == 1


def test_the_anomaly_text_names_the_device_and_score():
    text = sms_service._alert_text("Pump", "anomaly", f" (score {sms_service.format_number(0.91234)})")
    assert text == "PHAEMOS CRITICAL: anomaly on Pump (score 0.912)"


# -- ingest -----------------------------------------------------------------------------------

def test_ingest_still_sends_the_alert_email(client, db, device, store, stub_score, monkeypatch):
    order = []
    monkeypatch.setattr(notify_service, "send_discord_alert", lambda *a, **k: None)
    monkeypatch.setattr(alert_service.webhook_service, "notify_all", lambda *a, **k: None)
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(notify_service, "send_email_alert", lambda **k: order.append("email") or True)
    stub_score(0.1)
    _rule(db, device, "warning")
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), "temperature": 99.0},
        headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == 201
    assert order == ["email"]


def test_the_live_broadcast_is_queued_before_the_vendor_tasks(client, db, device, store, stub_score, monkeypatch):
    order = []
    monkeypatch.setattr(notify_service, "send_discord_alert", lambda *a, **k: None)
    monkeypatch.setattr(alert_service.webhook_service, "notify_all", lambda *a, **k: None)
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(notify_service, "send_email_alert", lambda **k: order.append("email") or True)

    async def fake_broadcast(device_id, payload):
        order.append("broadcast")

    monkeypatch.setattr("app.routes.telemetry.ws_manager.broadcast", fake_broadcast)
    stub_score(0.1)
    _rule(db, device, "warning")
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), "temperature": 99.0},
        headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == 201
    assert order == ["broadcast", "email"]


def test_a_resend_failure_does_not_break_ingest(client, db, device, store, stub_score, monkeypatch):
    monkeypatch.setattr(notify_service, "send_discord_alert", lambda *a, **k: None)
    monkeypatch.setattr(alert_service.webhook_service, "notify_all", lambda *a, **k: None)
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")

    def boom(params):
        raise RuntimeError("resend is down")

    monkeypatch.setattr(email_service.resend.Emails, "send", staticmethod(boom))
    stub_score(0.1)
    _rule(db, device, "warning")
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), "temperature": 99.0},
        headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == 201
    # the failed send keeps its window for a minute and no longer, so the next reading does not retry at once
    # and a retry is not held for the whole hour
    ttls = [ttl for k, ttl in store.ttls.items() if "alert-notify:email" in k]
    assert ttls and all(ttl <= alert_service.FAILED_SEND_RETRY_SECONDS for ttl in ttls)


def test_a_brevo_failure_does_not_break_ingest(client, db, store, stub_score, monkeypatch):
    monkeypatch.setattr(notify_service, "send_discord_alert", lambda *a, **k: None)
    monkeypatch.setattr(alert_service.webhook_service, "notify_all", lambda *a, **k: None)
    monkeypatch.setattr(settings, "alert_email_to", "")
    monkeypatch.setattr(settings, "brevo_api_key", "test-brevo-key")
    monkeypatch.setattr(settings, "brevo_sms_sender", "PHAEMOS")
    real_client = httpx.Client

    def factory(*args, **kwargs):
        def boom(request):
            raise httpx.ConnectTimeout("timed out", request=request)
        kwargs["transport"] = httpx.MockTransport(boom)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(sms_service.httpx, "Client", factory)
    stub_score(0.1)
    device = _owned_device(db)
    _rule(db, device, "critical")
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), "temperature": 99.0},
        headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == 201
