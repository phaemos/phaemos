"""
The values the hub forwards from the Nano and the Black Pill, the per link counters and the names the hub and the
backend agreed for the serial links.
"""

import csv
import io
from datetime import datetime, timedelta, timezone

import pytest

from app.models.alert import Alert
from app.models.device_health import DeviceHealth
from app.models.telemetry import Telemetry

NANO = {"nano_temp": 25.1, "nano_hum": 50.7, "nano_pres": 1006.6, "nano_light": 300, "nano_moist": 700, "nano_water": False}
BLACK_PILL = {
    "fft_peak_hz": 12.5, "vib_magnitude": 1.01, "vib_rms_x": 0.012, "vib_rms_y": 0.010, "vib_rms_z": 0.031,
    "vib_peak": 0.094, "stm32_vib_x": 0.02, "stm32_vib_y": -0.01, "stm32_vib_z": 1.01,
}


def _post(client, device, expect=201, **fields):
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), **fields},
        headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == expect, res.text
    return res.json()


# -- the new columns ---------------------------------------------------------------------------------

def test_the_nano_and_black_pill_values_are_stored_and_returned(client, db, device):
    body = _post(client, device, **NANO, **BLACK_PILL)
    for name, value in {**NANO, **BLACK_PILL}.items():
        assert body[name] == value, name
    row = db.query(Telemetry).filter(Telemetry.device_id == device.id).one()
    assert row.nano_water is False and row.vib_peak == 0.094 and row.stm32_vib_z == 1.01


def test_a_node_that_sends_none_of_them_stores_nulls_and_not_false(client, db, device):
    body = _post(client, device, temperature=20.0)
    for name in {**NANO, **BLACK_PILL}.keys() - {"fft_peak_hz", "vib_magnitude"}:
        assert body[name] is None, name


# the sensor key each field is reported against (sensor_map.FIELD_SENSOR). The Nano's light and moisture inputs have no key of
# their own, so the link to the Nano is the key
@pytest.mark.parametrize("field,value,sensor", [
    ("nano_temp", 500.0, "nano_bme280"), ("nano_temp", -90.0, "nano_bme280"), ("nano_hum", 120.0, "nano_bme280"),
    ("nano_pres", 5.0, "nano_bme280"), ("nano_light", 2000, "nano_link"), ("nano_moist", -3, "nano_link"),
    ("vib_rms_x", 40.0, "stm32_mpu6050"), ("vib_rms_z", -0.1, "stm32_mpu6050"), ("vib_peak", 99.0, "stm32_mpu6050"),
    ("stm32_vib_y", 50.0, "stm32_mpu6050"),
])
def test_a_value_no_part_could_produce_is_dropped_and_the_reading_is_kept(client, db, device, field, value, sensor):
    body = _post(client, device, temperature=21.0, **{field: value})
    assert body["temperature"] == 21.0
    assert body[field] is None
    # the value is named and the sensor behind it is marked out of range on the row. Training leaves the row out
    assert body["quality"] == {"dropped_values": [field], "faults": {sensor: "out_of_range"}}


def test_one_impossible_value_opens_no_alert_and_a_persistent_one_does_after_a_minute(db, device):
    from datetime import datetime, timedelta, timezone
    from app.models.alert import Alert
    from app.services.health_service import HealthResult, track_server_faults

    t0 = datetime(2030, 1, 1, tzinfo=timezone.utc)
    fault = {"nano_bme280": "out_of_range"}

    def alerts():
        return db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "sensor").count()

    # a single corrupted frame, then good readings. Repeated many times in an hour it is still not an intermittent sensor
    for n in range(8):
        at = t0 + timedelta(minutes=n * 5)
        track_server_faults(db, device, fault, {}, at, HealthResult())
        track_server_faults(db, device, {}, fault, at + timedelta(seconds=5), HealthResult())
    assert alerts() == 0
    # the same fault held for the debounce raises the one alert and not before
    base = t0 + timedelta(hours=2)
    for seconds in (0, 20, 59):
        track_server_faults(db, device, fault, fault if seconds else {}, base + timedelta(seconds=seconds), HealthResult())
    assert alerts() == 0
    track_server_faults(db, device, fault, fault, base + timedelta(seconds=61), HealthResult())
    assert alerts() == 1


def test_a_dropped_value_with_no_sensor_behind_it_is_named_and_raises_no_fault(client, db, device):
    # node_type belongs to no sensor, so only dropped_values says so and no sensor is marked
    body = _post(client, device, temperature=21.0, node_type="=x")
    assert body["node_type"] is None
    assert body["quality"] == {"dropped_values": ["node_type"]}


