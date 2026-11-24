"""
A failed sensor must be visible: one stateful monitoring alert per device and sensor, an alert for a node that posts
but is never scored and a list of the rules that cannot fire. The clock is passed in, so nothing waits.
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from passlib.context import CryptContext

from app.config import settings
from app.models.alert import Alert, AlertRule
from app.models.device import Device
from app.models.device_health import DeviceHealth
from app.models.maintenance import MaintenanceWindow
from app.models.user import User
from app.schemas.telemetry import TelemetryIngest
from app.services import alert_service, cooldown, health_service, ml_service, notify_service, sms_service
from tests.test_alert_notifications import FakeRedis

T0 = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _at(seconds):
    return T0 + timedelta(seconds=seconds)


def _seen(db, device, seconds, **faults):
    """One post's health at T0 + seconds. An empty call is a post that carries health fields and no faults."""
    payload = TelemetryIngest(device_id=str(device.id), faults=faults)
    return health_service.record_health(db, device, payload, _at(seconds))


def _alerts(db, device, **filters):
    return (
        db.query(Alert)
        .filter(Alert.device_id == device.id, Alert.sensor_key.isnot(None))
        .filter_by(**filters)
        .order_by(Alert.sensor_key)
        .all()
    )


@pytest.fixture
def machine(db):
    d = Device(name="Pump 1", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32))
    db.add(d)
    db.flush()
    return d


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
    monkeypatch.setattr(sms_service, "notify_critical", lambda **k: log["sms"].append(k) or True)
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "brevo_api_key", "test-brevo-key")
    return log


# -- opening: only after a minute, once, in plain words -------------------------------------------------

def test_a_fault_raises_nothing_until_it_has_lasted_a_minute(db, machine):
    for seconds in (0, 5, 30, 59):
        assert _seen(db, machine, seconds, bme280="missing").notify == []
    assert _alerts(db, machine) == []


def test_after_a_minute_one_alert_opens_with_the_sensor_and_the_state_in_plain_words(db, machine):
    for seconds in (0, 30):
        _seen(db, machine, seconds, bme280="missing")
    result = _seen(db, machine, 60, bme280="missing")
    (alert,) = _alerts(db, machine)
    assert alert.sensor_key == "bme280"
    assert alert.category == "monitoring" and alert.severity == "warning" and alert.rule_id is None
    assert alert.resolved is False
    assert alert.message == "Pump 1: sensor bme280 is not answering (missing)"
    assert result.notify == [("sensor-bme280", alert.message)]


def test_a_continuing_fault_is_not_a_new_alert_and_not_a_new_email(db, machine):
    for seconds in (0, 60):
        _seen(db, machine, seconds, bme280="missing")
    for seconds in (65, 120, 600, 3600):
        assert _seen(db, machine, seconds, bme280="missing").notify == []
    assert len(_alerts(db, machine)) == 1


def test_a_change_of_state_updates_the_alert_and_does_not_duplicate_it(db, machine):
    for seconds in (0, 60):
        _seen(db, machine, seconds, bme280="missing")
    result = _seen(db, machine, 90, bme280="stuck")
    (alert,) = _alerts(db, machine)
    assert alert.message == "Pump 1: sensor bme280 is stuck on one value (stuck)"
    assert result.notify == []


def test_each_sensor_has_its_own_alert(db, machine):
    for seconds in (0, 60):
        _seen(db, machine, seconds, bme280="missing", ds18b20="unplugged")
    keys = [a.sensor_key for a in _alerts(db, machine)]
    assert keys == ["bme280", "ds18b20"]


def test_a_node_posting_no_health_fields_does_not_move_the_clock(db, machine):
    _seen(db, machine, 0, bme280="missing")
    # a post with no health field says nothing about faults, so it is not recorded at all
    legacy = TelemetryIngest(device_id=str(machine.id), temperature=20.0)
    assert health_service.record_health(db, machine, legacy, _at(120)).stored is False
    assert _alerts(db, machine) == []


