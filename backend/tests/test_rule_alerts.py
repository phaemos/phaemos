"""
Stateful rule alerts (one open alert per machine and rule) and the wiring of the model's anomaly decision.
The clock is passed in, so nothing waits and the anomaly decision is stubbed, so nothing depends on the model's maths.
"""

import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

from app.config import settings
from app.models.alert import Alert, AlertRule, RuleState
from app.models.device import Device
from app.models.maintenance import MaintenanceWindow
from app.models.telemetry import Telemetry
from app.models.ticket import Ticket
from app.schemas.alert import AlertResponse
from app.services import alert_service, cooldown, liveness_service, notify_service, rule_metrics
from app.services.anomaly_decision import Decision
from tests.test_alert_notifications import FakeRedis, _owned_device

T0 = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _at(seconds):
    return T0 + timedelta(seconds=seconds)


def _rule(db, device, metric="temperature", condition="gt", threshold=50.0, severity="warning", for_s=30, margin=None):
    rule = AlertRule(
        device_id=device.id, metric=metric, condition=condition, threshold=threshold, severity=severity,
        for_seconds=for_s, clear_margin=margin,
    )
    db.add(rule)
    db.flush()
    return rule


def _eval(db, device, seconds, **reading):
    alert_service.evaluate_rules(device, reading, db, None, now=_at(seconds))


def _feed(db, device, start, end, step=10, **reading):
    """Readings from `start` to `end` inclusive, a step apart (never more than the gap that breaks a hold)."""
    for seconds in list(range(start, end, step)) + [end]:
        _eval(db, device, seconds, **reading)


def _alerts(db, device, **filters):
    return db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "rule").filter_by(**filters).all()


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


# -- raising ------------------------------------------------------------------------------------------------

def test_a_number_must_hold_for_the_whole_hold_before_the_alert_is_raised(db, device):
    _rule(db, device, for_s=30)
    for seconds in (0, 5, 10, 25, 29):
        _eval(db, device, seconds, temperature=99.0)
    assert _alerts(db, device) == []
    _eval(db, device, 30, temperature=99.0)
    (alert,) = _alerts(db, device)
    assert alert.kind == "rule" and alert.category == "machine" and alert.rule_id is not None
    # the five readings of the hold count as well as the one that raised it
    assert alert.occurrences == 6 and alert.last_value == 99.0 and alert.peak_value == 99.0
    assert alert.first_seen_at == _at(0) and alert.triggered_at == _at(30)
    assert alert.message == f"temperature is 99.0 (gt 50.0) on {device.name}"


def test_the_default_hold_is_thirty_seconds_for_a_number_and_none_for_an_on_or_off_reading(db, device):
    _rule(db, device, for_s=None)
    _rule(db, device, metric="gas_alert", condition="eq", threshold=1.0, severity="critical", for_s=None)
    assert rule_metrics.default_for_seconds("temperature") == 30
    assert rule_metrics.default_for_seconds("gas_alert") == 0 and rule_metrics.default_for_seconds("water_detected") == 0
    assert rule_metrics.default_for_seconds("vib_clipping") == 0
    _eval(db, device, 0, temperature=99.0, gas_alert=True)
    # the gas rule raised at once and the temperature rule is still waiting
    (alert,) = _alerts(db, device)
    assert "gas_alert" in alert.message
    _eval(db, device, 29, temperature=99.0, gas_alert=True)
    assert len(_alerts(db, device)) == 1
    _eval(db, device, 30, temperature=99.0, gas_alert=True)
    assert len(_alerts(db, device)) == 2


def test_a_hold_of_zero_raises_at_once(db, device):
    _rule(db, device, for_s=0)
    _eval(db, device, 0, temperature=99.0)
    assert len(_alerts(db, device)) == 1


def test_a_dip_back_inside_the_limit_restarts_the_hold(db, device):
    _rule(db, device, for_s=30)
    for seconds in (0, 10, 20):
        _eval(db, device, seconds, temperature=99.0)
    _eval(db, device, 25, temperature=10.0)
    for seconds in (30, 40, 50, 54):
        _eval(db, device, seconds, temperature=99.0)
    assert _alerts(db, device) == []
    _eval(db, device, 60, temperature=99.0)
    assert len(_alerts(db, device)) == 1


def test_a_gap_in_the_readings_is_not_the_condition_lasting(db, device):
    _rule(db, device, for_s=30)
    _eval(db, device, 0, temperature=99.0)
    _eval(db, device, 5, temperature=99.0)
    # the node was silent for 95 seconds: the hold starts again from this reading
    _eval(db, device, 100, temperature=99.0)
    _eval(db, device, 129, temperature=99.0)
    assert _alerts(db, device) == []
    _eval(db, device, 130, temperature=99.0)
    assert len(_alerts(db, device)) == 1


def test_a_value_sitting_on_the_threshold_does_not_breach(db, device):
    _rule(db, device, for_s=0)
    _eval(db, device, 0, temperature=50.0)
    assert _alerts(db, device) == []


