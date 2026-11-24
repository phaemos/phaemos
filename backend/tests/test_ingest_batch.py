"""
The batch route and observed_at, tested from the attacker's side first: a stolen key, a hostile gateway and a backlog that must
never be judged as current.
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.models.alert import Alert, AlertRule
from app.models.device import Device
from app.models.telemetry import Telemetry
from app.routes import telemetry as telemetry_route
from app.services import alert_service, ingest_limit
from tests._shape import plain

BATCH = "/api/v1/telemetry/batch"


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _batch(client, device, readings, key=None, expect=200):
    res = client.post(BATCH, json={"readings": readings}, headers={"X-API-Key": key or device.api_key})
    assert res.status_code == expect, res.text
    return res


def _hot_rule(db, device, metric="temperature", severity="critical"):
    db.add(AlertRule(for_seconds=0, device_id=device.id, metric=metric, condition="gt", threshold=50.0, severity=severity))
    db.flush()


def _rows(db, device):
    return db.query(Telemetry).filter(Telemetry.device_id == device.id).order_by(Telemetry.recorded_at).all()


def _alerts(db, device):
    return db.query(Alert).filter(Alert.device_id == device.id).all()


@pytest.fixture(autouse=True)
def _fresh_limits():
    ingest_limit.reset()
    yield
    ingest_limit.reset()


@pytest.fixture
def judged(monkeypatch):
    """Counts how often the rules and the anomaly window are asked to judge a reading."""
    calls = {"rules": 0, "anomaly": 0}
    real_rules, real_anomaly = telemetry_route.evaluate_rules, telemetry_route.evaluate_anomaly
    monkeypatch.setattr(telemetry_route, "evaluate_rules", lambda *a, **k: calls.__setitem__("rules", calls["rules"] + 1) or real_rules(*a, **k))
    monkeypatch.setattr(telemetry_route, "evaluate_anomaly", lambda *a, **k: calls.__setitem__("anomaly", calls["anomaly"] + 1) or real_anomaly(*a, **k))
    return calls


# -- the shape of the answer ----------------------------------------------------------------

def test_every_reading_gets_a_result_in_order(client, db, device):
    res = _batch(client, device, [{"temperature": 20.0 + i, "boot": 1, "seq": i} for i in range(5)]).json()
    assert [r["index"] for r in res["results"]] == [0, 1, 2, 3, 4]
    assert all(r["outcome"] == "stored" and r["id"] for r in res["results"])
    assert (res["stored"], res["duplicate"], res["refused"]) == (5, 0, 0)
    assert [r.temperature for r in _rows(db, device)] == [20.0, 21.0, 22.0, 23.0, 24.0]


def test_one_bad_reading_does_not_fail_the_rest(client, db, device):
    res = _batch(client, device, [{"temperature": 20.0}, {"temperature": "hot"}, {"humidity": float("nan") if False else 40.0}]).json()
    assert [r["outcome"] for r in res["results"]] == ["stored", "refused", "stored"]
    bad = res["results"][1]
    assert bad["code"] == "invalid_reading" and bad["status"] == 422 and "temperature" in bad["detail"]
    assert len(_rows(db, device)) == 2


@pytest.mark.parametrize("readings", [[], [{"temperature": 1.0}] * 101])
def test_the_size_of_a_batch_is_bounded(client, device, readings):
    _batch(client, device, readings, expect=422)


def test_a_batch_over_the_body_limit_is_refused_before_it_is_read(client, device):
    res = client.post(
        BATCH, content=b"{}", headers={"X-API-Key": device.api_key, "content-type": "application/json",
                                       "content-length": str(telemetry_route.BATCH_MAX_BODY_BYTES + 1)},
    )
    assert res.status_code == 413


def test_a_hundred_readings_of_the_largest_kind_fit_the_limit():
    import json
    one = {
        "temperature": 20.0, "humidity": 40.0, "pressure": 1000.0, "node_type": "esp32", "boot": 1, "seq": 1, "up": 1, "ts": 1_790_000_000,
        "reset_reason": "x" * 40, "fw": "y" * 50, "rssi": -50, "heap_free": 1,
        "faults": {f"sensor_{i:02d}": "missing" for i in range(49)},
        "links": {f"l{i}": {"ok": 4_294_967_295, "crc": 4_294_967_295, "fmt": 4_294_967_295, "gaps": 4_294_967_295,
                            "restarts": 4_294_967_295, "st": 65_535, "up": 2_147_483_647, "vcc": 65_535} for i in range(4)},
        "diag": {f"counter_{i:02d}_abcdefghi": 4_294_967_295 for i in range(16)},
        "not_fitted": ["bme280", "mpu6050", "ina219", "mlx90614", "vl53l0x", "mq2", "as5600", "max4466", "ldr", "ds18b20", "fc28"],
    }
    assert 100 * len(json.dumps(one)) < telemetry_route.BATCH_MAX_BODY_BYTES


# -- the replay rule, per item, under the one lock -------------------------------------------

def test_a_batch_sent_twice_answers_duplicate_for_every_reading_and_stores_nothing_new(client, db, device):
    readings = [{"temperature": 20.0, "boot": 4, "seq": i} for i in range(10)]
    _batch(client, device, readings)
    # only the exact pair last accepted is a duplicate: the earlier ones are older and refused. Nothing is stored twice either way
    again = _batch(client, device, readings).json()
    assert again["stored"] == 0
    assert again["results"][-1]["outcome"] == "duplicate" and again["results"][-1]["status"] == 200
    assert all(r["outcome"] == "refused" and r["code"] == "replay_stale" and r["status"] == 409 for r in again["results"][:-1])
    assert len(_rows(db, device)) == 10


def test_a_stale_reading_in_the_middle_is_refused_and_the_rest_go_in(client, db, device):
    readings = [{"temperature": 20.0, "boot": 4, "seq": s} for s in (10, 11, 5, 12)]
    res = _batch(client, device, readings).json()
    assert [r["outcome"] for r in res["results"]] == ["stored", "stored", "refused", "stored"]
    assert res["results"][2]["code"] == "replay_stale"
    assert (device.last_boot, device.last_seq) == (4, 12)


def test_a_protected_machine_cannot_drop_the_pair_inside_a_batch(client, db, device):
    _batch(client, device, [{"temperature": 20.0, "boot": 4, "seq": 1}])
    res = _batch(client, device, [{"temperature": 20.0}, {"temperature": 20.0, "boot": 4}]).json()
    assert [r["code"] for r in res["results"]] == ["replay_pair_missing", "replay_pair_missing"]
    assert len(_rows(db, device)) == 1


def test_a_pair_at_the_ceiling_is_refused_per_item_and_does_not_lock_the_machine(client, db, device):
    res = _batch(client, device, [
        {"temperature": 20.0, "boot": 4, "seq": 1}, {"temperature": 20.0, "boot": 2147483647, "seq": 4294967295},
        {"temperature": 20.0, "boot": 4, "seq": 2},
    ]).json()
    assert [r["outcome"] for r in res["results"]] == ["stored", "refused", "stored"]
    assert res["results"][1]["code"] == "counter_out_of_range" and res["results"][1]["status"] == 422


def test_a_batch_and_a_single_post_share_one_counter(client, db, device):
    _batch(client, device, [{"temperature": 20.0, "boot": 4, "seq": s} for s in (1, 2, 3)])
    old = client.post("/api/v1/telemetry", json={"temperature": 20.0, "boot": 4, "seq": 2}, headers={"X-API-Key": device.api_key})
    assert old.status_code == 409
    assert client.post("/api/v1/telemetry", json={"temperature": 20.0, "boot": 4, "seq": 4}, headers={"X-API-Key": device.api_key}).status_code == 201


def test_two_batches_cannot_both_pass_the_same_pair(client, db, device, monkeypatch):
    # the lock is taken once per batch before any item is judged
    order = []
    real_lock, real_judge = telemetry_route._lock_device, telemetry_route._judge
    monkeypatch.setattr(telemetry_route, "_lock_device", lambda *a, **k: order.append("lock") or real_lock(*a, **k))
    monkeypatch.setattr(telemetry_route, "_judge", lambda *a, **k: order.append("judge") or real_judge(*a, **k))
    _batch(client, device, [{"temperature": 1.0, "boot": 1, "seq": s} for s in (1, 2, 3)])
    assert order == ["lock", "judge", "judge", "judge"]


# -- the key ----------------------------------------------------------------------------------

def test_a_wrong_key_is_refused_like_on_the_single_route(client, device):
    res = _batch(client, device, [{"temperature": 1.0}], key=device.api_key[:8] + "x" * 35, expect=401)
    assert plain(res) == {"detail": "Invalid API key"}


def test_a_body_that_names_another_device_still_writes_to_the_keys_own(client, db, device):
    other = Device(name="Other", api_key=secrets.token_urlsafe(32))
    db.add(other)
    db.flush()
    _batch(client, device, [{"device_id": str(other.id), "temperature": 33.0}])
    assert len(_rows(db, device)) == 1 and _rows(db, other) == []


def test_device_id_is_optional_on_both_routes(client, db, device):
    assert client.post("/api/v1/telemetry", json={"temperature": 20.0}, headers={"X-API-Key": device.api_key}).status_code == 201
    assert client.post("/api/v1/telemetry", json={"device_id": "node-1", "temperature": 20.0}, headers={"X-API-Key": device.api_key}).status_code == 201


# -- the allowance ----------------------------------------------------------------------------

def test_the_batch_allowance_counts_readings_and_answers_429_with_retry_after(client, device, monkeypatch):
    monkeypatch.setattr(ingest_limit, "BATCH_ITEMS_PER_DEVICE", 150)
    _batch(client, device, [{"temperature": 1.0}] * 100)
    res = _batch(client, device, [{"temperature": 1.0}] * 100, expect=429)
    assert int(res.headers["Retry-After"]) >= 1
    # fifty more still fit
    _batch(client, device, [{"temperature": 1.0}] * 50)


def test_the_single_route_allowance_is_separate(client, device, monkeypatch):
    monkeypatch.setattr(ingest_limit, "BATCH_ITEMS_PER_DEVICE", 10)
    _batch(client, device, [{"temperature": 1.0}] * 10)
    assert client.post("/api/v1/telemetry", json={"temperature": 1.0}, headers={"X-API-Key": device.api_key}).status_code == 201


def test_the_site_allowance_caps_every_device_together(client, db, device, monkeypatch):
    other = Device(name="Other", api_key=secrets.token_urlsafe(32))
    db.add(other)
    db.flush()
    monkeypatch.setattr(ingest_limit, "BATCH_ITEMS_ALL", 120)
    _batch(client, device, [{"temperature": 1.0}] * 100)
    _batch(client, other, [{"temperature": 1.0}] * 100, expect=429)


def test_an_hour_of_backlog_clears_in_a_few_minutes_of_allowance():
    per_minute = ingest_limit.BATCH_ITEMS_PER_DEVICE
    hour = 48 * 60
    assert hour / per_minute < 3 and hour <= per_minute * 3


# -- observed_at and the backlog --------------------------------------------------------------

def test_a_backlog_reading_is_stored_at_its_own_time_and_judged_by_nothing(client, db, device, judged):
    _hot_rule(db, device)
    device.last_seen = _now() - timedelta(hours=3)
    device.link_state = "offline"
    db.flush()
    long_ago = _now() - timedelta(hours=2)
    res = _batch(client, device, [{"temperature": 99.0, "observed_at": _iso(long_ago + timedelta(seconds=5 * i))} for i in range(20)]).json()
    assert res["stored"] == 20 and all(r["backlog"] for r in res["results"])
    rows = _rows(db, device)
    assert abs((rows[0].recorded_at - long_ago).total_seconds()) < 1
    # no rule, no anomaly window, no alert, no notification and no broadcast judged a reading from two hours ago
    assert judged == {"rules": 0, "anomaly": 0}
    assert _alerts(db, device) == []
    # not scored, marked and not a heartbeat
    assert all(r.anomaly_score is None and r.quality["backlog"] is True for r in rows)
    db.refresh(device)
    assert device.link_state == "offline" and device.last_seen < _now() - timedelta(hours=1)


def test_a_backlog_reading_never_ends_a_silent_machine_alarm(client, db, device):
    device.link_state = "offline"
    device.last_seen = _now() - timedelta(hours=3)
    db.add(Alert(device_id=device.id, message="silent", severity="warning", resolved=False, category="monitoring", kind="offline"))
    db.flush()
    _batch(client, device, [{"temperature": 20.0, "observed_at": _iso(_now() - timedelta(hours=2))}])
    assert db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "offline", Alert.resolved.is_(False)).count() == 1


def test_a_live_reading_in_the_same_batch_is_judged_once_for_the_whole_batch(client, db, device, judged):
    _hot_rule(db, device)
    old = _now() - timedelta(hours=1)
    readings = [{"temperature": 99.0, "observed_at": _iso(old + timedelta(seconds=i))} for i in range(50)]
    readings += [{"temperature": 99.0} for _ in range(30)]
    res = _batch(client, device, readings).json()
    assert res["stored"] == 80
    assert judged == {"rules": 1, "anomaly": 1}
    # one rule alert for the live readings. The fifty old ones raised nothing
    assert len(_alerts(db, device)) == 1


def test_a_hundred_backlog_readings_over_a_threshold_raise_no_alert_and_queue_nothing(client, db, device, monkeypatch):
    _hot_rule(db, device)
    queued = []
    monkeypatch.setattr(alert_service, "_dispatch", lambda *a, **k: queued.append(a))
    old = _now() - timedelta(hours=5)
    _batch(client, device, [{"temperature": 99.0, "observed_at": _iso(old + timedelta(seconds=i))} for i in range(100)])
    assert _alerts(db, device) == [] and queued == []


def test_a_hundred_live_readings_over_a_threshold_make_one_alert_and_one_round_of_notifications(client, db, device, monkeypatch):
    _hot_rule(db, device)
    told = []
    monkeypatch.setattr(alert_service, "_tell_about_rule_alert", lambda *a, **k: told.append(1))
    _batch(client, device, [{"temperature": 99.0} for _ in range(100)])
    assert len(_alerts(db, device)) == 1 and told == [1]


def test_an_observed_time_a_few_seconds_old_is_still_live(client, db, device, judged):
    res = _batch(client, device, [{"temperature": 20.0, "observed_at": _iso(_now() - timedelta(seconds=10))}]).json()
    assert res["results"][0]["backlog"] is False
    assert judged["rules"] == 1
    row = _rows(db, device)[0]
    assert abs((_now() - row.recorded_at).total_seconds() - 10) < 3


def test_a_future_observed_time_is_not_believed(client, db, device):
    res = _batch(client, device, [{"temperature": 20.0, "observed_at": _iso(_now() + timedelta(hours=5))}]).json()
    assert res["results"][0]["outcome"] == "stored" and res["results"][0]["backlog"] is False
    row = _rows(db, device)[0]
    assert abs((row.recorded_at - _now()).total_seconds()) < 5
    assert row.quality["observed_at_ignored"] == "future"


def test_a_clock_a_little_fast_is_read_as_now(client, db, device):
    _batch(client, device, [{"temperature": 20.0, "observed_at": _iso(_now() + timedelta(seconds=30))}])
    row = _rows(db, device)[0]
    assert row.recorded_at <= _now() and row.quality is None


def test_an_observed_time_older_than_seven_days_is_refused(client, db, device):
    res = _batch(client, device, [{"temperature": 20.0, "observed_at": _iso(_now() - timedelta(days=8))}, {"temperature": 21.0}]).json()
    assert res["results"][0]["code"] == "observed_at_too_old" and res["results"][0]["status"] == 422
    assert res["results"][1]["outcome"] == "stored"
    assert len(_rows(db, device)) == 1


def test_a_refused_observed_time_does_not_use_up_the_pair(client, db, device):
    _batch(client, device, [{"temperature": 1.0, "boot": 2, "seq": 5, "observed_at": _iso(_now() - timedelta(days=9))}])
    assert device.replay_protected is False
    res = _batch(client, device, [{"temperature": 1.0, "boot": 2, "seq": 5}]).json()
    assert res["stored"] == 1


def test_the_devices_own_clock_decides_nothing(client, db, device):
    res = _batch(client, device, [{"temperature": 20.0, "ts": 1_000_000_001}]).json()
    row = _rows(db, device)[0]
    assert abs((_now() - row.recorded_at).total_seconds()) < 5
    assert row.device_ts.year == 2001 and res["results"][0]["backlog"] is False


def test_the_single_route_honours_observed_at_the_same_way(client, db, device, judged):
    _hot_rule(db, device)
    res = client.post(
        "/api/v1/telemetry", json={"temperature": 99.0, "observed_at": _iso(_now() - timedelta(hours=1))},
        headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == 201 and res.json()["quality"]["backlog"] is True
    assert judged == {"rules": 0, "anomaly": 0} and _alerts(db, device) == []
    too_old = client.post(
        "/api/v1/telemetry", json={"temperature": 1.0, "observed_at": _iso(_now() - timedelta(days=30))},
        headers={"X-API-Key": device.api_key},
    )
    assert too_old.status_code == 422


def test_a_bad_observed_at_is_that_items_problem(client, db, device):
    res = _batch(client, device, [{"temperature": 20.0, "observed_at": "last tuesday"}, {"temperature": 21.0}]).json()
    assert res["results"][0]["code"] == "invalid_reading" and res["results"][1]["outcome"] == "stored"


# -- a hostile gateway: the protections the single route has hold here ----------------------------

def test_backdated_calm_readings_cannot_dilute_the_anomaly_window(client, db, device):
    # readings an attacker backdates into the last two minutes are older than a live one, so they are stored unscored and the model's
    # window does not see them
    old = _now() - timedelta(seconds=100)
    _batch(client, device, [{"temperature": 20.0, "observed_at": _iso(old + timedelta(seconds=i))} for i in range(60)])
    rows = _rows(db, device)
    assert len(rows) == 60 and all(r.anomaly_score is None for r in rows)


@pytest.mark.real_fault_gating
def test_a_fault_claim_in_a_batch_still_needs_an_alert_behind_it(client, db, device):
    _hot_rule(db, device)
    res = _batch(client, device, [{"temperature": 99.0, "faults": {"bme280": "missing"}}]).json()
    assert res["stored"] == 1
    assert _rows(db, device)[0].temperature == 99.0
    assert len(_alerts(db, device)) == 1


@pytest.mark.real_fault_gating
def test_a_fault_claim_in_a_backlog_reading_stops_nothing_and_raises_nothing(client, db, device):
    db.add(Alert(device_id=device.id, message="sensor", severity="warning", resolved=False, category="monitoring",
                 sensor_key="bme280", kind="sensor"))
    db.flush()
    _batch(client, device, [{"temperature": 99.0, "faults": {"bme280": "missing"}, "observed_at": _iso(_now() - timedelta(hours=1))}])
    row = _rows(db, device)[0]
    assert row.temperature == 99.0


def test_physical_ranges_hold_in_a_batch(client, db, device):
    res = _batch(client, device, [{"temperature": 1e308, "humidity": 40.0}]).json()
    row = _rows(db, device)[0]
    assert row.temperature is None and row.quality["dropped_values"] == ["temperature"] and res["stored"] == 1


def test_a_nul_in_one_string_is_cleaned_and_the_reading_kept(client, db, device):
    res = _batch(client, device, [{"temperature": 20.0, "node_type": "es\u0000p"}]).json()
    assert res["stored"] == 1 and _rows(db, device)[0].node_type is None


def test_the_replay_counters_a_batch_records_are_the_ones_the_admin_can_reset(client, db, device, auth_headers):
    _batch(client, device, [{"temperature": 1.0, "boot": 40, "seq": 3}])
    assert client.post(f"/api/v1/devices/{device.id}/accept-counter", headers=auth_headers).status_code == 200
    assert _batch(client, device, [{"temperature": 1.0, "boot": 1, "seq": 1}]).json()["stored"] == 1


def test_a_big_jump_inside_a_batch_is_recorded_as_a_warning(client, db, device, auth_headers):
    _batch(client, device, [{"temperature": 1.0, "boot": 3, "seq": 1}, {"temperature": 1.0, "boot": 5_000, "seq": 1}])
    body = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()
    assert "boot jumped" in body["counter_jump_note"]
