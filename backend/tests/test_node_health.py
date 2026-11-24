"""
Health fields on the telemetry post: validation, storage, the fault that stops a sensor, lost posts, restart loops
and what the API returns.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.models.alert import Alert, AlertRule
from app.models.device_health import DeviceHealth
from app.models.telemetry import Telemetry
from app.services import health_service, sensor_map


def _post(client, device, expect=201, **fields):
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), **fields},
        headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == expect, res.text
    return res.json()


def _rule(db, device, metric="temperature", threshold=50.0, severity="warning"):
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric=metric, condition="gt", threshold=threshold, severity=severity))
    db.flush()


def _latest(db, device):
    return db.query(Telemetry).filter(Telemetry.device_id == device.id).order_by(Telemetry.recorded_at.desc()).first()


FULL_HEALTH = {
    "seq": 41, "boot": 7, "up": 3600, "ts": 1_790_000_000,
    "faults": {"bme280": "missing"}, "reset_reason": "poweron", "rssi": -61, "heap_free": 180_000, "fw": "2.4.1",
}
# the same without the (boot, seq) pair. A machine that has sent the pair must always send it, so a test of a later post that
# carries no health fields at all starts from this
NO_PAIR = {k: v for k, v in FULL_HEALTH.items() if k not in ("seq", "boot")}


# -- a current node keeps working ----------------------------------------------------------------

def test_a_post_with_no_health_fields_still_works_and_stores_no_health(client, db, device):
    body = _post(client, device, temperature=24.1, humidity=55.0)
    assert body["temperature"] == 24.1
    assert body["seq"] is None and body["device_ts"] is None and body["quality"] is None
    assert db.get(DeviceHealth, device.id) is None


def test_a_node_with_the_nano_fields_it_always_sent_is_still_accepted(client, device):
    # the hub also posts nano_* fields that the schema does not know. They are ignored, not refused
    _post(client, device, temperature=24.1, nano_temp=22.0, nano_light=100)


# -- storage ----------------------------------------------------------------------------------

def test_the_health_fields_are_stored(client, db, device):
    # no reading is sent, so nothing is rejected and quality holds the faults alone
    _post(client, device, **FULL_HEALTH)
    row = _latest(db, device)
    assert row.seq == 41
    assert row.device_ts == datetime.fromtimestamp(1_790_000_000, tz=timezone.utc)
    assert row.quality == {"faults": {"bme280": "missing"}}

    health = db.get(DeviceHealth, device.id)
    assert (health.boot_count, health.uptime_s, health.reset_reason) == (7, 3600, "poweron")
    assert (health.rssi, health.heap_free, health.firmware_version, health.last_seq) == (-61, 180_000, "2.4.1", 41)
    assert health.faults == {"bme280": "missing"}
    assert health.reported_at is not None


def test_the_health_fields_never_reach_the_readings_or_the_rules(client, db, device):
    body = _post(client, device, temperature=24.1, **FULL_HEALTH)
    # the response carries the stored row, which has no column named after a health field
    assert "boot" not in body and "rssi" not in body and "faults" not in body


def test_the_firmware_version_the_node_reports_does_not_touch_the_ota_target(client, db, device):
    device.firmware_version = "9.9.9"
    db.flush()
    _post(client, device, temperature=24.1, fw="2.4.1")
    db.refresh(device)
    assert device.firmware_version == "9.9.9"
    assert db.get(DeviceHealth, device.id).firmware_version == "2.4.1"


def test_a_later_post_replaces_the_faults_and_keeps_what_it_leaves_out(client, db, device):
    _post(client, device, temperature=24.1, **FULL_HEALTH)
    _post(client, device, temperature=24.2, seq=42, boot=7, up=3605)
    health = db.get(DeviceHealth, device.id)
    # absent faults means nothing is wrong
    assert health.faults == {}
    assert health.uptime_s == 3605 and health.last_seq == 42
    # a vital the second post did not send keeps its last value
    assert health.rssi == -61 and health.firmware_version == "2.4.1"


def test_a_post_with_no_health_fields_leaves_the_latest_vitals_alone(client, db, device):
    _post(client, device, temperature=24.1, **NO_PAIR)
    _post(client, device, temperature=24.2)
    assert db.get(DeviceHealth, device.id).faults == {"bme280": "missing"}


# -- validation -------------------------------------------------------------------------------

def test_unknown_fault_states_are_stored_as_unknown(client, db, device):
    _post(client, device, temperature=24.1, faults={"ds18b20": "melting", "ldr": "stuck"})
    assert _latest(db, device).quality["faults"] == {"ds18b20": "unknown", "ldr": "stuck"}


def test_ok_and_empty_fault_maps_store_no_quality(client, db, device):
    _post(client, device, temperature=24.1, faults={"bme280": "ok"})
    assert _latest(db, device).quality is None
    _post(client, device, temperature=24.1, faults={})
    assert _latest(db, device).quality is None
    # null in the database and not a JSON null
    assert db.execute(text("SELECT count(*) FROM telemetry WHERE device_id = CAST(:d AS uuid) AND quality IS NULL"), {"d": str(device.id)}).scalar() == 2


def test_an_oversized_fault_map_is_cut_and_not_refused(client, db, device):
    faults = {f"sensor_{i}": "missing" for i in range(60)}
    _post(client, device, temperature=24.1, faults=faults)
    assert len(_latest(db, device).quality["faults"]) == sensor_map.MAX_FAULT_ENTRIES


@pytest.mark.parametrize("field,value", [
    ("seq", -1), ("boot", -3), ("up", -1), ("ts", 5), ("rssi", -500), ("rssi", 300), ("heap_free", -1),
    ("reset_reason", "x" * 200), ("fw", "v" * 200), ("seq", "many"), ("up", 1.5), ("boot", True),
])
def test_a_bad_health_field_is_dropped_and_the_reading_is_kept(client, db, device, field, value):
    body = _post(client, device, temperature=24.1, **{field: value})
    assert body["temperature"] == 24.1
    assert body["quality"] == {"dropped_health": [field]}
    health = db.get(DeviceHealth, device.id)
    assert health.dropped_fields == 1


def test_a_malformed_faults_field_is_dropped_and_the_reading_is_kept(client, db, device):
    body = _post(client, device, temperature=24.1, faults=["bme280"])
    assert body["temperature"] == 24.1
    assert body["quality"] == {"dropped_health": ["faults"]}


def test_good_fields_in_the_same_post_are_still_stored(client, db, device):
    _post(client, device, temperature=24.1, seq=5, boot=2, rssi=-500, fw="2.0")
    health = db.get(DeviceHealth, device.id)
    assert (health.last_seq, health.boot_count, health.firmware_version) == (5, 2, "2.0")
    assert health.rssi is None
    assert health.dropped_fields == 1
    assert _latest(db, device).quality == {"dropped_health": ["rssi"]}


def test_a_dropped_field_is_counted_every_time_and_shown_by_the_api(client, db, device, auth_headers):
    _post(client, device, temperature=24.1, rssi=-500)
    _post(client, device, temperature=24.1, rssi=999, heap_free=-5)
    one = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()
    assert one["health"]["dropped_fields"] == 3


def test_a_post_of_only_bad_fields_leaves_the_latest_faults_and_vitals(client, db, device):
    _post(client, device, **NO_PAIR)
    _post(client, device, temperature=24.1, rssi=-500)
    health = db.get(DeviceHealth, device.id)
    assert health.faults == {"bme280": "missing"}
    assert health.rssi == -61
    assert health.dropped_fields == 1


def test_a_dropped_faults_field_does_not_clear_the_last_fault_map(client, db, device):
    _post(client, device, **FULL_HEALTH)
    _post(client, device, seq=42, boot=7, faults="broken")
    health = db.get(DeviceHealth, device.id)
    assert health.faults == {"bme280": "missing"}
    assert health.last_seq == 42


def test_a_node_cannot_name_its_own_dropped_fields(client, db, device):
    body = _post(client, device, temperature=24.1, dropped_health=["rssi"])
    assert body["quality"] is None
    assert db.get(DeviceHealth, device.id) is None


def test_the_reading_values_keep_their_strict_validation(client, device):
    # only health fields are forgiving. A sensor value that is not a finite number still answers 422
    res = client.post(
        "/api/v1/telemetry",
        content=b"{\"device_id\": \"%s\", \"temperature\": NaN}" % str(device.id).encode(),
        headers={"X-API-Key": device.api_key, "Content-Type": "application/json"},
    )
    assert res.status_code == 422
    _post(client, device, expect=422, temperature="hot")


# -- a fault stops its sensor ------------------------------------------------------------------

def test_a_faulted_sensor_does_not_fire_its_rule_and_is_stored_as_null(client, db, device):
    _rule(db, device, "temperature", 50.0)
    body = _post(client, device, temperature=180.0, humidity=40.0, faults={"bme280": "out_of_range"})
    assert body["temperature"] is None and body["humidity"] is None
    assert db.query(Alert).filter(Alert.device_id == device.id).count() == 0
    row = _latest(db, device)
    assert row.temperature is None
    # the value the node sent is not lost: it sits in the quality record
    assert row.quality == {
        "faults": {"bme280": "out_of_range"},
        "rejected": {"temperature": 180.0, "humidity": 40.0},
    }


def test_the_same_reading_without_the_fault_does_fire_the_rule(client, db, device):
    _rule(db, device, "temperature", 50.0)
    _post(client, device, temperature=180.0)
    assert db.query(Alert).filter(Alert.device_id == device.id).count() == 1


def test_a_fault_stops_only_the_sensor_it_names(client, db, device):
    _rule(db, device, "contact_temp", 50.0)
    body = _post(client, device, temperature=180.0, contact_temp=90.0, faults={"bme280": "stuck"})
    assert body["temperature"] is None
    assert body["contact_temp"] == 90.0
    assert db.query(Alert).filter(Alert.device_id == device.id).count() == 1


def test_a_stopped_flag_is_null_and_not_false(client, db, device):
    body = _post(client, device, gas_level=3000.0, gas_alert=True, faults={"mq2": "warming_up"})
    assert body["gas_level"] is None and body["gas_alert"] is None
    assert db.execute(text("SELECT gas_alert FROM telemetry WHERE device_id = CAST(:d AS uuid)"), {"d": str(device.id)}).scalar() is None


def test_a_fault_naming_no_known_sensor_stops_nothing(client, db, device):
    body = _post(client, device, temperature=24.1, faults={"toaster": "missing"})
    assert body["temperature"] == 24.1
    assert _latest(db, device).quality == {"faults": {"toaster": "missing"}}


def test_a_reading_that_lacks_a_stopped_sensor_is_not_scored(client, db, device, monkeypatch):
    from app.services import ml_service

    class _Fake:
        phaemos_features = ["temperature"]
        phaemos_schema = 2
        offset_ = 0.0
        phaemos_typical_decision = 0.1

        def score_samples(self, X):
            return [-0.5] * len(X)

    monkeypatch.setattr(ml_service, "_model", {"default": _Fake()})
    body = _post(client, device, temperature=180.0, faults={"bme280": "out_of_range"})
    assert body["anomaly_score"] is None and body["is_anomaly"] is False


# -- lost posts and restarts ---------------------------------------------------------------------

def test_a_jump_in_the_sequence_counts_the_lost_posts(client, db, device):
    _post(client, device, temperature=24.1, seq=10, boot=1)
    _post(client, device, temperature=24.1, seq=11, boot=1)
    assert db.get(DeviceHealth, device.id).lost_posts == 0
    _post(client, device, temperature=24.1, seq=15, boot=1)
    health = db.get(DeviceHealth, device.id)
    assert health.lost_posts == 3
    assert health.last_gap_at is not None
    # recording a gap raises no alert
    assert db.query(Alert).filter(Alert.device_id == device.id).count() == 0


def test_a_repeat_or_a_restart_of_the_counter_is_not_a_gap(client, db, device):
    _post(client, device, temperature=24.1, seq=50, boot=1)
    # the same pair again is a retry of a post whose answer was lost: a 200 with a marker and nothing stored
    _post(client, device, temperature=24.1, seq=50, boot=1, expect=200)
    # a boot restarts the counter at zero. That proves nothing about lost posts
    _post(client, device, temperature=24.1, seq=0, boot=2)
    _post(client, device, temperature=24.1, seq=1, boot=2)
    assert db.get(DeviceHealth, device.id).lost_posts == 0


def _boots(client, device, counts):
    for n, boot in enumerate(counts):
        _post(client, device, temperature=24.1, seq=n, boot=boot)


def test_three_boots_in_ten_minutes_open_one_monitoring_alert(client, db, device, monkeypatch):
    sent = []
    monkeypatch.setattr(health_service.alert_service, "notify_monitoring", lambda *a, **k: sent.append(a))
    _boots(client, device, [1, 2, 3, 4, 5, 6])
    alerts = db.query(Alert).filter(Alert.device_id == device.id).all()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.category == "monitoring" and alert.severity == "warning" and alert.rule_id is None
    assert alert.message == f"{device.name} has restarted 3 times in 10 minutes"
    # one notification and not one per post
    assert len(sent) == 1


def test_two_boots_are_not_a_loop(client, db, device):
    _boots(client, device, [1, 2, 3])
    assert db.query(Alert).filter(Alert.device_id == device.id).count() == 0


def test_boots_older_than_ten_minutes_do_not_count(db, device):
    now = datetime.now(timezone.utc)
    row = DeviceHealth(
        device_id=device.id,
        boot_events=[(now - timedelta(minutes=m)).isoformat() for m in (30, 20, 11)],
    )
    assert row.recent_boots(now) == 0
    assert not row.in_reset_loop(now)
    row.boot_events.append((now - timedelta(minutes=1)).isoformat())
    assert row.recent_boots(now) == 1


# -- the API ------------------------------------------------------------------------------------

def test_the_device_routes_return_the_link_state_age_and_health(client, db, device, auth_headers):
    device.last_seen = datetime.now(timezone.utc) - timedelta(seconds=30)
    device.link_state = "late"
    db.flush()
    _post(client, device, temperature=24.1, **FULL_HEALTH)
    # the post made the node online again
    one = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()
    assert one["link_state"] == "online"
    assert one["expected_interval_s"] == 5
    assert 0 <= one["seconds_since_last_post"] < 10
    health = one["health"]
    assert health["boot_count"] == 7 and health["uptime_s"] == 3600 and health["rssi"] == -61
    assert health["heap_free"] == 180_000 and health["firmware_version"] == "2.4.1" and health["last_seq"] == 41
    assert health["faults"] == {"bme280": "missing"}
    assert health["reported_at"] is not None
    assert health["lost_posts"] == 0 and health["reset_loop"] is False

    listed = [d for d in client.get("/api/v1/devices", headers=auth_headers).json() if d["id"] == str(device.id)][0]
    assert listed["health"] == health
    assert listed["link_state"] == "online"


def test_a_device_with_no_health_has_null_health_and_keeps_every_old_field(client, db, device, auth_headers):
    one = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()
    assert one["health"] is None
    assert one["seconds_since_last_post"] is None
    for field in ("id", "name", "location", "type", "status", "last_seen", "firmware_version", "created_at", "owner_id", "tags"):
        assert field in one


def test_the_alert_list_filters_by_category_and_returns_category_and_sensor_key(client, db, device, auth_headers):
    machine = Alert(device_id=device.id, message="hot", severity="warning", resolved=False)
    monitoring = Alert(
        device_id=device.id, message="quiet", severity="warning", resolved=False,
        category="monitoring", sensor_key="bme280",
    )
    db.add_all([machine, monitoring])
    db.flush()

    everything = client.get("/api/v1/alerts", headers=auth_headers).json()
    assert {a["id"] for a in everything} == {str(machine.id), str(monitoring.id)}
    by_id = {a["id"]: a for a in everything}
    assert by_id[str(machine.id)]["category"] == "machine" and by_id[str(machine.id)]["sensor_key"] is None
    assert by_id[str(monitoring.id)]["category"] == "monitoring" and by_id[str(monitoring.id)]["sensor_key"] == "bme280"

    only = client.get("/api/v1/alerts?category=monitoring", headers=auth_headers).json()
    assert [a["id"] for a in only] == [str(monitoring.id)]
    only = client.get("/api/v1/alerts?category=machine&resolved=false", headers=auth_headers).json()
    assert [a["id"] for a in only] == [str(machine.id)]
    assert client.get("/api/v1/alerts?category=bogus", headers=auth_headers).status_code == 422


def test_an_existing_alert_with_no_category_reads_as_a_machine_alert(db, device):
    alert = Alert(device_id=device.id, message="hot", severity="warning", resolved=False)
    db.add(alert)
    db.flush()
    assert alert.category == "machine"


# -- text the database cannot store ------------------------------------------------------------------------

def _post_raw(client, device, body: bytes):
    res = client.post(
        "/api/v1/telemetry", content=body,
        headers={"X-API-Key": device.api_key, "Content-Type": "application/json"},
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.parametrize("field,literal", [
    ("fw", '"1.0\\u0000"'), ("reset_reason", '"pow\\u0000er"'), ("fw", '"v\\ud800"'), ("reset_reason", '"a\\nb"'),
])
def test_a_health_string_the_database_cannot_store_is_dropped_and_the_reading_is_kept(client, db, device, field, literal):
    body = _post_raw(
        client, device,
        ('{"device_id": "%s", "temperature": 22.5, "boot": 1, "%s": %s}' % (device.id, field, literal)).encode(),
    )
    assert body["temperature"] == 22.5
    assert body["quality"] == {"dropped_health": [field]}
    assert db.query(Telemetry).filter(Telemetry.device_id == device.id).count() == 1


def test_a_fault_key_with_a_nul_or_a_lone_surrogate_drops_that_key_and_keeps_the_rest(client, db, device):
    body = _post_raw(
        client, device,
        ('{"device_id": "%s", "temperature": 22.5, "faults": {"bme280\\u0000": "missing", "ldr": "stuck", '
         '"x\\ud800": "missing"}}' % device.id).encode(),
    )
    assert body["temperature"] == 22.5
    assert body["quality"] == {"faults": {"ldr": "stuck"}, "dropped_health": ["faults"]}
    assert db.get(DeviceHealth, device.id).faults == {"ldr": "stuck"}


# -- a boot counter that jumped while the node was away ---------------------------------------------------------

def test_a_boot_counter_that_jumped_while_the_node_was_away_is_not_a_restart_loop(client, db, device):
    # three boots over a week without Wi-Fi: the counter is three higher and the uptime says the latest boot was long ago
    _post(client, device, temperature=20.0, boot=1, up=500_000)
    _post(client, device, temperature=20.0, boot=4, up=250_000)
    health = db.get(DeviceHealth, device.id)
    assert health.boot_count == 4
    assert health.recent_boots(datetime.now(timezone.utc)) == 0
    assert db.query(Alert).filter(Alert.device_id == device.id).count() == 0


def test_a_jump_is_one_boot_dated_by_the_uptime(client, db, device):
    _post(client, device, temperature=20.0, boot=1, up=100)
    _post(client, device, temperature=20.0, boot=9, up=30)
    health = db.get(DeviceHealth, device.id)
    # eight in the counter but one observed, thirty seconds ago
    assert len(health.boot_events) == 1
    assert health.recent_boots(datetime.now(timezone.utc)) == 1


def test_three_boots_seen_one_after_another_are_still_a_restart_loop(client, db, device):
    for boot in (1, 2, 3, 4):
        _post(client, device, temperature=20.0, boot=boot, up=4)
    alert = db.query(Alert).filter(Alert.device_id == device.id).one()
    assert alert.message.endswith("has restarted 3 times in 10 minutes")


# -- the device read answers for the new fields ----------------------------------------------------------------

def test_the_health_read_carries_links_and_the_rules_list_and_keeps_every_older_field(client, db, device, auth_headers):
    _post(client, device, temperature=20.0, **FULL_HEALTH)
    health = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()["health"]
    for field in (
        "boot_count", "uptime_s", "reset_reason", "rssi", "heap_free", "firmware_version", "last_seq", "reported_at",
        "faults", "lost_posts", "last_gap_at", "dropped_fields", "reset_loop", "links", "rules_cannot_evaluate",
    ):
        assert field in health, field
    assert health["links"] == {} and health["rules_cannot_evaluate"] == []