def test_a_reading_without_the_metric_breaks_a_pending_hold(db, device):
    _rule(db, device, for_s=30)
    _eval(db, device, 0, temperature=99.0)
    _eval(db, device, 10, temperature=None)
    _eval(db, device, 20, temperature=99.0)
    _eval(db, device, 49, temperature=99.0)
    assert _alerts(db, device) == []
    _eval(db, device, 50, temperature=99.0)
    assert len(_alerts(db, device)) == 1


def test_the_hold_is_kept_in_the_database_so_a_restart_does_not_lose_it(db, device):
    rule = _rule(db, device, for_s=30)
    _eval(db, device, 0, temperature=99.0)
    state = db.get(RuleState, rule.id)
    assert state.breach_since == _at(0)
    # a restart: nothing in memory, only the row
    db.expire_all()
    _eval(db, device, 30, temperature=99.0)
    assert len(_alerts(db, device)) == 1


def test_the_tracking_does_not_grow_with_the_readings(db, device):
    _rule(db, device, for_s=0)
    for seconds in range(0, 1000, 5):
        _eval(db, device, seconds, temperature=99.0)
    assert db.query(RuleState).filter(RuleState.device_id == device.id).count() == 1
    (alert,) = _alerts(db, device)
    assert alert.occurrences == 200


def test_the_peak_the_count_and_the_first_time_cover_the_qualifying_period(db, device):
    # the machine reached 39.1 thirty seconds before the alert was raised. The alert must say so: an operator reading a lower peak
    # would be misled
    _rule(db, device, threshold=36.0, for_s=30)
    for seconds, value in ((0, 36.5), (5, 37.0), (10, 38.2), (15, 39.1), (20, 38.0), (25, 37.5), (30, 36.9)):
        _eval(db, device, seconds, temperature=value)
    (alert,) = _alerts(db, device)
    assert alert.peak_value == 39.1
    assert alert.occurrences == 7
    assert alert.first_seen_at == _at(0)
    assert alert.last_value == 36.9
    # the alert goes on counting from there
    _eval(db, device, 35, temperature=40.0)
    db.refresh(alert)
    assert alert.occurrences == 8 and alert.peak_value == 40.0
    state = db.query(RuleState).filter(RuleState.device_id == device.id).one()
    assert state.hold_count == 0 and state.hold_peak is None and state.breach_since is None


def test_a_broken_hold_starts_its_figures_again(db, device):
    _rule(db, device, threshold=36.0, for_s=30)
    for seconds, value in ((0, 45.0), (5, 44.0), (10, 20.0)):
        _eval(db, device, seconds, temperature=value)
    # the hold broke at 10: the 45.0 does not belong to the next one
    for seconds in (15, 20, 25, 30, 35, 40, 45):
        _eval(db, device, seconds, temperature=37.0)
    (alert,) = _alerts(db, device)
    assert alert.peak_value == 37.0 and alert.first_seen_at == _at(15) and alert.occurrences == 7


def test_a_lower_limit_rule_keeps_the_lowest_value_of_the_hold(db, device):
    _rule(db, device, metric="humidity", condition="lt", threshold=30.0, for_s=20)
    for seconds, value in ((0, 25.0), (5, 12.0), (10, 20.0), (15, 22.0), (20, 24.0)):
        _eval(db, device, seconds, humidity=value)
    (alert,) = _alerts(db, device)
    assert alert.peak_value == 12.0 and alert.occurrences == 5


# -- one alert for each machine and rule, updated in place ---------------------------------------------------

def test_the_open_alert_is_updated_in_place(db, device):
    _rule(db, device, for_s=0)
    for seconds, value in ((0, 60.0), (5, 80.0), (10, 70.0)):
        _eval(db, device, seconds, temperature=value)
    (alert,) = _alerts(db, device)
    assert (alert.occurrences, alert.last_value, alert.peak_value) == (3, 70.0, 80.0)
    assert alert.last_seen_at == _at(10)
    # the message and the start time stay as raised
    assert alert.message.startswith("temperature is 60.0")


def test_the_peak_of_a_lower_limit_rule_is_the_lowest_value(db, device):
    _rule(db, device, metric="humidity", condition="lt", threshold=30.0, for_s=0)
    for seconds, value in ((0, 20.0), (5, 5.0), (10, 12.0)):
        _eval(db, device, seconds, humidity=value)
    (alert,) = _alerts(db, device)
    assert alert.peak_value == 5.0 and alert.last_value == 12.0


def test_each_rule_has_its_own_alert_and_another_machine_its_own(db, device):
    _rule(db, device, for_s=0)
    _rule(db, device, metric="humidity", threshold=40.0, for_s=0)
    other = Device(name="other", api_key=secrets.token_urlsafe(16))
    db.add(other)
    db.flush()
    _rule(db, other, for_s=0)
    _eval(db, device, 0, temperature=99.0, humidity=99.0)
    _eval(db, device, 5, temperature=99.0, humidity=99.0)
    _eval(db, other, 0, temperature=99.0)
    assert len(_alerts(db, device)) == 2 and len(_alerts(db, other)) == 1
    assert sorted(a.occurrences for a in _alerts(db, device)) == [2, 2]