@pytest.mark.parametrize("state", ["warming_up", "not_fitted"])
def test_states_that_are_not_failures_raise_nothing(db, machine, state):
    for seconds in (0, 60, 600):
        _seen(db, machine, seconds, mq2=state)
    assert _alerts(db, machine) == []


def test_a_sensor_marked_not_fitted_raises_nothing(db, machine):
    machine.not_fitted = ["bme280"]
    db.flush()
    for seconds in (0, 60, 600):
        _seen(db, machine, seconds, bme280="missing", nano_link="silent")
    keys = [a.sensor_key for a in _alerts(db, machine)]
    # only the link that is not marked raises one
    assert keys == ["nano_link"]


def test_no_alert_opens_during_a_maintenance_window(db, machine):
    now = datetime.now(timezone.utc)
    db.add(MaintenanceWindow(
        device_id=machine.id, label="service", start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1),
        suppress_alerts=True,
    ))
    db.flush()
    for seconds in (0, 60, 600):
        _seen(db, machine, seconds, bme280="missing")
    assert _alerts(db, machine) == []


def test_an_alert_that_exists_but_was_forgotten_by_the_tracker_is_not_duplicated(db, machine):
    for seconds in (0, 60):
        _seen(db, machine, seconds, bme280="missing")
    row = db.get(DeviceHealth, machine.id)
    row.sensor_track = {}
    db.flush()
    for seconds in (100, 200):
        _seen(db, machine, seconds, bme280="missing")
    assert len(_alerts(db, machine)) == 1


# -- resolving ------------------------------------------------------------------------------------

def test_the_alert_resolves_after_a_minute_of_the_sensor_reporting_ok(db, machine):
    for seconds in (0, 60):
        _seen(db, machine, seconds, bme280="missing")
    # ok and absent from the map, mean the same thing
    _seen(db, machine, 100)
    _seen(db, machine, 130, bme280="ok")
    _seen(db, machine, 159)
    (alert,) = _alerts(db, machine)
    assert alert.resolved is False
    _seen(db, machine, 160)
    assert alert.resolved is True and alert.resolved_at is not None
    assert alert.message.endswith("(resolved: the sensor has reported ok for a minute)")


def test_a_fault_that_returns_before_the_minute_is_up_keeps_the_alert_open(db, machine):
    for seconds in (0, 60):
        _seen(db, machine, seconds, bme280="missing")
    _seen(db, machine, 70)
    _seen(db, machine, 100, bme280="missing")
    _seen(db, machine, 200, bme280="missing")
    (alert,) = _alerts(db, machine)
    assert alert.resolved is False
    assert len(_alerts(db, machine)) == 1


def test_a_second_fault_after_a_resolved_one_opens_a_new_alert(db, machine):
    for seconds in (0, 60):
        _seen(db, machine, seconds, bme280="missing")
    for seconds in (100, 200):
        _seen(db, machine, seconds)
    for seconds in (1000, 1060):
        _seen(db, machine, seconds, bme280="stuck")
    assert len(_alerts(db, machine)) == 2
    assert len(_alerts(db, machine, resolved=False)) == 1


# -- flapping -------------------------------------------------------------------------------------

def test_a_flapping_sensor_gets_one_alert_that_says_it_is_intermittent(db, machine):
    seconds = 0
    for _ in range(3):
        _seen(db, machine, seconds, bme280="missing")
        _seen(db, machine, seconds + 5)
        seconds += 10
    # six changes so far. The seventh makes it intermittent, at once and not after a minute
    result = _seen(db, machine, seconds, bme280="missing")
    (alert,) = _alerts(db, machine)
    assert "intermittent" in alert.message
    assert "7 times in the last hour" in alert.message
    assert result.notify == [("sensor-bme280", alert.message)]
    # many more changes raise no more alerts
    for step in range(1, 11):
        _seen(db, machine, seconds + step * 10, **({"bme280": "missing"} if step % 2 else {}))
    assert len(_alerts(db, machine)) == 1


