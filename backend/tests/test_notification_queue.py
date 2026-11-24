"""
Discord and webhook calls leave the ingest request. They are queued like email and SMS and follow the same hourly
repeat window per device, metric and severity.
"""

import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import BackgroundTasks

from app.config import settings
from app.models.alert import AlertRule
from app.models.device import Device
from app.models.webhook import Webhook
from app.services import alert_service, cooldown, notify_pool, notify_service, webhook_service
from tests.test_alert_notifications import FakeRedis

READING = {"temperature": 99.0}


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
def calls(monkeypatch):
    # what would have gone to Discord and to the webhooks. Nothing here reaches the network
    log = {"discord": [], "webhook": []}
    monkeypatch.setattr(settings, "discord_webhook_url", "https://discord.com/api/webhooks/1/test-token")
    monkeypatch.setattr(notify_service, "send_discord_alert", lambda **k: log["discord"].append(k) or True)
    monkeypatch.setattr(
        webhook_service, "_deliver",
        lambda wh, body, *a, **k: log["webhook"].append((wh.name, json.loads(body))) or webhook_service.Outcome(True, 200),
    )
    return log


def _rule(db, device, severity="warning", metric="temperature"):
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric=metric, condition="gt", threshold=50.0, severity=severity))
    db.flush()


def _webhook(db, name="Ops", enabled=True, url="https://hooks.slack.com/services/T/B/x"):
    db.add(Webhook(name=name, url=url, enabled=enabled))
    db.flush()


def _run(tasks):
    asyncio.run(tasks())


def test_discord_and_webhooks_are_queued_and_not_called_in_the_request(db, device, store, calls):
    _rule(db, device)
    _webhook(db)
    tasks = BackgroundTasks()
    alert_service.evaluate_rules(device, READING, db, tasks)
    # queued, nothing sent yet
    assert calls == {"discord": [], "webhook": []}
    assert len(tasks.tasks) == 2
    _run(tasks)
    assert len(calls["discord"]) == 1
    assert calls["discord"][0]["severity"] == "warning"
    assert "temperature is 99.0" in calls["discord"][0]["message"]
    assert [name for name, _ in calls["webhook"]] == ["Ops"]


def test_the_webhook_is_read_while_the_session_is_open(db, device, store, calls, monkeypatch):
    _rule(db, device)
    _webhook(db, name="Slack")
    jobs = []
    monkeypatch.setattr(notify_pool, "submit", lambda job, critical=False, undo=None: jobs.append(job) or True)
    tasks = BackgroundTasks()
    alert_service.evaluate_rules(device, READING, db, tasks)
    _run(tasks)
    # each vendor call is handed to the pool as _run_guarded(key, function, **kwargs)
    job = [j for j in jobs if j.args[1] is webhook_service.deliver_all][0]
    (target,) = job.keywords["targets"]
    # plain values, so the task does not need the closed session
    assert isinstance(target, webhook_service.WebhookTarget) and target.name == "Slack"
    assert job.keywords["alert_context"]["metric"] == "temperature"


def test_a_breach_that_stays_breached_calls_each_channel_once_an_hour(db, device, store, calls):
    _rule(db, device)
    _webhook(db)
    for _ in range(6):
        tasks = BackgroundTasks()
        alert_service.evaluate_rules(device, READING, db, tasks)
        _run(tasks)
    assert len(calls["discord"]) == 1
    assert len(calls["webhook"]) == 1
    keys = [c[0] for c in store.set_calls if "alert-notify" in c[0]]
    assert any(":discord:" in k for k in keys) and any(":webhook:" in k for k in keys)
    window = [c for c in store.set_calls if ":discord:" in c[0] or ":webhook:" in c[0]]
    assert all(nx and ex == 60 for _, nx, ex in window)
    assert all(ttl == 3600 for k, ttl in store.ttls.items() if ":discord:" in k or ":webhook:" in k)


def test_the_window_ends(db, device, store, calls):
    # the window alone does not send again: the alert must also be due its hourly reminder
    t0 = datetime.now(timezone.utc)
    _rule(db, device)
    _webhook(db)
    alert_service.evaluate_rules(device, READING, db, now=t0)
    assert len(calls["discord"]) == 1 and len(calls["webhook"]) == 1
    keys = [k for k in store.values if "alert-notify" in k and (":discord:" in k or ":webhook:" in k)]
    for key in keys:
        store.expire_now(key)
    alert_service.evaluate_rules(device, READING, db, now=t0 + timedelta(seconds=60))
    assert len(calls["discord"]) == 1 and len(calls["webhook"]) == 1
    alert_service.evaluate_rules(device, READING, db, now=t0 + timedelta(seconds=alert_service.REMINDER_SECONDS))
    assert len(calls["discord"]) == 2 and len(calls["webhook"]) == 2


def test_each_device_metric_and_severity_has_its_own_window(db, device, store, calls):
    other = Device(name="Other", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32))
    db.add(other)
    db.flush()
    _rule(db, device, "warning", "temperature")
    _rule(db, device, "critical", "humidity")
    _rule(db, other, "warning", "temperature")
    _webhook(db)
    alert_service.evaluate_rules(device, {"temperature": 99.0, "humidity": 99.0}, db)
    alert_service.evaluate_rules(other, READING, db)
    assert len(calls["discord"]) == 3
    assert len(calls["webhook"]) == 3


