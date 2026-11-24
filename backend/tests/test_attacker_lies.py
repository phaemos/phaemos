"""
What a stolen device key can and cannot hide, written from the attacker's side.

The attacker posts calm lies: a fault claim, a not-fitted list, an impossible value, a flapping sensor. The rule under test is that
a post cannot silence a threshold rule without leaving an open alert that says why. These run with the real gating
(the mark real_fault_gating), not the test suite's default of counting every claim.
"""

import pytest
from sqlalchemy import text

from app.models.alert import Alert, AlertRule
from app.models.telemetry import Telemetry
from app.services import health_service

pytestmark = pytest.mark.real_fault_gating


def _post(client, device, **fields):
    res = client.post(
        "/api/v1/telemetry", json={"device_id": str(device.id), **fields}, headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _hot_rule(db, device, metric="temperature"):
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric=metric, condition="gt", threshold=50.0, severity="critical"))
    db.flush()


def _rule_alerts(db, device):
    return db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "rule", Alert.resolved.is_(False)).all()


def _sensor_alerts(db, device):
    return db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "sensor", Alert.resolved.is_(False)).all()


def test_a_fault_claim_with_no_alert_behind_it_does_not_silence_the_rule(client, db, device):
    _hot_rule(db, device)
    body = _post(client, device, temperature=99.0, faults={"bme280": "missing"})
    # the value was not stopped and the rule fired
    assert body["temperature"] == 99.0
    assert len(_rule_alerts(db, device)) == 1
    # and the row says the claim was not applied, so the reading explains itself
    row = db.query(Telemetry).filter(Telemetry.device_id == device.id).one()
    assert row.quality["not_applied"] == ["bme280"]


def test_a_claim_stops_its_sensor_only_while_the_sensor_alert_is_open_and_visible(client, db, device):
    _hot_rule(db, device)
    db.add(Alert(
        device_id=device.id, message="sensor bme280 is not answering", severity="warning", resolved=False,
        category="monitoring", sensor_key="bme280", kind="sensor",
    ))
    db.flush()
    body = _post(client, device, temperature=99.0, faults={"bme280": "missing"})
    assert body["temperature"] is None
    assert _rule_alerts(db, device) == []
    # the thing that explains it is open
    assert len(_sensor_alerts(db, device)) == 1
    # the alert is resolved by a person: the very next claim stops nothing
    alert = _sensor_alerts(db, device)[0]
    alert.resolved = True
    db.flush()
    assert _post(client, device, temperature=99.0, faults={"bme280": "missing"})["temperature"] == 99.0


def test_the_alert_of_one_sensor_does_not_stop_another(client, db, device):
    _hot_rule(db, device)
    db.add(Alert(
        device_id=device.id, message="sensor ldr is not answering", severity="warning", resolved=False,
        category="monitoring", sensor_key="ldr", kind="sensor",
    ))
    db.flush()
    body = _post(client, device, temperature=99.0, faults={"ldr": "missing", "bme280": "missing"})
    assert body["temperature"] == 99.0
    assert len(_rule_alerts(db, device)) == 1


def test_the_firmwares_not_fitted_list_is_display_only(client, db, device):
    _hot_rule(db, device)
    body = _post(client, device, temperature=99.0, not_fitted=["bme280"], faults={"bme280": "missing"})
    assert body["temperature"] == 99.0
    assert len(_rule_alerts(db, device)) == 1


def test_an_admins_not_fitted_list_does_stop_the_sensor(client, db, device):
    device.not_fitted = ["bme280"]
    _hot_rule(db, device)
    db.flush()
    body = _post(client, device, temperature=99.0, faults={"bme280": "missing"})
    assert body["temperature"] is None
    assert _rule_alerts(db, device) == []


def test_a_warming_up_claim_stops_nothing(client, db, device):
    # a quiet state raises no alert, so it cannot be allowed to hide a value
    _hot_rule(db, device)
    body = _post(client, device, temperature=99.0, faults={"bme280": "warming_up"})
    assert body["temperature"] == 99.0
    assert len(_rule_alerts(db, device)) == 1


def test_a_sensor_that_flips_between_faulty_and_fine_ends_up_with_an_open_alert(client, db, device):
    # the attacker alternates the claim hoping to keep the rule off without ever holding a fault for a minute. Each claim
    # stops nothing. The changes themselves make the sensor intermittent, which opens an alert at once
    _hot_rule(db, device)
    for _ in range(4):
        assert _post(client, device, temperature=99.0, faults={"bme280": "missing"})["temperature"] == 99.0
        assert _post(client, device, temperature=99.0, faults={})["temperature"] == 99.0
    (alert,) = _sensor_alerts(db, device)
    assert "intermittent" in alert.message


def test_an_impossible_value_is_dropped_marked_and_becomes_a_visible_sensor_fault(client, db, device, monkeypatch):
    monkeypatch.setattr(health_service, "FAULT_ALERT_AFTER_S", 0)
    _hot_rule(db, device)
    body = _post(client, device, temperature=1e308, humidity=40.0)
    assert body["temperature"] is None and body["humidity"] == 40.0
    row = db.query(Telemetry).filter(Telemetry.device_id == device.id).one()
    assert row.quality["dropped_values"] == ["temperature"]
    # the dropped value cannot fire a rule, so the sensor is shown as out of range
    (alert,) = _sensor_alerts(db, device)
    assert alert.sensor_key == "bme280" and "out_of_range" in alert.message


@pytest.mark.parametrize("field,value", [
    ("temperature", 251.0), ("temperature", -91.0), ("humidity", 101.0), ("pressure", 5000.0), ("vibration_x", 161.0),
    ("gyro_z", -2101.0), ("bus_voltage", 33.0), ("ir_temperature", 400.0), ("contact_temp", -127.0),
    ("shaft_angle", 400.0), ("distance_mm", 1e9), ("gas_level", -1.0),
])
def test_every_classic_field_has_a_physical_range(client, db, device, field, value):
    body = _post(client, device, **{field: value})
    assert body[field] is None
    row = db.query(Telemetry).filter(Telemetry.device_id == device.id).one()
    assert row.quality["dropped_values"] == [field]


@pytest.mark.parametrize("field,value", [
    ("temperature", 250.0), ("temperature", -90.0), ("humidity", 0.0), ("pressure", 300.0), ("vibration_x", -160.0),
    ("contact_temp", 125.0), ("shaft_angle", 360.0),
])
def test_the_edges_of_a_range_are_accepted(client, db, device, field, value):
    assert _post(client, device, **{field: value})[field] == value


def test_a_marked_reading_is_left_out_of_training(client, db, device):
    # the training query refuses a row whose quality has any of these keys (services/training_data.py)
    _post(client, device, temperature=1e308, humidity=40.0)
    _post(client, device, temperature=99.0, faults={"bme280": "missing"})
    left_out = db.execute(
        text(
            "SELECT count(*) FROM telemetry WHERE device_id = CAST(:d AS uuid) "
            "AND quality ?| ARRAY['faults', 'rejected', 'dropped_health', 'dropped_values']"
        ),
        {"d": str(device.id)},
    ).scalar()
    assert left_out == 2


def test_the_node_type_is_a_short_plain_name(client, db, device):
    assert _post(client, device, temperature=20.0, node_type="ESP32")["node_type"] == "esp32"
    for bad in ("=HYPERLINK(\"x\")", "-1+1", "@SUM(1)", "a b", "x" * 21, "+cmd"):
        body = _post(client, device, temperature=20.0, node_type=bad)
        assert body["node_type"] is None, bad