def test_values_at_the_limits_are_kept(client, device):
    body = _post(client, device, nano_temp=85.0, nano_hum=100.0, nano_pres=300.0, nano_light=1023, vib_peak=32.0,
                 stm32_vib_x=-16.0, vib_rms_y=0.0)
    assert body["nano_temp"] == 85.0 and body["vib_peak"] == 32.0 and body["stm32_vib_x"] == -16.0
    assert body["quality"] is None


def test_a_node_cannot_name_its_own_dropped_values(client, device):
    body = _post(client, device, temperature=20.0, dropped_values=["nano_temp"])
    assert body["quality"] is None


def test_a_value_that_is_not_a_finite_number_is_still_refused(client, device):
    _post(client, device, expect=422, nano_temp="warm")
    res = client.post(
        "/api/v1/telemetry",
        content=b'{"device_id": "%s", "vib_peak": Infinity}' % str(device.id).encode(),
        headers={"X-API-Key": device.api_key, "Content-Type": "application/json"},
    )
    assert res.status_code == 422


# -- a fault on the satellites -------------------------------------------------------------------------

def test_a_dead_nano_link_stops_every_nano_value_and_keeps_what_was_sent(client, db, device):
    body = _post(client, device, temperature=20.0, **NANO, faults={"nano_link": "silent"})
    for name in NANO:
        assert body[name] is None, name
    assert body["temperature"] == 20.0
    assert body["quality"]["faults"] == {"nano_link": "silent"}
    assert body["quality"]["rejected"]["nano_temp"] == 25.1
    # a stopped flag is null and not false
    assert body["nano_water"] is None


def test_a_faulted_nano_sensor_stops_its_three_values_only(client, device):
    body = _post(client, device, **NANO, faults={"nano_bme280": "stuck"})
    assert body["nano_temp"] is None and body["nano_hum"] is None and body["nano_pres"] is None
    assert body["nano_light"] == 300 and body["nano_moist"] == 700 and body["nano_water"] is False


def test_the_black_pill_sensor_and_its_link_stop_the_same_values(client, device):
    for key, state in (("stm32_mpu6050", "stuck"), ("stm32_link", "garbage"), ("stm32", "one_way")):
        body = _post(client, device, temperature=20.0, **BLACK_PILL, faults={key: state})
        for name in BLACK_PILL:
            assert body[name] is None, (key, name)
        assert body["temperature"] == 20.0


def test_the_supply_keys_stop_nothing_but_are_kept(client, db, device):
    body = _post(client, device, **NANO, faults={"nano_supply": "out_of_range", "supply": "out_of_range"})
    assert body["nano_temp"] == 25.1
    assert body["quality"]["faults"] == {"nano_supply": "out_of_range", "supply": "out_of_range"}


# -- the per link counters ---------------------------------------------------------------------------------

LINKS = {
    "nano": {"ok": 1042, "crc": 0, "gaps": 0, "restarts": 0, "st": 0, "up": 5210, "vcc": 4980},
    "stm32": {"ok": 998, "crc": 2, "gaps": 1, "restarts": 1, "st": 4, "up": 5200, "vcc": 3290},
}


def test_the_links_are_stored_and_returned_in_health(client, db, device, auth_headers):
    _post(client, device, boot=1, links=LINKS)
    assert db.get(DeviceHealth, device.id).links == LINKS
    health = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()["health"]
    assert health["links"] == LINKS


def test_a_later_post_replaces_the_links(client, db, device):
    _post(client, device, boot=1, links=LINKS)
    _post(client, device, boot=1, links={"nano": {"ok": 1100}})
    assert db.get(DeviceHealth, device.id).links == {"nano": {"ok": 1100}}


@pytest.mark.parametrize("bad", [
    {"nano": {"ok": -1}}, {"nano": {"st": 70000}}, {"nano": {"vcc": 100000}}, {"nano": {"ok": "many"}},
    {"nano": {"up": 1.5}}, {"nano": {"ok": True}},
])
def test_a_bad_link_value_is_dropped_and_the_rest_kept(client, db, device, bad):
    body = _post(client, device, temperature=20.0, boot=1, links={"nano": {"crc": 3, **bad["nano"]}})
    assert body["temperature"] == 20.0
    assert body["quality"] == {"dropped_health": ["links"]}
    links = db.get(DeviceHealth, device.id).links
    assert links == {"nano": {"crc": 3}}


