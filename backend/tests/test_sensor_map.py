"""
The map from sensor key to the telemetry fields it produces and the cleaning of a node's fault map.
"""

import pytest

from app.models.telemetry import Telemetry
from app.schemas.telemetry import HEALTH_FIELDS, NON_MEASUREMENT_FIELDS, TelemetryIngest
from app.services import ml_service
from app.services.sensor_map import (
    BOOLEAN_FIELDS,
    LINK_KEYS,
    STATE_WORDS,
    storable_text,
    has_unstorable_key,
    FAULT_STATES,
    SENSOR_ALIASES,
    FIELD_SENSOR,
    MAX_FAULT_ENTRIES,
    MAX_FAULT_KEY_LENGTH,
    SENSOR_FIELDS,
    clean_faults,
    faulted_fields,
)

# the ingest fields that say who sent the reading and not what a sensor measured
_NOT_SENSOR_FIELDS = NON_MEASUREMENT_FIELDS


def test_every_telemetry_field_belongs_to_a_sensor():
    ingest_fields = set(TelemetryIngest.model_fields) - _NOT_SENSOR_FIELDS - HEALTH_FIELDS
    assert ingest_fields - set(FIELD_SENSOR) == set(), "an ingest field has no sensor in services/sensor_map.py"
    # and the other way, so the map names no field that the API does not accept
    assert set(FIELD_SENSOR) - ingest_fields == set()


def test_every_sensor_column_the_model_uses_belongs_to_a_sensor():
    from app.services import training_data as td
    assert set(td.SENSOR_COLS) <= set(FIELD_SENSOR)
    # the model's one other column is the site's ambient reference, which is another node's temperature (a sensor column)
    assert ml_service.SENSOR_COLS == td.SENSOR_COLS + [td.AMBIENT_REF] and "temperature" in FIELD_SENSOR


def test_every_mapped_field_is_a_telemetry_column():
    columns = {c.name for c in Telemetry.__table__.columns}
    assert set(FIELD_SENSOR) <= columns


def test_only_a_link_shares_a_field_with_the_sensor_behind_it():
    owners: dict[str, list[str]] = {}
    for key, fields in SENSOR_FIELDS.items():
        for field in fields:
            owners.setdefault(field, []).append(key)
    for field, keys in owners.items():
        # at most one real sensor, plus the links that carry its value
        assert len([k for k in keys if k not in LINK_KEYS]) <= 1, field
    assert LINK_KEYS == {"nano_link", "stm32_link"}


def test_the_flag_fields_are_mapped():
    assert BOOLEAN_FIELDS <= set(FIELD_SENSOR)


def test_a_sensor_stops_all_of_its_fields_and_no_others():
    assert faulted_fields({"bme280": "missing"}) == {"temperature", "humidity", "pressure"}
    assert faulted_fields({"mq2": "warming_up"}) == {"gas_level", "gas_alert"}
    # a key no sensor has stops nothing
    assert faulted_fields({"toaster": "missing"}) == set()


def test_known_states_are_kept_and_others_become_unknown():
    cleaned = clean_faults({"bme280": "missing", "mpu6050": "STUCK", "ds18b20": "on fire", "ldr": 7})
    assert cleaned == {"bme280": "missing", "mpu6050": "stuck", "ds18b20": "unknown", "ldr": "unknown"}


def test_ok_means_no_fault_and_empty_means_none():
    assert clean_faults({"bme280": "ok"}) == {}
    assert clean_faults({}) == {}
    assert clean_faults(None) == {}


def test_keys_are_trimmed_lowered_and_cut():
    cleaned = clean_faults({"  BME280 ": "missing", "x" * 100: "stuck"})
    assert "bme280" in cleaned
    assert ("x" * MAX_FAULT_KEY_LENGTH) in cleaned


def test_the_number_of_entries_is_capped():
    cleaned = clean_faults({f"s{i}": "missing" for i in range(MAX_FAULT_ENTRIES + 10)})
    assert len(cleaned) == MAX_FAULT_ENTRIES