def test_the_database_refuses_a_second_open_alert_for_a_rule_but_not_for_another_rule(db, device):
    first = _rule(db, device)
    second = _rule(db, device, metric="humidity")

    def make(rule):
        return Alert(device_id=device.id, rule_id=rule.id, message="x", severity="warning", resolved=False, kind="rule")

    db.add_all([make(first), make(second)])
    db.flush()
    db.add(make(first))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_a_resolved_alert_does_not_block_a_new_one(db, device):
    _rule(db, device, for_s=0, margin=1.0)
    _eval(db, device, 0, temperature=99.0)
    _feed(db, device, 5, 70, temperature=10.0)
    assert len(_alerts(db, device, resolved=True)) == 1
    _eval(db, device, 100, temperature=99.0)
    assert len(_alerts(db, device)) == 2 and len(_alerts(db, device, resolved=False)) == 1


# -- resolving -------------------------------------------------------------------------------------------------

def _open(db, device, **rule_kwargs):
    rule = _rule(db, device, for_s=0, **rule_kwargs)
    _eval(db, device, 0, temperature=99.0)
    (alert,) = _alerts(db, device)
    return rule, alert


def test_the_alert_resolves_after_the_value_has_been_back_inside_by_the_margin_for_a_minute(db, device):
    _, alert = _open(db, device)
    # the default margin for 50.0 is 1.0, so 49.0 is inside and 49.5 is not
    _feed(db, device, 10, 69, temperature=49.0)
    assert alert.resolved is False
    _eval(db, device, 70, temperature=49.0)
    assert alert.resolved is True and alert.resolved_at == _at(70)
    assert alert.message.endswith("(resolved: back inside the limit)")


def test_a_value_between_the_threshold_and_the_margin_neither_occurs_nor_clears(db, device):
    _, alert = _open(db, device)
    _feed(db, device, 10, 40, temperature=49.0)
    # 49.5 is under the threshold but not inside by the margin: the clear hold starts again
    _eval(db, device, 50, temperature=49.5)
    _feed(db, device, 60, 119, temperature=49.0)
    assert alert.resolved is False
    _eval(db, device, 120, temperature=49.0)
    assert alert.resolved is True
    # and it did not count as occurring
    assert alert.occurrences == 1


def test_a_value_exactly_on_the_threshold_is_not_inside(db, device):
    _, alert = _open(db, device)
    _feed(db, device, 10, 200, temperature=50.0)
    assert alert.resolved is False


def test_the_breach_coming_back_restarts_the_clear_hold(db, device):
    _, alert = _open(db, device)
    _feed(db, device, 10, 40, temperature=10.0)
    _eval(db, device, 50, temperature=99.0)
    _feed(db, device, 60, 119, temperature=10.0)
    assert alert.resolved is False
    _eval(db, device, 120, temperature=10.0)
    assert alert.resolved is True
    assert alert.occurrences == 2


def test_an_explicit_margin_and_a_longer_hold_are_used(db, device):
    rule = _rule(db, device, for_s=120, margin=5.0)
    _feed(db, device, 0, 120, temperature=99.0)
    (alert,) = _alerts(db, device)
    # 46 is back under the limit but not inside by the margin of 5
    _feed(db, device, 130, 400, temperature=46.0)
    assert alert.resolved is False
    _eval(db, device, 410, temperature=45.0)
    # the clear hold is for_seconds (120) because that is longer than a minute
    _feed(db, device, 420, 529, temperature=45.0)
    assert alert.resolved is False
    _eval(db, device, 530, temperature=45.0)
    assert alert.resolved is True and rule.clear_margin == 5.0


def test_a_lower_limit_rule_clears_above_the_threshold_plus_the_margin(db, device):
    _rule(db, device, metric="humidity", condition="lt", threshold=10.0, for_s=0)
    _eval(db, device, 0, humidity=2.0)
    (alert,) = _alerts(db, device)
    # the margin is 2 per cent of 10.0 and never under 0.1, so a value has to reach about 10.2 to be inside
    _feed(db, device, 10, 100, humidity=10.15)
    assert alert.resolved is False
    _eval(db, device, 110, humidity=10.3)
    _feed(db, device, 120, 169, humidity=10.3)
    assert alert.resolved is False
    _eval(db, device, 170, humidity=10.3)
    assert alert.resolved is True


def test_an_equality_rule_clears_when_the_value_differs(db, device):
    _rule(db, device, metric="gas_alert", condition="eq", threshold=1.0, severity="critical", for_s=None)
    _eval(db, device, 0, gas_alert=True)
    (alert,) = _alerts(db, device)
    _feed(db, device, 10, 69, gas_alert=False)
    assert alert.resolved is False
    _eval(db, device, 70, gas_alert=False)
    assert alert.resolved is True


@pytest.mark.parametrize("threshold,expected", [(50.0, 1.0), (0.55, 0.011), (1.0, 0.1), (0.0, 0.1), (-80.0, 1.6), (1000.0, 20.0)])
def test_the_default_margin_is_two_per_cent_and_never_under_one_unit_of_the_last_decimal(threshold, expected):
    assert rule_metrics.default_clear_margin(threshold) == pytest.approx(expected)


# -- notifications: on raise, on a rise to critical and as an hourly reminder, never per reading -----------

def test_one_notification_on_the_raise_and_none_for_the_readings_after(db, device, mail):
    _rule(db, device, for_s=0)
    for seconds in range(0, 100, 5):
        _eval(db, device, seconds, temperature=99.0)
    assert len(mail) == 1 and "temperature is 99.0" in mail[0]["body"]