def test_a_links_field_that_is_not_an_object_is_dropped_and_the_last_links_stay(client, db, device):
    _post(client, device, boot=1, links=LINKS)
    body = _post(client, device, temperature=20.0, boot=1, links=["nano"])
    assert body["quality"] == {"dropped_health": ["links"]}
    assert db.get(DeviceHealth, device.id).links == LINKS


def test_only_four_links_are_kept_and_names_are_cleaned(client, db, device):
    many = {f"link{i}": {"ok": i} for i in range(7)}
    body = _post(client, device, boot=1, links={**many, "  NANO  ": {"ok": 1}, "bad\u0000": {"ok": 1}})
    assert body["quality"] == {"dropped_health": ["links"]}
    assert len(db.get(DeviceHealth, device.id).links) == 4


def test_a_link_entry_that_is_not_an_object_is_dropped(client, db, device):
    _post(client, device, boot=1, links={"nano": 5, "stm32": {"ok": 2}})
    assert db.get(DeviceHealth, device.id).links == {"stm32": {"ok": 2}}


def test_a_post_with_links_alone_counts_as_a_health_post(client, db, device):
    _post(client, device, links=LINKS)
    row = db.get(DeviceHealth, device.id)
    assert row is not None and row.links == LINKS


# -- the new states ------------------------------------------------------------------------------------------

def test_the_new_link_states_are_stored_as_sent(client, db, device):
    body = _post(client, device, faults={"nano_link": "garbage", "stm32_link": "one_way", "nano_bme280": "stuck"})
    assert body["quality"]["faults"] == {"nano_link": "garbage", "stm32_link": "one_way", "nano_bme280": "stuck"}


def test_a_garbage_link_raises_a_fault_alert_in_plain_words(db, device):
    from tests.test_fault_alerts import _seen
    for seconds in (0, 60):
        _seen(db, device, seconds, nano_link="garbage")
    alert = db.query(Alert).filter(Alert.device_id == device.id, Alert.sensor_key == "nano_link").one()
    assert alert.message.endswith("sensor nano_link is sending corrupt data (garbage)")


# -- the bucketed reads and the export ----------------------------------------------------------------------

def _rows(db, device):
    now = datetime.now(timezone.utc)
    for i, (peak, vx, water) in enumerate([(0.2, 0.5, False), (0.9, -1.5, True), (0.4, 1.0, False)]):
        db.add(Telemetry(
            device_id=device.id, recorded_at=now - timedelta(seconds=10 * i), nano_temp=20.0 + i, nano_hum=40.0 + i,
            vib_rms_x=0.1 * (i + 1), vib_peak=peak, stm32_vib_x=vx, nano_water=water,
        ))
    db.flush()
    return now


def test_the_bucketed_read_averages_the_new_values_and_keeps_the_largest_peak(client, db, device, auth_headers):
    now = _rows(db, device)
    start = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = client.get(f"/api/v1/telemetry/{device.id}?bucket=3600&from_ts={start}", headers=auth_headers)
    assert res.status_code == 200
    rows = res.json()
    assert sum(r["reading_count"] for r in rows) == 3
    merged = rows[0]
    if len(rows) == 1:
        assert merged["nano_temp"] == pytest.approx(21.0)
        assert merged["nano_hum"] == pytest.approx(41.0)
        assert merged["vib_rms_x"] == pytest.approx(0.2)
        # the peak keeps the largest and the axis keeps its mean and its largest absolute value
        assert merged["vib_peak"] == pytest.approx(0.9)
        assert merged["stm32_vib_x"] == pytest.approx((0.5 - 1.5 + 1.0) / 3)
        assert merged["stm32_vib_x_peak"] == pytest.approx(1.5)
        assert merged["nano_water"] is True
    else:
        # the three rows straddled a bucket edge. The new keys are still present in every row
        for key in ("nano_temp", "vib_peak", "stm32_vib_x_peak", "nano_water"):
            assert key in merged


def test_the_export_has_a_column_for_each_new_value(client, db, device, auth_headers):
    _rows(db, device)
    start = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = client.get(f"/api/v1/telemetry/export?device_id={device.id}&from_ts={start}", headers=auth_headers)
    assert res.status_code == 200
    header = next(csv.reader(io.StringIO(res.text)))
    for name in (*NANO, *BLACK_PILL):
        assert name in header, name