def test_a_flapping_alert_stays_until_the_sensor_has_been_quiet_for_the_hour(db, machine):
    seconds = 0
    for _ in range(4):
        _seen(db, machine, seconds, bme280="missing")
        _seen(db, machine, seconds + 5)
        seconds += 10
    (alert,) = _alerts(db, machine)
    # ok for ten minutes: the changes are still inside the hour
    for step in range(1, 11):
        _seen(db, machine, seconds + step * 60)
    assert alert.resolved is False
    # an hour on, the changes have aged out and the minute of ok resolves it
    for step in range(0, 3):
        _seen(db, machine, seconds + 3800 + step * 40)
    assert alert.resolved is True


def test_five_changes_in_an_hour_is_not_yet_intermittent(db, machine):
    seconds = 0
    for _ in range(2):
        _seen(db, machine, seconds, bme280="missing")
        _seen(db, machine, seconds + 5)
        seconds += 10
    _seen(db, machine, seconds, bme280="missing")
    # five changes. No alert until it has lasted a minute
    assert _alerts(db, machine) == []


# -- notification: email only, on the hourly window for that device and sensor -------------------------

def test_a_fault_alert_emails_a_warning_on_the_hourly_window_for_its_sensor_and_never_texts(db, sent, store):
    owner = User(name="Owner", email=f"o-{secrets.token_hex(3)}@example.com", password_hash=_pwd.hash("Passw0rd!x"),
                 role="admin", phone_number="+447700900000", phone_confirmed_at=datetime.now(timezone.utc))
    db.add(owner)
    db.flush()
    machine = Device(name="Pump 1", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32), owner_id=owner.id)
    db.add(machine)
    db.flush()
    for seconds in (0, 60):
        result = _seen(db, machine, seconds, bme280="missing", ldr="stuck")
    for kind, message in result.notify:
        alert_service.notify_monitoring(None, machine, kind, message)
    # one email for each sensor, as a warning
    assert sorted(e["subject"] for e in sent["email"]) == ["PHAEMOS [WARNING] Pump 1"] * 2
    # the same sensor again within the hour is held, another sensor is not
    alert_service.notify_monitoring(None, machine, "sensor-bme280", "again")
    assert len(sent["email"]) == 2
    alert_service.notify_monitoring(None, machine, "sensor-mq2", "other")
    assert len(sent["email"]) == 3
    assert sent["sms"] == []


def test_a_post_that_opens_a_fault_alert_sends_its_email(client, db, machine, sent, monkeypatch):
    monkeypatch.setattr(health_service, "FAULT_ALERT_AFTER_S", 0)
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(machine.id), "boot": 1, "faults": {"bme280": "missing"}},
        headers={"X-API-Key": machine.api_key},
    )
    assert res.status_code == 201
    (alert,) = _alerts(db, machine)
    assert alert.sensor_key == "bme280"
    assert [e["body"] for e in sent["email"]] == [alert.message]
    # the second post finds the alert open and sends nothing more
    client.post(
        "/api/v1/telemetry",
        json={"device_id": str(machine.id), "boot": 1, "faults": {"bme280": "missing"}},
        headers={"X-API-Key": machine.api_key},
    )
    assert len(sent["email"]) == 1 and len(_alerts(db, machine)) == 1


# -- a node that posts but is never scored ------------------------------------------------------------

class _Model:
    phaemos_features = ["temperature", "humidity"]
    phaemos_schema = ml_service.SCHEMA_VERSION
    offset_ = 0.0
    phaemos_typical_decision = 0.1

    def score_samples(self, X):
        return [-0.5] * len(X)


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(ml_service, "_model", {"default": _Model()})


def _unscored(db, machine, seconds, **reading):
    return health_service.track_scoring(db, machine, reading, False, _at(seconds))


def _scored(db, machine, seconds):
    return health_service.track_scoring(db, machine, {"temperature": 1.0, "humidity": 2.0}, True, _at(seconds))


def _unscored_alerts(db, machine):
    return db.query(Alert).filter(
        Alert.device_id == machine.id, Alert.message.contains(health_service.UNSCORED_SUFFIX)
    ).all()