def test_a_rise_to_critical_notifies_once_and_updates_the_one_alert(db, device, mail, store):
    rule = _rule(db, device, for_s=0, severity="warning")
    _eval(db, device, 0, temperature=99.0)
    rule.severity = "critical"
    db.flush()
    # the email window is held for the hour after the first send, so it is opened to see the second notification
    for key in [k for k in store.values if ":email:" in k]:
        store.expire_now(key)
    _eval(db, device, 5, temperature=99.0)
    _eval(db, device, 10, temperature=99.0)
    (alert,) = _alerts(db, device)
    assert alert.severity == "critical"
    assert [m["subject"] for m in mail] == [f"PHAEMOS [WARNING] {device.name}", f"PHAEMOS [CRITICAL] {device.name}"]
    assert mail[1]["body"].endswith("(now critical)")


def test_a_reminder_goes_once_an_hour_while_the_alert_stays_open(db, device, monkeypatch):
    _rule(db, device, for_s=0)
    told = []
    monkeypatch.setattr(alert_service, "_tell_about_rule_alert",
                        lambda bt, db_, dev, rule, alert, text_, now, reason="raised": told.append(text_) or setattr(alert, "notified_at", now))
    _eval(db, device, 0, temperature=99.0)
    assert len(told) == 1
    for seconds in (5, 600, 3599):
        _eval(db, device, seconds, temperature=99.0)
    assert len(told) == 1
    _eval(db, device, 3600, temperature=99.0)
    assert len(told) == 2 and "still occurring" in told[1] and "peak 99.0" in told[1]


def test_no_notification_while_the_condition_has_gone(db, device, monkeypatch):
    _, alert = _open(db, device)
    alert.notified_at = _at(0)
    told = []
    monkeypatch.setattr(alert_service, "_tell_about_rule_alert", lambda *a, **k: told.append(1))
    _eval(db, device, 4000, temperature=10.0)
    assert told == []


def test_a_failed_notification_marks_the_alert_so_the_next_reading_sends_again(db, device, store, monkeypatch, notification_reset_recorder):
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    sent = []
    monkeypatch.setattr(notify_service, "send_email_alert", lambda **k: sent.append(k) or False)
    _rule(db, device, for_s=0)
    _eval(db, device, 0, temperature=99.0)
    (alert,) = _alerts(db, device)
    assert notification_reset_recorder == [alert.id]
    # the 60 second window then lets the next reading try again and it does
    alert.notified_at = None
    for key in [k for k in store.values if ":email:" in k]:
        store.expire_now(key)
    _eval(db, device, 70, temperature=99.0)
    assert len(sent) == 2


def test_the_forget_hook_clears_notified_at_in_its_own_session(db, device, monkeypatch):
    from app import db as db_module

    seen = []

    class _Session:
        def execute(self, stmt):
            seen.append(str(stmt))

        def commit(self):
            seen.append("commit")

        def close(self):
            seen.append("close")

    monkeypatch.setattr(db_module, "SessionLocal", lambda: _Session())
    alert_service._REAL_FORGET_NOTIFICATION(device.id)
    assert "UPDATE alerts SET notified_at" in seen[0]
    assert seen[1:] == ["commit", "close"]
    assert alert_service._failure_hook(None) is None
    assert alert_service._failure_hook(device.id) is not None


# -- unavailable field, silent node, rule edits and deletes -----------------------------------------------

def test_an_open_alert_whose_field_became_unavailable_stays_but_stops_moving(db, device):
    _, alert = _open(db, device)
    _feed(db, device, 10, 200, temperature=None)
    assert alert.resolved is False and alert.last_seen_at == _at(0) and alert.occurrences == 1