def test_a_list_is_not_a_fault_map():
    with pytest.raises(ValueError):
        clean_faults(["bme280"])


def test_the_agreed_sensor_keys_are_all_known():
    agreed = {
        "bme280", "mpu6050", "ina219", "mlx90614", "vl53l0x", "as5600", "ds18b20", "mq2", "ldr", "max4466", "fc28",
        "nano_link", "stm32_link", "supply",
        # step 2
        "nano_bme280", "nano_supply", "stm32_mpu6050",
    }
    assert set(SENSOR_FIELDS) == agreed


def test_the_supply_keys_stop_no_telemetry_field():
    assert SENSOR_FIELDS["supply"] == () and SENSOR_FIELDS["nano_supply"] == ()
    assert faulted_fields({"supply": "out_of_range", "nano_supply": "out_of_range"}) == set()
    # and a fault on them is still recognised and kept
    assert clean_faults({"nano_supply": "out_of_range", "supply": "out_of_range"}) == {
        "nano_supply": "out_of_range", "supply": "out_of_range",
    }


def test_the_nano_sensor_stops_its_three_values_and_the_link_stops_every_nano_value():
    assert faulted_fields({"nano_bme280": "missing"}) == {"nano_temp", "nano_hum", "nano_pres"}
    every_nano = {f for f in FIELD_SENSOR if f.startswith("nano_")}
    assert every_nano == {"nano_temp", "nano_hum", "nano_pres", "nano_light", "nano_moist", "nano_water"}
    assert faulted_fields({"nano_link": "silent"}) == every_nano


def test_the_black_pill_sensor_and_link_stop_the_same_ten_fields():
    ten = {
        "fft_peak_hz", "vib_magnitude", "vib_rms_x", "vib_rms_y", "vib_rms_z", "vib_peak",
        "stm32_vib_x", "stm32_vib_y", "stm32_vib_z", "vib_clipping",
    }
    assert faulted_fields({"stm32_mpu6050": "stuck"}) == ten
    assert faulted_fields({"stm32_link": "garbage"}) == ten


def test_the_nano_flag_is_a_boolean_field():
    assert "nano_water" in BOOLEAN_FIELDS


def test_stm32_is_an_alias_of_stm32_link():
    assert SENSOR_ALIASES == {"stm32": "stm32_link"}
    assert faulted_fields({"stm32": "missing"}) == faulted_fields({"stm32_link": "missing"})
    # stored under the one name, so a map never holds both
    assert clean_faults({"stm32": "silent"}) == {"stm32_link": "silent"}


def test_the_firmware_states_are_known():
    for state in ("unplugged", "line_low", "silent", "stuck", "garbage", "one_way"):
        assert state in FAULT_STATES
    assert clean_faults({"fc28": "unplugged", "stm32_link": "line_low", "nano_link": "silent"}) == {
        "fc28": "unplugged", "stm32_link": "line_low", "nano_link": "silent",
    }
    assert clean_faults({"nano_link": "garbage", "stm32_link": "one_way"}) == {
        "nano_link": "garbage", "stm32_link": "one_way",
    }


def test_every_state_has_words_for_an_alert():
    for state in FAULT_STATES:
        assert state in STATE_WORDS
    assert "unknown" in STATE_WORDS


def test_text_with_a_control_character_or_a_lone_surrogate_cannot_be_stored():
    assert storable_text("1.0.4") and storable_text("poweron") and storable_text("reset \u00e9")
    assert not storable_text("1.0\u0000") and not storable_text("a\nb") and not storable_text("x\ud800")
    assert not storable_text(5)


def test_a_fault_key_that_cannot_be_stored_is_left_out_and_the_rest_kept():
    raw = {"bme280\u0000": "missing", "ldr": "stuck", "x\ud800": "missing"}
    assert has_unstorable_key(raw)
    assert clean_faults(raw) == {"ldr": "stuck"}
