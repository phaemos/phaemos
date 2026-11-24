"""
A Redis that is slow but not down must not hold the telemetry request on every window check.
"""

import time

import pytest

from app.services import cooldown


class _Hanging:
    # a Redis that never answers: every call fails after what a socket timeout would cost, which the test counts
    def __init__(self):
        self.calls = 0

    def set(self, *a, **k):
        self.calls += 1
        raise TimeoutError("timed out")

    delete = incrby = set

    def expireat(self, *a, **k):
        self.calls += 1
        raise TimeoutError("timed out")


@pytest.fixture
def hung(monkeypatch):
    fake = _Hanging()
    monkeypatch.setattr(cooldown, "_client", lambda: fake)
    cooldown._local.clear()
    cooldown._local_daily.clear()
    yield fake
    cooldown._local.clear()
    cooldown._local_daily.clear()


def test_after_one_failure_redis_is_not_tried_again_for_a_while(hung):
    assert cooldown.acquire("k1", 60) is True
    assert hung.calls == 1
    # four more checks in the same request: none of them touches Redis
    assert cooldown.acquire("k2", 60) is True
    assert cooldown.take_daily("email", 50) is True
    cooldown.release("k2")
    assert cooldown.acquire("k3", 60) is True
    assert hung.calls == 1


def test_the_windows_still_work_from_process_memory_while_redis_is_skipped(hung):
    assert cooldown.acquire("window", 3600) is True
    assert cooldown.acquire("window", 3600) is False
    assert cooldown.take_daily("sms", 2) is True
    assert cooldown.take_daily("sms", 2) is True
    assert cooldown.take_daily("sms", 2) is False


def test_redis_is_tried_again_once_the_pause_is_over(hung, monkeypatch):
    cooldown.acquire("k1", 60)
    assert hung.calls == 1
    monkeypatch.setattr(cooldown, "_redis_down_until", time.monotonic() - 1)
    cooldown.acquire("k2", 60)
    assert hung.calls == 2


def test_a_whole_breached_rule_costs_one_redis_call_not_five(db, device, hung, monkeypatch):
    # the request path of a breached rule: the Discord, email and webhook windows and the daily cap
    from app.config import settings
    from app.models.alert import AlertRule
    from app.models.webhook import Webhook
    from app.services import alert_service

    monkeypatch.setattr(settings, "discord_webhook_url", "https://discord.com/api/webhooks/1/x")
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    db.add(Webhook(name="Ops", url="https://hooks.slack.com/services/T/B/x", enabled=True))
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric="temperature", condition="gt", threshold=50.0, severity="warning"))
    db.flush()
    from fastapi import BackgroundTasks
    alert_service.evaluate_rules(device, {"temperature": 99.0}, db, BackgroundTasks())
    assert hung.calls == 1