def test_the_sweep_closes_a_rule_alert_whose_readings_stopped_for_an_hour(db, device):
    _, alert = _open(db, device)
    liveness_service.sweep(db, now=_at(3599), started_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert alert.resolved is False
    summary = liveness_service.sweep(db, now=_at(3601), started_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert alert.resolved is True and alert.message.endswith("(closed: no reading met the condition for an hour)")
    assert summary["alerts_resolved"] >= 1


def test_the_sweep_leaves_a_live_rule_alert_alone(db, device):
    _, alert = _open(db, device)
    for seconds in range(5, 4000, 300):
        _eval(db, device, seconds, temperature=99.0)
    liveness_service.sweep(db, now=_at(3900), started_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert alert.resolved is False


def test_the_alert_shows_whether_it_is_still_occurring(db, device):
    _, alert = _open(db, device)
    alert.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    db.flush()
    assert AlertResponse.model_validate(alert).still_occurring is True
    alert.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    assert AlertResponse.model_validate(alert).still_occurring is False
    alert.resolved = True
    assert AlertResponse.model_validate(alert).still_occurring is False
    # a system alert has no last_seen_at, so the answer is null
    system = Alert(device_id=device.id, message="x", severity="warning", resolved=False, category="monitoring", kind="offline")
    db.add(system)
    db.flush()
    assert AlertResponse.model_validate(system).still_occurring is None


def test_no_rule_is_evaluated_in_a_maintenance_window(db, device):
    now = datetime.now(timezone.utc)
    db.add(MaintenanceWindow(device_id=device.id, label="x", start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1),
                             suppress_alerts=True))
    db.flush()
    _rule(db, device, for_s=0)
    _eval(db, device, 0, temperature=99.0)
    assert _alerts(db, device) == []


def test_changing_the_metric_closes_the_open_alert_and_a_new_threshold_keeps_it(client, db, device, auth_headers):
    rule, alert = _open(db, device)
    res = client.put(f"/api/v1/alert-rules/{rule.id}", json={"threshold": 80.0}, headers=auth_headers)
    assert res.status_code == 200
    db.refresh(alert)
    assert alert.resolved is False
    res = client.put(f"/api/v1/alert-rules/{rule.id}", json={"metric": "humidity"}, headers=auth_headers)
    assert res.status_code == 200
    db.refresh(alert)
    assert alert.resolved is True and alert.message.endswith("(closed: the rule was changed)")
    assert db.get(RuleState, rule.id) is None


def test_deleting_a_rule_closes_its_open_alert_and_keeps_the_row(client, db, device, auth_headers):
    rule, alert = _open(db, device)
    assert client.delete(f"/api/v1/alert-rules/{rule.id}", headers=auth_headers).status_code == 204
    db.refresh(alert)
    assert alert.resolved is True and alert.message.endswith("(closed: the rule was deleted)")
    assert alert.rule_id is None
    assert db.query(RuleState).filter(RuleState.rule_id == rule.id).count() == 0


# -- a hand resolve ----------------------------------------------------------------------------------------------

def test_a_rule_alert_resolved_by_hand_is_not_raised_again_for_an_hour(db, device):
    _, alert = _open(db, device)
    alert.resolved, alert.resolved_at = True, _at(10)
    alert.message += " (resolved by hand)"
    db.flush()
    for seconds in (20, 600, 3000):
        _eval(db, device, seconds, temperature=99.0)
    assert len(_alerts(db, device)) == 1
    _eval(db, device, 3700, temperature=99.0)
    assert len(_alerts(db, device)) == 2 and len(_alerts(db, device, resolved=False)) == 1


def test_resolving_a_rule_alert_by_hand_through_the_api_records_it(client, db, device, auth_headers):
    _, alert = _open(db, device)
    res = client.patch(f"/api/v1/alerts/{alert.id}/resolve", headers=auth_headers)
    assert res.status_code == 200 and res.json()["message"].endswith("(resolved by hand)")


# -- a ticket made from a rule alert --------------------------------------------------------------------------

def test_a_ticket_keeps_pointing_at_the_one_long_lived_alert(client, db, device, auth_headers):
    # a ticket made from a rule alert points at the one row for as long as the breach lasts. When it resolves and the
    # breach comes back, that is a new alert row and the ticket keeps its old one
    _, alert = _open(db, device)
    res = client.post("/api/v1/tickets", json={"title": "Check the pump", "device_id": str(device.id), "alert_id": str(alert.id)},
                      headers=auth_headers)
    assert res.status_code == 201
    for seconds in (5, 10, 15):
        _eval(db, device, seconds, temperature=99.0)
    ticket = db.query(Ticket).filter(Ticket.device_id == device.id).one()
    assert ticket.alert_id == alert.id and alert.occurrences == 4


# -- the API ---------------------------------------------------------------------------------------------------

def test_the_alert_list_returns_the_new_fields(client, db, device, auth_headers):
    _, alert = _open(db, device)
    alert.last_seen_at = datetime.now(timezone.utc)
    db.flush()
    body = client.get("/api/v1/alerts", headers=auth_headers).json()
    (item,) = [a for a in body if a["id"] == str(alert.id)]
    assert item["kind"] == "rule" and item["occurrences"] == 1
    assert item["last_value"] == 99.0 and item["peak_value"] == 99.0
    assert item["last_seen_at"] is not None and item["still_occurring"] is True
    # an older alert row keeps its shape
    old = Alert(device_id=device.id, message="hot", severity="warning", resolved=False)
    db.add(old)
    db.flush()
    item = [a for a in client.get("/api/v1/alerts", headers=auth_headers).json() if a["id"] == str(old.id)][0]
    assert item["occurrences"] == 1 and item["last_value"] is None and item["still_occurring"] is None


def test_a_rule_carries_its_hold_and_margin_and_the_effective_values(client, db, device, auth_headers):
    body = {"device_id": str(device.id), "metric": "temperature", "condition": "gt", "threshold": 50.0, "severity": "warning"}
    made = client.post("/api/v1/alert-rules", json=body, headers=auth_headers).json()
    assert made["for_seconds"] is None and made["clear_margin"] is None
    assert made["effective_for_seconds"] == 30 and made["effective_clear_margin"] == pytest.approx(1.0)
    gas = client.post("/api/v1/alert-rules", json={**body, "metric": "gas_alert", "condition": "eq", "threshold": 1.0}, headers=auth_headers).json()
    assert gas["effective_for_seconds"] == 0
    own = client.post("/api/v1/alert-rules", json={**body, "for_seconds": 10, "clear_margin": 2.5}, headers=auth_headers).json()
    assert (own["for_seconds"], own["clear_margin"], own["effective_for_seconds"], own["effective_clear_margin"]) == (10, 2.5, 10, 2.5)
    # set back to the default with an explicit null
    reset = client.put(f"/api/v1/alert-rules/{own['id']}", json={"for_seconds": None, "clear_margin": None}, headers=auth_headers).json()
    assert reset["for_seconds"] is None and reset["effective_for_seconds"] == 30
    # an update that leaves them out keeps them
    kept = client.put(f"/api/v1/alert-rules/{made['id']}", json={"severity": "critical"}, headers=auth_headers).json()
    assert kept["severity"] == "critical"


@pytest.mark.parametrize("over", [{"for_seconds": -1}, {"for_seconds": 86_401}, {"clear_margin": -0.1}, {"for_seconds": "soon"}])
def test_a_bad_hold_or_margin_is_refused(client, device, auth_headers, over):
    body = {"device_id": str(device.id), "metric": "temperature", "condition": "gt", "threshold": 50.0, "severity": "warning", **over}
    assert client.post("/api/v1/alert-rules", json=body, headers=auth_headers).status_code == 422


def test_a_post_keeps_one_alert_for_a_breach_that_goes_on(client, db, device):
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric="temperature", condition="gt", threshold=50.0, severity="warning"))
    db.flush()
    for _ in range(5):
        res = client.post("/api/v1/telemetry", json={"device_id": str(device.id), "temperature": 99.0},
                          headers={"X-API-Key": device.api_key})
        assert res.status_code == 201
    (alert,) = _alerts(db, device)
    assert alert.occurrences == 5