def test_a_failed_send_is_not_retried_within_a_minute_and_is_retried_after_it(
    db, device, store, calls, monkeypatch, forget_failed
):
    t0 = datetime.now(timezone.utc)
    _rule(db, device)
    attempts = []

    def fail_then_work(**kwargs):
        attempts.append(kwargs)
        return len(attempts) > 1

    monkeypatch.setattr(notify_service, "send_discord_alert", fail_then_work)
    alert_service.evaluate_rules(device, READING, db, now=t0)
    # the failed send marks the alert as not yet told about, as the real hook does
    assert len(set(forget_failed())) == 1
    (key,) = [k for k in store.values if ":discord:" in k]
    # the failed send leaves the window with at most a minute to live
    assert store.ttls[key] <= alert_service.FAILED_SEND_RETRY_SECONDS == 60
    # the readings inside that minute do not try again, though the alert is untold
    for seconds in (5, 10, 59):
        alert_service.evaluate_rules(device, READING, db, now=t0 + timedelta(seconds=seconds))
    assert len(attempts) == 1
    # the minute passes (the key runs out) and the next reading tries again and succeeds
    store.expire_now(key)
    t1 = t0 + timedelta(seconds=61)
    alert_service.evaluate_rules(device, READING, db, now=t1)
    assert len(attempts) == 2
    # a success holds for the hour again
    assert store.ttls[key] == alert_service.NOTIFY_COOLDOWN_SECONDS
    alert_service.evaluate_rules(device, READING, db, now=t1 + timedelta(seconds=5))
    assert len(attempts) == 2


def test_an_info_alert_sends_no_discord_but_still_reaches_webhooks(db, device, store, calls):
    _rule(db, device, "info")
    _webhook(db)
    alert_service.evaluate_rules(device, READING, db)
    assert calls["discord"] == []
    assert len(calls["webhook"]) == 1


def test_nothing_is_queued_when_neither_channel_is_set_up(db, device, store, monkeypatch):
    monkeypatch.setattr(settings, "discord_webhook_url", "")
    _rule(db, device)
    _webhook(db, enabled=False)
    tasks = BackgroundTasks()
    alert_service.evaluate_rules(device, READING, db, tasks)
    assert tasks.tasks == []
    # and no window was spent on nothing
    assert not [c for c in store.set_calls if ":discord:" in c[0] or ":webhook:" in c[0]]


def test_a_bad_webhook_template_no_longer_breaks_the_request(db, device, store, caplog):
    # a template naming a placeholder that does not exist used to raise inside the ingest request;
    # it now raises inside a guarded task, which logs it and leaves the window with at most a minute to live
    db.add(Webhook(name="Bad", url="https://hooks.slack.com/services/T/B/x", enabled=True, template="{nope}"))
    db.flush()
    _rule(db, device)
    tasks = BackgroundTasks()
    alert_service.evaluate_rules(device, READING, db, tasks)
    with caplog.at_level("WARNING"):
        _run(tasks)
    # a template saved before it was checked is refused when the message is built (the save now refuses it, so this one is old)
    assert "ValueError" in caplog.text
    # deliver_all returned False because nothing was delivered, so the window is cut to the retry wait
    (key,) = [k for k in store.values if ":webhook:" in k]
    assert store.ttls[key] <= alert_service.FAILED_SEND_RETRY_SECONDS


def test_the_anomaly_alert_queues_discord_with_its_own_window(db, device, store, calls, old_three_in_a_row):
    from datetime import datetime, timedelta, timezone
    from app.models.telemetry import Telemetry

    now = datetime.now(timezone.utc)
    for i in range(3):
        db.add(Telemetry(device_id=device.id, temperature=25.0, anomaly_score=0.8, is_anomaly=True,
                         recorded_at=now - timedelta(seconds=i)))
    db.flush()
    tasks = BackgroundTasks()
    alert_service.evaluate_anomaly(device, db, tasks)
    assert calls["discord"] == []
    _run(tasks)
    assert len(calls["discord"]) == 1
    assert any(":discord:" in c[0] and ":anomaly:" in c[0] for c in store.set_calls)


def test_discord_returns_true_only_once_discord_accepted_it(monkeypatch):
    monkeypatch.setattr(settings, "discord_webhook_url", "https://discord.com/api/webhooks/1/test-token")
    real_client = httpx.Client
    status = {"code": 204}

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(status["code"]))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(notify_service.httpx, "Client", factory)
    assert notify_service.send_discord_alert("hot", "critical") is True
    status["code"] = 500
    assert notify_service.send_discord_alert("hot", "critical") is False
    assert notify_service.send_discord_alert("hot", "info") is False


def test_an_ingest_post_still_reaches_both_channels_through_background_tasks(client, db, device, store, calls, monkeypatch):
    _rule(db, device)
    _webhook(db)
    delivered = []
    original = webhook_service.deliver_all

    def traced(targets, alert_context):
        delivered.append(alert_context["metric"])
        return original(targets, alert_context)

    monkeypatch.setattr(webhook_service, "deliver_all", traced)
    res = client.post("/api/v1/telemetry", json={"device_id": str(device.id), "temperature": 99.0}, headers={"X-API-Key": device.api_key})
    assert res.status_code == 201
    assert delivered == ["temperature"]
    assert len(calls["discord"]) == 1
    assert len(calls["webhook"]) == 1
