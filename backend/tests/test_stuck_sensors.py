"""
The stuck sensor check: a value that stops moving is a sensor fault, raised through the sensor alert path and never nagging.
"""

import random


from app.models.alert import Alert
from app.services import health_service, stuck_sensors as ss


def _feed(state, readings, start=0.0, interval=5.0):
    flagged_at = None
    for i, reading in enumerate(readings):
        t = start + i * interval
        state, stuck = ss.update(state, reading, t, interval)
        if stuck and flagged_at is None:
            flagged_at = t
    return state, flagged_at


def _moving(n, seed=1, step=0.05):
    rng = random.Random(seed)
    return [{"temperature": 22.0 + rng.choice((-1, 1)) * step * rng.randint(1, 5)} for _ in range(n)]


def test_a_moving_value_is_never_flagged():
    _, flagged = _feed({}, _moving(2000))
    assert flagged is None


def test_a_value_that_freezes_is_flagged_after_its_period_and_not_before():
    state, _ = _feed({}, _moving(200))
    rule = ss.STUCK_RULES["temperature"]
    frozen = [{"temperature": 23.17}] * int(rule.min_s / 5 + 20)
    _, flagged = _feed(state, frozen, start=2000.0)
    assert flagged is not None
    # not before the table's period (600 s), to within one reading
    assert flagged - 2000.0 >= rule.min_s - 5
    # and just inside it, nothing
    _, early = _feed(state, frozen[: int(rule.min_s / 5) - 2], start=2000.0)
    assert early is None


def test_a_column_that_has_always_been_flat_is_not_stuck():
    # a machine's constant is its normal: it never moved, so a flat spell is not a change of state
    _, flagged = _feed({}, [{"temperature": 21.0}] * 5000)
    assert flagged is None


def test_a_column_that_barely_moved_is_not_judged_either():
    readings = [{"temperature": 21.0}] * 2000 + [{"temperature": 21.5}] * 3000
    _, flagged = _feed({}, readings)
    assert flagged is None


def test_a_zero_at_rest_is_not_stuck_for_columns_that_can_rest_at_zero():
    state, _ = _feed({}, [{"current_ma": 100.0 + (i % 7) * 3.0} for i in range(300)])
    _, flagged = _feed(state, [{"current_ma": 0.0}] * 3000, start=2000.0)
    assert flagged is None
    # a temperature of zero is not a resting value: it is flagged like any other
    state, _ = _feed({}, _moving(200))
    _, flagged = _feed(state, [{"temperature": 0.0}] * 400, start=2000.0)
    assert flagged is not None


def test_a_silent_stretch_does_not_count_as_flat_time():
    state, _ = _feed({}, _moving(200))
    state, _ = _feed(state, [{"temperature": 23.0}], start=1000.0)
    # the node went quiet for a day and came back with the same value: only one credit of time, not a day
    _, stuck = ss.update(state, {"temperature": 23.0}, 1000.0 + 86_400.0, 5.0)
    assert stuck == {}


def test_it_clears_the_moment_the_value_moves():
    state, _ = _feed({}, _moving(200))
    state, flagged = _feed(state, [{"temperature": 23.0}] * 200, start=2000.0)
    assert flagged is not None
    state, stuck = ss.update(state, {"temperature": 23.4}, 5000.0, 5.0)
    assert stuck == {}


def test_a_flag_is_kept_while_the_column_is_missing_and_clears_when_it_moves():
    state, _ = _feed({}, _moving(200))
    state, flagged = _feed(state, [{"temperature": 23.0}] * 200, start=2000.0)
    assert flagged is not None
    state, stuck = ss.update(state, {}, 6000.0, 5.0)
    assert stuck == {"bme280": "stuck"}


def test_a_coarse_rounding_node_teaches_the_check_its_normal_flat_spells():
    # rounded to 0.5 the temperature sits on one value for long spells. The longest healthy spell raises the bar
    rng = random.Random(3)
    readings, value = [], 22.0
    while len(readings) < 3000:
        value += rng.choice((-0.5, 0.5))
        readings += [{"temperature": value}] * rng.randint(20, 150)   # up to 750 s flat
    _, flagged = _feed({}, readings)
    assert flagged is None


def test_the_table_has_a_reason_for_every_row_and_names_what_it_leaves_out():
    assert all(rule.why for rule in ss.STUCK_RULES.values())
    assert set(ss.NOT_CHECKED) == {"distance_mm", "shaft_angle", "fft_peak_hz"}
    assert not set(ss.NOT_CHECKED) & set(ss.STUCK_RULES)


# -- through the post -------------------------------------------------------------------------

def _post(client, device, **fields):
    res = client.post(
        "/api/v1/telemetry", json={"device_id": str(device.id), **fields}, headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_a_stuck_sensor_raises_one_sensor_alert_through_the_fault_path(client, db, device, monkeypatch):
    monkeypatch.setattr(health_service, "FAULT_ALERT_AFTER_S", 0)
    import time
    now = time.time()
    device.stuck_state = {"temperature": {"q": 2317, "f": 700.0, "m": 500, "l": 0.0, "t": now - 5, "x": False}}
    db.flush()
    body = _post(client, device, temperature=23.17)
    # the value is kept: a frozen reading may still be the true one, so nothing is hidden from the rules
    assert body["temperature"] == 23.17
    (alert,) = db.query(Alert).filter(Alert.device_id == device.id, Alert.resolved.is_(False)).all()
    assert alert.kind == "sensor" and alert.sensor_key == "bme280" and "stuck" in alert.message
    # the row is marked as suspect, so training leaves it out
    from app.models.telemetry import Telemetry
    row = db.query(Telemetry).filter(Telemetry.device_id == device.id).one()
    assert row.quality["faults"] == {"bme280": "stuck"}
    # a second post does not make a second alert
    _post(client, device, temperature=23.17)
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.resolved.is_(False)).count() == 1


def test_a_stuck_sensor_resolves_after_the_value_moves(client, db, device, monkeypatch):
    monkeypatch.setattr(health_service, "FAULT_ALERT_AFTER_S", 0)
    monkeypatch.setattr(health_service, "FAULT_CLEAR_AFTER_S", 0)
    import time
    now = time.time()
    device.stuck_state = {"temperature": {"q": 2317, "f": 700.0, "m": 500, "l": 0.0, "t": now - 5, "x": False}}
    db.flush()
    _post(client, device, temperature=23.17)
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.resolved.is_(False)).count() == 1
    _post(client, device, temperature=24.0)
    _post(client, device, temperature=24.2)
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.resolved.is_(False)).count() == 0