# -- retention and the migration ------------------------------------------------------------------------------------

def test_a_resolved_rule_alert_is_deleted_by_the_twelve_month_rule(db, device):
    from app.tasks import retention

    old = Alert(device_id=device.id, message="x", severity="warning", resolved=True, kind="rule",
                resolved_at=datetime.now(timezone.utc) - timedelta(days=400))
    db.add(old)
    db.flush()
    alert_id = old.id
    db.expunge_all()

    class _Keep:
        def __init__(self, s):
            self._s = s

        def close(self):
            pass

        def __getattr__(self, n):
            return getattr(self._s, n)

    retention.run_retention(lambda: _Keep(db), now=datetime.now(timezone.utc))
    assert db.query(Alert).filter(Alert.id == alert_id).first() is None


def _collapse_statement():
    source = (MIGRATIONS / "029_stateful_rule_alerts.sql").read_text()
    return re.search(r"\$q\$\s*(WITH open_rows.*?)\$q\$", source, re.S).group(1)


def test_the_migration_collapses_open_duplicates_into_one_alert_per_machine_and_rule(db, device):
    gt_rule = _rule(db, device, for_s=0)
    lt_rule = _rule(db, device, metric="humidity", condition="lt", threshold=30.0, for_s=0)
    t0 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
    for i in range(48):
        db.add(Alert(device_id=device.id, rule_id=gt_rule.id, severity="warning", resolved=False,
                     message=f"temperature is {60 + (i if i != 10 else 40)}.0 (gt 50.0) on {device.name}",
                     triggered_at=t0 + timedelta(seconds=5 * i)))
    for i, v in enumerate((20.0, 5.0, 12.0)):
        db.add(Alert(device_id=device.id, rule_id=lt_rule.id, severity="critical", resolved=False,
                     message=f"humidity is {v} (lt 30.0) on {device.name}", triggered_at=t0 + timedelta(seconds=i)))
    # an alert with no rule and an already resolved one are not touched
    db.add(Alert(device_id=device.id, message="Anomaly detected", severity="warning", resolved=False))
    db.add(Alert(device_id=device.id, rule_id=gt_rule.id, message="temperature is 99.0 (gt 50.0) on x", severity="warning",
                 resolved=True, triggered_at=t0 - timedelta(days=1)))
    db.flush()
    db.execute(text(_collapse_statement()))
    db.expire_all()
    kept = db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "rule").order_by(Alert.rule_id).all()
    assert len(kept) == 2
    by_rule = {a.rule_id: a for a in kept}
    hot = by_rule[gt_rule.id]
    assert hot.occurrences == 48 and hot.triggered_at == t0 and hot.resolved is False
    assert hot.last_value == 107.0 and hot.peak_value == 107.0
    assert hot.last_seen_at == t0 + timedelta(seconds=5 * 47)
    dry = by_rule[lt_rule.id]
    assert dry.occurrences == 3 and dry.last_value == 12.0 and dry.peak_value == 5.0 and dry.severity == "critical"
    closed = db.query(Alert).filter(Alert.device_id == device.id, Alert.message.like("%(closed: merged into one alert for this rule)")).all()
    assert len(closed) == 47 + 2 and all(a.resolved for a in closed)
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.rule_id.isnot(None), Alert.resolved.is_(False)).count() == 2
    # the alert without a rule and the old resolved one are as they were
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.message == "Anomaly detected", Alert.resolved.is_(False)).count() == 1
    # running it again changes nothing
    db.execute(text(_collapse_statement()))
    db.expire_all()
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "rule", Alert.resolved.is_(False)).count() == 2
    assert db.get(Alert, hot.id).occurrences == 48