def test_ten_minutes_without_a_scored_reading_raises_one_alert_naming_the_missing_inputs(db, machine, model):
    for seconds in (0, 120, 599):
        assert _unscored(db, machine, seconds, temperature=20.0) is None
    note = _unscored(db, machine, 600, temperature=20.0)
    (alert,) = _unscored_alerts(db, machine)
    assert alert.message == "Pump 1 has had no scored reading for 10 minutes: the model is missing humidity"
    assert alert.category == "monitoring" and alert.severity == "warning" and alert.sensor_key is None
    assert note == ("unscored", alert.message)
    # steady state: no second alert and no second email
    assert _unscored(db, machine, 700, temperature=20.0) is None
    assert len(_unscored_alerts(db, machine)) == 1


def test_a_scored_reading_resolves_it_and_clears_the_state(db, machine, model):
    _unscored(db, machine, 0, temperature=20.0)
    _unscored(db, machine, 600, temperature=20.0)
    _scored(db, machine, 610)
    (alert,) = _unscored_alerts(db, machine)
    assert alert.resolved is True and alert.message.endswith("(resolved: readings are scored again)")
    assert machine.unscored_since is None and machine.unscored_missing == [] and machine.unscored_alerted is False


def test_one_scored_reading_in_the_ten_minutes_restarts_the_count(db, machine, model):
    _unscored(db, machine, 0, temperature=20.0)
    _scored(db, machine, 300)
    assert _unscored(db, machine, 700, temperature=20.0) is None
    assert _unscored(db, machine, 1299, temperature=20.0) is None
    assert _unscored_alerts(db, machine) == []


def test_fields_that_go_missing_with_no_fault_named_count_too(db, machine, model):
    # a range sensor with no target sends no distance and names no fault, so the node is simply never scored
    _unscored(db, machine, 0, temperature=20.0, humidity=None)
    _unscored(db, machine, 600, temperature=20.0, humidity=None)
    (alert,) = _unscored_alerts(db, machine)
    assert "humidity" in alert.message


def test_the_unscored_alert_is_held_back_in_a_maintenance_window(db, machine, model):
    now = datetime.now(timezone.utc)
    db.add(MaintenanceWindow(
        device_id=machine.id, label="service", start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1),
        suppress_alerts=True,
    ))
    db.flush()
    _unscored(db, machine, 0, temperature=20.0)
    assert _unscored(db, machine, 900, temperature=20.0) is None
    assert _unscored_alerts(db, machine) == []


def test_a_node_with_no_model_is_never_called_unscored(client, db, machine, monkeypatch):
    monkeypatch.setattr(ml_service, "_model", None)
    monkeypatch.setattr(ml_service, "_load_model", lambda: None)
    monkeypatch.setattr(health_service, "UNSCORED_ALERT_AFTER_S", 0)
    client.post("/api/v1/telemetry", json={"device_id": str(machine.id), "temperature": 20.0}, headers={"X-API-Key": machine.api_key})
    assert _unscored_alerts(db, machine) == []


def test_a_post_that_leaves_the_node_unscored_opens_the_alert(client, db, machine, model, sent, monkeypatch):
    monkeypatch.setattr(health_service, "UNSCORED_ALERT_AFTER_S", 0)
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(machine.id), "temperature": 20.0},
        headers={"X-API-Key": machine.api_key},
    )
    assert res.status_code == 201
    (alert,) = _unscored_alerts(db, machine)
    assert "the model is missing humidity" in alert.message
    assert [e["body"] for e in sent["email"]] == [alert.message]


# -- the rules that cannot be evaluated --------------------------------------------------------------

def _rule(db, device, metric="temperature"):
    rule = AlertRule(for_seconds=0, device_id=device.id, metric=metric, condition="gt", threshold=50.0, severity="warning")
    db.add(rule)
    db.flush()
    return rule