def test_the_migration_steps_are_in_a_safe_order():
    source = re.sub(r"--[^\n]*", "", (MIGRATIONS / "029_stateful_rule_alerts.sql").read_text())
    order = [
        source.index("CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_alerts_open_system"),
        source.index("DROP INDEX CONCURRENTLY IF EXISTS uq_alerts_open_kind"),
        source.index("WITH open_rows"),
        source.index("CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_alerts_open_rule"),
    ]
    assert order == sorted(order)
    assert "SET lock_timeout" in source


# -- the model's anomaly decision through evaluate_anomaly --------------------------------------------------------

@pytest.fixture
def decision(monkeypatch):
    box = {"next": Decision("none"), "calls": []}

    def decide(points, open_alert_since, last_resolved_at, now, interval_s):
        box["calls"].append({"points": points, "open": open_alert_since, "last_resolved": last_resolved_at, "now": now,
                             "interval": interval_s})
        return box["next"]

    monkeypatch.setattr(alert_service.anomaly_decision, "decide", decide)
    return box


@pytest.fixture
def owner_mail(monkeypatch, store):
    log = {"email": [], "sms": []}
    monkeypatch.setattr(notify_service, "send_email_alert", lambda **k: log["email"].append(k) or True)
    from app.services import sms_service

    monkeypatch.setattr(sms_service, "notify_anomaly", lambda **k: log["sms"].append(k) or True)
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "brevo_api_key", "test-brevo-key")
    return log


def _scored(db, device, ages, score=0.9):
    now = datetime.now(timezone.utc)
    for age in ages:
        db.add(Telemetry(device_id=device.id, temperature=1.0, anomaly_score=score, recorded_at=now - timedelta(seconds=age)))
    db.flush()


def _anomaly(db, device, **filters):
    return db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "anomaly").filter_by(**filters).all()


def test_a_raise_opens_one_alert_and_one_ticket_with_the_decisions_reason_and_notifies_once(db, owner_mail, decision):
    device = _owned_device(db)
    _scored(db, device, [30, 20, 10])
    decision["next"] = Decision("raise", "warning", "73 of 80 scored readings in the last 120 s were at or over the boundary (median 0.91)")
    alert_service.evaluate_anomaly(device, db)
    (alert,) = _anomaly(db, device)
    assert alert.message == f"Anomaly detected on {device.name}: 73 of 80 scored readings in the last 120 s were at or over the boundary (median 0.91)"
    assert alert.severity == "warning" and alert.category == "machine" and alert.rule_id is None
    assert alert.peak_value == pytest.approx(0.9) and alert.last_seen_at is not None
    ticket = db.query(Ticket).filter(Ticket.device_id == device.id).one()
    assert ticket.alert_id == alert.id and ticket.priority == "high"
    assert len(owner_mail["email"]) == 1 and owner_mail["sms"] == []
    # a second raise while one is open does nothing
    alert_service.evaluate_anomaly(device, db)
    assert len(_anomaly(db, device)) == 1 and len(owner_mail["email"]) == 1


def test_a_critical_raise_texts_the_owner(db, owner_mail, decision):
    device = _owned_device(db)
    decision["next"] = Decision("raise", "critical", "the median is 0.97")
    alert_service.evaluate_anomaly(device, db)
    assert len(owner_mail["sms"]) == 1
    assert db.query(Ticket).filter(Ticket.device_id == device.id).one().priority == "critical"


def test_an_escalate_updates_the_one_open_alert_and_notifies_once(db, owner_mail, decision):
    device = _owned_device(db)
    decision["next"] = Decision("raise", "warning", "median 0.75")
    alert_service.evaluate_anomaly(device, db)
    decision["next"] = Decision("escalate", "critical", "the median rose to 0.93")
    alert_service.evaluate_anomaly(device, db)
    (alert,) = _anomaly(db, device)
    assert alert.severity == "critical" and alert.message.endswith("the median rose to 0.93")
    assert db.query(Ticket).filter(Ticket.device_id == device.id).one().priority == "critical"
    assert len(owner_mail["sms"]) == 1
    # a second escalate when it is already critical sends nothing
    alert_service.evaluate_anomaly(device, db)
    assert len(owner_mail["sms"]) == 1 and len(_anomaly(db, device)) == 1


def test_an_escalate_with_nothing_open_does_nothing(db, device, decision):
    decision["next"] = Decision("escalate", "critical", "x")
    alert_service.evaluate_anomaly(device, db)
    assert _anomaly(db, device) == []


def test_a_resolve_closes_the_open_alert_and_says_why(db, device, decision):
    decision["next"] = Decision("raise", "warning", "median 0.8")
    alert_service.evaluate_anomaly(device, db)
    decision["next"] = Decision("resolve", None, "the median of the last 300 s is 0.31")
    alert_service.evaluate_anomaly(device, db)
    (alert,) = _anomaly(db, device)
    assert alert.resolved is True and alert.resolved_at is not None
    assert alert.message.endswith("(resolved: the median of the last 300 s is 0.31)")
    # a resolve with nothing open does nothing
    alert_service.evaluate_anomaly(device, db)


def test_none_raises_nothing_and_keeps_an_open_alert_current(db, device, decision):
    decision["next"] = Decision("none")
    alert_service.evaluate_anomaly(device, db)
    assert _anomaly(db, device) == []
    decision["next"] = Decision("raise", "warning", "r")
    _scored(db, device, [20], score=0.6)
    alert_service.evaluate_anomaly(device, db)
    (alert,) = _anomaly(db, device)
    before = alert.peak_value
    _scored(db, device, [5], score=0.99)
    decision["next"] = Decision("none")
    alert_service.evaluate_anomaly(device, db)
    assert alert.resolved is False and alert.peak_value == pytest.approx(0.99) and alert.peak_value > before


def test_the_decision_gets_the_open_alerts_start_the_last_resolve_and_the_interval(db, device, decision):
    device.expected_interval_s = 10
    decision["next"] = Decision("raise", "warning", "r")
    alert_service.evaluate_anomaly(device, db)
    alert = _anomaly(db, device)[0]
    first = decision["calls"][0]
    assert first["open"] is None and first["last_resolved"] is None and first["interval"] == 10
    decision["next"] = Decision("none")
    alert_service.evaluate_anomaly(device, db)
    assert decision["calls"][1]["open"] == alert.triggered_at
    alert.resolved, alert.resolved_at = True, datetime.now(timezone.utc) - timedelta(minutes=5)
    db.flush()
    alert_service.evaluate_anomaly(device, db)
    assert decision["calls"][2]["open"] is None and decision["calls"][2]["last_resolved"] == alert.resolved_at


def test_a_hand_resolve_sets_the_time_the_re_arm_delay_runs_from(client, db, device, auth_headers, decision):
    decision["next"] = Decision("raise", "warning", "r")
    alert_service.evaluate_anomaly(device, db)
    alert = _anomaly(db, device)[0]
    assert client.patch(f"/api/v1/alerts/{alert.id}/resolve", headers=auth_headers).status_code == 200
    decision["next"] = Decision("none")
    alert_service.evaluate_anomaly(device, db)
    assert decision["calls"][-1]["last_resolved"] is not None


def test_a_machine_in_a_maintenance_window_is_not_evaluated(db, device, decision):
    now = datetime.now(timezone.utc)
    db.add(MaintenanceWindow(device_id=device.id, label="x", start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1),
                             suppress_alerts=True))
    db.flush()
    decision["next"] = Decision("raise", "warning", "r")
    alert_service.evaluate_anomaly(device, db)
    assert decision["calls"] == [] and _anomaly(db, device) == []


def test_the_second_post_that_loses_the_race_raises_nothing(db, device, decision, monkeypatch):
    decision["next"] = Decision("raise", "warning", "r")
    alert_service.evaluate_anomaly(device, db)
    # the other post's alert is open but this evaluation's lookup does not see it
    monkeypatch.setattr(alert_service, "_open_anomaly_alert", lambda *a, **k: None)
    alert_service.evaluate_anomaly(device, db)
    assert len(_anomaly(db, device)) == 1 and db.query(Ticket).filter(Ticket.device_id == device.id).count() == 1


def test_the_old_three_in_a_row_constants_are_gone():
    for name in ("ANOMALY_RUN", "ANOMALY_RUN_WINDOW", "CRITICAL_SCORE"):
        assert not hasattr(alert_service, name)


def test_the_device_read_carries_the_models_state_without_a_query_for_each_machine(client, db, device, auth_headers, monkeypatch):
    import secrets

    from sqlalchemy import event

    from app.models.device import Device
    from app.services import ml_service

    calls = []
    status = {"state": "learning", "scope": None, "hours_collected": 7.5, "hours_needed": 24.0,
              "false_alerts_per_week": None, "trained_at": None, "refusal": None, "refused_at": None,
              "monitored": False, "reason": "learning: 7.5 of 24 hours of clean readings collected",
              "false_alerts_per_week_high_95": None, "ambient": None, "light": False}
    monkeypatch.setattr(ml_service, "model_status", lambda device_id, node_type: calls.append((device_id, node_type)) or status)
    one = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()
    # the whole object as model_status reports it, with the five fields added for the model's status
    assert one["model"] == status
    listed = [d for d in client.get("/api/v1/devices", headers=auth_headers).json() if d["id"] == str(device.id)][0]
    assert listed["model"] == status
    assert (device.id, device.type) in calls
    monkeypatch.undo()

    # the real status, from a loaded bundle, costs no query for any machine: a list of one and a list of six run the same
    # statements
    monkeypatch.setattr(ml_service, "_model", {ml_service.META_KEY: {"machines": {}, "unmonitored": {}}})
    monkeypatch.setattr(ml_service, "_load_model", lambda: None)
    monkeypatch.setattr(ml_service, "_problem", None)
    statements = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    bind = db.get_bind()
    event.listen(bind, "before_cursor_execute", count)
    try:
        client.get("/api/v1/devices", headers=auth_headers)
        with_one = len(statements)
        for i in range(5):
            db.add(Device(name=f"Extra {i}", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32)))
        db.flush()
        statements.clear()
        body = client.get("/api/v1/devices", headers=auth_headers).json()
        with_six = len(statements)
    finally:
        event.remove(bind, "before_cursor_execute", count)
    assert len(body) >= 6 and all(set(status) <= set(d["model"]) for d in body)
    assert with_six == with_one