def test_a_rule_on_a_faulted_sensor_is_listed_and_raises_no_alert_of_its_own(client, db, machine, auth_headers):
    rule = _rule(db, machine, "temperature")
    other = _rule(db, machine, "contact_temp")
    client.post(
        "/api/v1/telemetry",
        json={"device_id": str(machine.id), "temperature": 90.0, "boot": 1, "faults": {"bme280": "missing"}},
        headers={"X-API-Key": machine.api_key},
    )
    health = client.get(f"/api/v1/devices/{machine.id}", headers=auth_headers).json()["health"]
    (listed,) = health["rules_cannot_evaluate"]
    assert listed["rule_id"] == str(rule.id) and listed["metric"] == "temperature"
    assert listed["sensor_key"] == "bme280" and listed["state"] == "missing"
    assert "not answering" in listed["reason"]
    assert str(other.id) not in {r["rule_id"] for r in health["rules_cannot_evaluate"]}
    # no alert for the rule: the fault alert covers the cause and has not opened yet
    assert db.query(Alert).filter(Alert.device_id == machine.id).count() == 0


def test_the_list_is_empty_when_nothing_is_faulted(client, db, machine, auth_headers):
    _rule(db, machine)
    client.post("/api/v1/telemetry", json={"device_id": str(machine.id), "boot": 1}, headers={"X-API-Key": machine.api_key})
    health = client.get(f"/api/v1/devices/{machine.id}", headers=auth_headers).json()["health"]
    assert health["rules_cannot_evaluate"] == []


def test_a_fault_on_a_sensor_that_is_not_fitted_is_shown_as_not_fitted(client, db, machine, auth_headers):
    _rule(db, machine)
    machine.not_fitted = ["bme280"]
    db.flush()
    client.post(
        "/api/v1/telemetry",
        json={"device_id": str(machine.id), "boot": 1, "faults": {"bme280": "missing", "ldr": "stuck"}},
        headers={"X-API-Key": machine.api_key},
    )
    health = client.get(f"/api/v1/devices/{machine.id}", headers=auth_headers).json()["health"]
    assert health["faults"] == {"bme280": "not_fitted", "ldr": "stuck"}
    (listed,) = health["rules_cannot_evaluate"]
    assert listed["state"] == "not_fitted" and "not fitted" in listed["reason"]


# -- the not fitted list is an admin field -------------------------------------------------------------

def _user(db, email, role):
    u = User(name=email, email=email, password_hash=_pwd.hash("Passw0rd!x"), role=role)
    db.add(u)
    db.flush()
    return u


def _headers(user):
    from app.routes.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'role': user.role})}"}


def test_an_admin_sets_the_not_fitted_list_and_the_alias_is_stored_under_its_name(client, db, machine, auth_headers):
    res = client.patch(f"/api/v1/devices/{machine.id}", json={"not_fitted": ["stm32", "NANO_LINK", "stm32_link"]}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["not_fitted"] == ["stm32_link", "nano_link"]
    assert client.get(f"/api/v1/devices/{machine.id}", headers=auth_headers).json()["not_fitted"] == ["stm32_link", "nano_link"]
    cleared = client.patch(f"/api/v1/devices/{machine.id}", json={"not_fitted": []}, headers=auth_headers)
    assert cleared.json()["not_fitted"] == []


def test_a_device_starts_with_nothing_marked_not_fitted(client, machine, auth_headers):
    assert client.get(f"/api/v1/devices/{machine.id}", headers=auth_headers).json()["not_fitted"] == []


def test_an_unknown_sensor_key_is_refused(client, machine, auth_headers):
    res = client.patch(f"/api/v1/devices/{machine.id}", json={"not_fitted": ["toaster"]}, headers=auth_headers)
    assert res.status_code == 422


def test_a_technician_cannot_change_the_not_fitted_list_even_on_their_own_machine(client, db):
    tech = _user(db, "nf-tech@test.com", "technician")
    own = Device(name="own", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32), owner_id=tech.id)
    db.add(own)
    db.flush()
    res = client.patch(f"/api/v1/devices/{own.id}", json={"not_fitted": ["bme280"]}, headers=_headers(tech))
    assert res.status_code == 403
    assert client.patch(f"/api/v1/devices/{own.id}", json={"name": "renamed"}, headers=_headers(tech)).status_code == 200


def test_a_viewer_cannot_change_it(client, db, machine):
    viewer = _user(db, "nf-viewer@test.com", "viewer")
    assert client.patch(f"/api/v1/devices/{machine.id}", json={"not_fitted": ["bme280"]}, headers=_headers(viewer)).status_code == 403
