import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from starlette.websockets import WebSocketDisconnect

from sqlalchemy import text

from app.main import app
from app.models.device import Device
from app.models.telemetry import Telemetry


def test_ingest_missing_api_key(client, device):
    # X-API-Key is a required header - omitting it returns 422 (validation error).
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), "temperature": 22.5},
    )
    assert res.status_code == 422


def test_ingest_invalid_api_key(client, device):
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), "temperature": 22.5},
        headers={"X-API-Key": "bad-key"},
    )
    assert res.status_code == 401


def test_ingest_success(client, device):
    res = client.post(
        "/api/v1/telemetry",
        json={
            "device_id": str(device.id),
            "temperature": 24.1,
            "humidity": 55.0,
            "vibration_x": 0.01,
            "vibration_y": -0.02,
            "vibration_z": 9.81,
            "light_level": 300.0,
        },
        headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["temperature"] == 24.1
    assert "anomaly_score" in body
    assert "is_anomaly" in body


def test_ingest_v2_sensors_stored(client, device, auth_headers):
    # all v2 sensor fields must reach the DB - previously only 6 fields were
    # forwarded into the reading dict and the rest were silently dropped.
    res = client.post(
        "/api/v1/telemetry",
        json={
            "device_id": str(device.id),
            "gas_level": 412.0,
            "shaft_rpm": 1500.0,
            "ir_temperature": 38.5,
            "moisture_level": 0.12,
            "sound_level": 65.0,
        },
        headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["gas_level"] == 412.0
    assert body["shaft_rpm"] == 1500.0
    assert body["ir_temperature"] == 38.5
    assert body["moisture_level"] == 0.12
    assert body["sound_level"] == 65.0


def test_get_telemetry_empty(client, device, auth_headers):
    # GET /telemetry now requires a Bearer token - previously unauthenticated.
    res = client.get(f"/api/v1/telemetry/{device.id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_get_latest_not_found(client, device, auth_headers):
    res = client.get(f"/api/v1/telemetry/{device.id}/latest", headers=auth_headers)
    assert res.status_code == 404


def test_get_latest_after_ingest(client, device, auth_headers):
    client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), "temperature": 30.0},
        headers={"X-API-Key": device.api_key},
    )
    res = client.get(f"/api/v1/telemetry/{device.id}/latest", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["temperature"] == 30.0


# ── WebSocket path ────────────────────────────────────────────────────────────

def test_telemetry_websocket_lives_outside_the_versioned_prefix():
    # the dashboard builds this URL in frontend/lib/wsUrl.ts, so the two must agree.
    path = app.url_path_for("telemetry_ws", device_id="abc")
    assert path == "/ws/telemetry/abc"


def test_telemetry_websocket_answers_at_its_path(client, device, monkeypatch):
    # no token in the URL and no first frame: refused with 1008, which only the telemetry route
    # sends, so this proves the route is served at /ws/telemetry/{device_id}. The wait for the
    # first frame is shortened so the test does not sit through it.
    monkeypatch.setattr("app.routes.ws.FIRST_FRAME_SECONDS", 0.2)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/telemetry/{device.id}") as ws:
            ws.receive_text()
    assert exc.value.code == 1008


# ── bucketed history ──────────────────────────────────────────────────────────

# a fixed, past, five-minute-aligned instant so every bucket edge in these tests is predictable
T0 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def _row(db, device, offset_s, **fields):
    # written straight to the table because ingest stamps recorded_at with the current time
    db.add(Telemetry(device_id=device.id, recorded_at=T0 + timedelta(seconds=offset_s), **fields))


def _get_buckets(client, device, headers, bucket, **extra):
    params = {"bucket": bucket, "from_ts": T0.isoformat(), "to_ts": (T0 + timedelta(minutes=10)).isoformat(), **extra}
    return client.get(f"/api/v1/telemetry/{device.id}", params=params, headers=headers)


def test_bucket_averages_a_known_set(client, db, device, auth_headers):
    # two readings share the 12:00 minute and one sits alone in 12:02
    _row(db, device, 0, temperature=20.0, humidity=40.0)
    _row(db, device, 30, temperature=30.0, humidity=60.0)
    _row(db, device, 130, temperature=10.0)
    db.flush()

    res = _get_buckets(client, device, auth_headers, 60)
    assert res.status_code == 200
    body = res.json()
    # newest bucket first, like the raw route
    assert [b["recorded_at"][:16] for b in body] == ["2026-01-05T12:02", "2026-01-05T12:00"]
    late, early = body
    assert early["temperature"] == pytest.approx(25.0)
    assert early["humidity"] == pytest.approx(50.0)
    assert early["reading_count"] == 2
    assert late["temperature"] == pytest.approx(10.0)
    assert late["reading_count"] == 1
    # a column with no readings in the bucket stays null rather than becoming zero
    assert late["humidity"] is None
    assert late["device_id"] == str(device.id)
    assert "id" not in early


def test_bucket_flags_are_ored(client, db, device, auth_headers):
    _row(db, device, 0, gas_alert=False, water_detected=False, is_anomaly=False)
    _row(db, device, 10, gas_alert=True, water_detected=False, is_anomaly=False)
    _row(db, device, 20, gas_alert=False, water_detected=False, is_anomaly=True)
    db.flush()

    bucket = _get_buckets(client, device, auth_headers, 60).json()[0]
    assert bucket["gas_alert"] is True
    assert bucket["is_anomaly"] is True
    assert bucket["water_detected"] is False


def test_bucket_anomaly_score_is_the_maximum(client, db, device, auth_headers):
    # a mean of 0.4 would hide the spike this chart exists to show
    for offset, score in ((0, 0.1), (10, 0.9), (20, 0.2)):
        _row(db, device, offset, anomaly_score=score, vib_magnitude=score * 10, fft_peak_hz=100 + offset)
    db.flush()

    bucket = _get_buckets(client, device, auth_headers, 60).json()[0]
    assert bucket["anomaly_score"] == pytest.approx(0.9)
    assert bucket["vib_magnitude"] == pytest.approx(9.0)
    # the frequency comes from the strongest vibration (magnitude 9 at offset 10), not the highest frequency
    assert bucket["fft_peak_hz"] == pytest.approx(110.0)


def test_empty_buckets_are_absent(client, db, device, auth_headers):
    # readings in the first and fourth minutes: the two between them must not be invented
    _row(db, device, 0, temperature=1.0)
    _row(db, device, 190, temperature=2.0)
    db.flush()

    body = _get_buckets(client, device, auth_headers, 60).json()
    assert len(body) == 2


def test_bucket_edges_follow_the_clock_not_from_ts(client, db, device, auth_headers):
    # from_ts is mid-bucket, yet the 12:00 reading still lands in the 12:00 bucket
    _row(db, device, 90, temperature=5.0)
    db.flush()
    res = client.get(
        f"/api/v1/telemetry/{device.id}",
        params={
            "bucket": 300,
            "from_ts": (T0 + timedelta(seconds=45)).isoformat(),
            "to_ts": (T0 + timedelta(minutes=10)).isoformat(),
        },
        headers=auth_headers,
    )
    assert res.json()[0]["recorded_at"][:16] == "2026-01-05T12:00"


def test_bucket_ignores_limit_and_offset(client, db, device, auth_headers):
    for minute in range(5):
        _row(db, device, minute * 60, temperature=float(minute))
    db.flush()
    body = _get_buckets(client, device, auth_headers, 60, limit=1, offset=1).json()
    assert len(body) == 5


def test_bucket_still_filters_by_node_type(client, db, device, auth_headers):
    _row(db, device, 0, temperature=10.0, node_type="esp32")
    _row(db, device, 10, temperature=50.0, node_type="stm32")
    db.flush()

    body = _get_buckets(client, device, auth_headers, 60, node_type="esp32").json()
    assert len(body) == 1
    assert body[0]["temperature"] == pytest.approx(10.0)
    assert body[0]["reading_count"] == 1


def test_bucket_only_counts_the_requested_device(client, db, device, auth_headers):
    other = Device(name="Other", location="Lab", type="esp32", api_key="other-key")
    db.add(other)
    db.flush()
    _row(db, device, 0, temperature=10.0)
    _row(db, other, 5, temperature=90.0)
    db.flush()

    body = _get_buckets(client, device, auth_headers, 60).json()
    assert body[0]["temperature"] == pytest.approx(10.0)
    assert body[0]["reading_count"] == 1


@pytest.mark.parametrize("bucket", [0, 9, -5, 86_401, "abc"])
def test_bucket_bounds_return_422(client, device, auth_headers, bucket):
    res = _get_buckets(client, device, auth_headers, bucket)
    assert res.status_code == 422


def test_bucket_bounds_are_inclusive(client, device, auth_headers):
    assert _get_buckets(client, device, auth_headers, 10).status_code == 200
    assert _get_buckets(client, device, auth_headers, 86_400).status_code == 200


def test_bucket_needs_from_ts(client, device, auth_headers):
    res = client.get(f"/api/v1/telemetry/{device.id}", params={"bucket": 60}, headers=auth_headers)
    assert res.status_code == 422
    assert "from" in res.json()["detail"]


def test_bucket_count_cap_returns_422_with_a_clear_message(client, device, auth_headers):
    # a day of 10 second buckets is 8,641 buckets, well past the 1,000 cap
    res = client.get(
        f"/api/v1/telemetry/{device.id}",
        params={"bucket": 10, "from_ts": T0.isoformat(), "to_ts": (T0 + timedelta(days=1)).isoformat()},
        headers=auth_headers,
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "at most 1000" in detail
    assert "larger bucket" in detail


def test_bucket_count_cap_allows_exactly_the_limit_window(client, device, auth_headers):
    # 999 whole buckets plus one for epoch alignment is 1,000: allowed
    res = client.get(
        f"/api/v1/telemetry/{device.id}",
        params={"bucket": 60, "from_ts": T0.isoformat(), "to_ts": (T0 + timedelta(seconds=999 * 60)).isoformat()},
        headers=auth_headers,
    )
    assert res.status_code == 200


def test_bucket_requires_auth(client, device):
    res = client.get(f"/api/v1/telemetry/{device.id}", params={"bucket": 60, "from_ts": T0.isoformat()})
    assert res.status_code == 401


def test_unbucketed_route_is_unchanged(client, db, device, auth_headers):
    _row(db, device, 0, temperature=20.0)
    _row(db, device, 30, temperature=30.0)
    db.flush()

    res = client.get(f"/api/v1/telemetry/{device.id}", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    # raw rows, newest first, with the stored id and without any bucket field
    assert [r["temperature"] for r in body] == [30.0, 20.0]
    assert "id" in body[0]
    assert "reading_count" not in body[0]
    assert "node_type" in body[0]
    # limit still applies without a bucket
    one = client.get(f"/api/v1/telemetry/{device.id}", params={"limit": 1}, headers=auth_headers).json()
    assert len(one) == 1


def test_unbucketed_route_still_filters_by_node_type(client, db, device, auth_headers):
    _row(db, device, 0, temperature=10.0, node_type="esp32")
    _row(db, device, 10, temperature=50.0, node_type="stm32")
    db.flush()

    body = client.get(f"/api/v1/telemetry/{device.id}", params={"node_type": "stm32"}, headers=auth_headers).json()
    assert [r["temperature"] for r in body] == [50.0]


# ── circular, peak and strongest-vibration aggregates ─────────────────────────

def _angle_gap(a, b):
    # distance on a 360 degree circle, so 359.9999 and 0.0001 are both close to 0
    d = abs(a - b) % 360
    return min(d, 360 - d)


def test_shaft_angle_is_a_circular_mean(client, db, device, auth_headers):
    # 359 and 1 are two degrees apart across the wrap: a plain mean would say 180
    _row(db, device, 0, shaft_angle=359.0)
    _row(db, device, 10, shaft_angle=1.0)
    # 350 and 20 average to 5
    _row(db, device, 70, shaft_angle=350.0)
    _row(db, device, 80, shaft_angle=20.0)
    _row(db, device, 130, shaft_angle=10.0)
    _row(db, device, 140, shaft_angle=20.0)
    db.flush()

    by_minute = {b["recorded_at"][11:16]: b["shaft_angle"] for b in _get_buckets(client, device, auth_headers, 60).json()}
    assert _angle_gap(by_minute["12:00"], 0.0) < 0.001
    assert by_minute["12:01"] == pytest.approx(5.0)
    assert by_minute["12:02"] == pytest.approx(15.0)
    assert all(0 <= v <= 360 for v in by_minute.values())


def test_signed_axes_keep_the_mean_and_add_a_peak(client, db, device, auth_headers):
    # the mean is the static offset: -1. The vibration is the swing to 3
    _row(db, device, 0, vibration_x=-3.0, gyro_z=2.0)
    _row(db, device, 10, vibration_x=1.0, gyro_z=-8.0)
    db.flush()

    bucket = _get_buckets(client, device, auth_headers, 60).json()[0]
    assert bucket["vibration_x"] == pytest.approx(-1.0)
    assert bucket["vibration_x_peak"] == pytest.approx(3.0)
    assert bucket["gyro_z"] == pytest.approx(-3.0)
    assert bucket["gyro_z_peak"] == pytest.approx(8.0)
    assert bucket["vibration_y_peak"] is None


def test_fft_peak_comes_from_the_strongest_vibration_and_skips_gaps(client, db, device, auth_headers):
    # the strongest reading has no frequency, so the next strongest one that has a frequency is used
    _row(db, device, 0, vib_magnitude=10.0)
    _row(db, device, 10, vib_magnitude=2.0, fft_peak_hz=80.0)
    _row(db, device, 20, vib_magnitude=1.0, fft_peak_hz=900.0)
    db.flush()

    bucket = _get_buckets(client, device, auth_headers, 60).json()[0]
    assert bucket["fft_peak_hz"] == pytest.approx(80.0)


def test_bucket_flags_all_null(client, db, device, auth_headers):
    _row(db, device, 0, temperature=1.0)
    db.flush()
    db.execute(text("UPDATE telemetry SET gas_alert = NULL, water_detected = NULL, is_anomaly = NULL"))

    bucket = _get_buckets(client, device, auth_headers, 60).json()[0]
    assert bucket["gas_alert"] is None
    assert bucket["water_detected"] is None
    # the schema promises a boolean, so a bucket with no answer reads false
    assert bucket["is_anomaly"] is False


def test_bucket_from_ts_with_a_non_utc_offset(client, db, device, auth_headers):
    # 17:00 at +05:00 is 12:00 UTC. Misread as UTC it would start five hours late and miss both rows
    _row(db, device, -1, temperature=99.0)
    _row(db, device, 0, temperature=10.0)
    db.flush()
    start = T0.astimezone(timezone(timedelta(hours=5)))
    assert start.isoformat().endswith("+05:00")

    res = client.get(
        f"/api/v1/telemetry/{device.id}",
        params={"bucket": 60, "from_ts": start.isoformat(), "to_ts": (start + timedelta(minutes=10)).isoformat()},
        headers=auth_headers,
    )
    body = res.json()
    assert len(body) == 1
    assert body[0]["temperature"] == pytest.approx(10.0)


def test_bucket_from_ts_without_a_zone_is_read_as_utc(client, db, device, auth_headers):
    _row(db, device, 0, temperature=10.0)
    db.flush()
    res = client.get(
        f"/api/v1/telemetry/{device.id}",
        params={"bucket": 60, "from_ts": "2026-01-05T12:00:00", "to_ts": "2026-01-05T12:10:00"},
        headers=auth_headers,
    )
    assert len(res.json()) == 1


def test_first_bucket_can_start_before_from_ts(client, db, device, auth_headers):
    _row(db, device, 90, temperature=5.0)
    db.flush()
    res = client.get(
        f"/api/v1/telemetry/{device.id}",
        params={"bucket": 300, "from_ts": (T0 + timedelta(seconds=45)).isoformat(), "to_ts": (T0 + timedelta(minutes=10)).isoformat()},
        headers=auth_headers,
    )
    first = datetime.fromisoformat(res.json()[0]["recorded_at"].replace("Z", "+00:00"))
    assert first < T0 + timedelta(seconds=45)


# ── cost and abuse limits ─────────────────────────────────────────────────────

def test_bucket_window_is_capped_at_31_days(client, device, auth_headers):
    too_long = client.get(
        f"/api/v1/telemetry/{device.id}",
        params={"bucket": 3600, "from_ts": T0.isoformat(), "to_ts": (T0 + timedelta(days=32)).isoformat()},
        headers=auth_headers,
    )
    assert too_long.status_code == 422
    assert "31 days" in too_long.json()["detail"]
    allowed = client.get(
        f"/api/v1/telemetry/{device.id}",
        params={"bucket": 3600, "from_ts": T0.isoformat(), "to_ts": (T0 + timedelta(days=31)).isoformat()},
        headers=auth_headers,
    )
    assert allowed.status_code == 200


def test_bucket_window_of_1000_bucket_widths_is_refused(client, device, auth_headers):
    # 999 widths can touch 1000 buckets (allowed). 1000 widths can touch 1001
    res = client.get(
        f"/api/v1/telemetry/{device.id}",
        params={"bucket": 60, "from_ts": T0.isoformat(), "to_ts": (T0 + timedelta(seconds=1000 * 60)).isoformat()},
        headers=auth_headers,
    )
    assert res.status_code == 422
    assert "up to 1001" in res.json()["detail"]


def test_bucket_query_timeout_answers_503(client, device, auth_headers, monkeypatch):
    from app.services.telemetry_buckets import BucketQueryTimeout

    def slow(*args, **kwargs):
        raise BucketQueryTimeout

    monkeypatch.setattr("app.routes.telemetry.bucketed_telemetry", slow)
    res = _get_buckets(client, device, auth_headers, 60)
    assert res.status_code == 503
    assert "too long" in res.json()["detail"]


def test_history_limit_has_an_upper_bound(client, device, auth_headers):
    ok = client.get(f"/api/v1/telemetry/{device.id}", params={"limit": 5000}, headers=auth_headers)
    assert ok.status_code == 200
    res = client.get(f"/api/v1/telemetry/{device.id}", params={"limit": 5001}, headers=auth_headers)
    assert res.status_code == 422
    # the bound is now checked by the query validator, whose detail is a list of errors
    assert "5000" in str(res.json()["detail"])


def test_history_route_is_rate_limited(client, device, auth_headers):
    # 404 is the cheapest answer: the limit counts requests, not what they return
    url = f"/api/v1/telemetry/{device.id}/latest"
    for _ in range(600):
        assert client.get(url, headers=auth_headers).status_code == 404
    assert client.get(url, headers=auth_headers).status_code == 429


# ── export ────────────────────────────────────────────────────────────────────

def _export(client, device, headers, **extra):
    # the rows sit at a fixed time in the past, so the window is closed at both ends to stay inside the export cap
    params = {
        "device_id": str(device.id),
        "from_ts": (T0 - timedelta(minutes=1)).isoformat(),
        "to_ts": (T0 + timedelta(hours=1)).isoformat(),
        **extra,
    }
    return client.get("/api/v1/telemetry/export", params=params, headers=headers)


def _old_export_body(db, device):
    # the body the route produced before it streamed: every row in memory, oldest first
    rows = db.query(Telemetry).filter(Telemetry.device_id == device.id).order_by(Telemetry.recorded_at.asc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(rows[0].__table__.columns.keys())
    for row in rows:
        writer.writerow([getattr(row, c.name) for c in row.__table__.columns])
    return buf.getvalue()


def test_export_streamed_body_matches_the_old_body(client, db, device, auth_headers):
    for i in range(5):
        _row(db, device, i * 5, temperature=20.0 + i, node_type="esp32", gas_alert=bool(i % 2))
    db.flush()

    res = _export(client, device, auth_headers)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert res.headers["content-disposition"] == f"attachment; filename=telemetry_{device.id}.csv"
    assert res.text == _old_export_body(db, device)


def test_export_across_several_batches_is_identical(client, db, device, auth_headers, monkeypatch):
    for i in range(5):
        _row(db, device, i * 5, temperature=20.0 + i)
    db.flush()
    monkeypatch.setattr("app.routes.telemetry.EXPORT_BATCH", 2)

    res = _export(client, device, auth_headers)
    assert res.text == _old_export_body(db, device)
    assert len(list(csv.reader(io.StringIO(res.text)))) == 6


def test_export_with_no_rows_sends_the_short_header(client, device, auth_headers):
    res = _export(client, device, auth_headers)
    assert res.status_code == 200
    assert res.text == "id,device_id,recorded_at\r\n"


def test_export_span_is_capped_at_31_days(client, device, auth_headers):
    res = _export(client, device, auth_headers, to_ts=(T0 + timedelta(days=32)).isoformat())
    assert res.status_code == 422
    assert "shorter range" in res.json()["detail"]
    ok = _export(client, device, auth_headers, to_ts=(T0 + timedelta(days=30)).isoformat())
    assert ok.status_code == 200


def test_export_needs_from_ts(client, device, auth_headers):
    res = client.get("/api/v1/telemetry/export", params={"device_id": str(device.id)}, headers=auth_headers)
    assert res.status_code == 422


def test_export_requires_auth(client, device):
    res = client.get("/api/v1/telemetry/export", params={"device_id": str(device.id), "from_ts": T0.isoformat()})
    assert res.status_code == 401


# ── ingest refuses non-finite numbers ─────────────────────────────────────────

@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_ingest_refuses_non_finite_numbers(client, db, device, value):
    body = '{"device_id": "%s", "temperature": 21.0, "vib_magnitude": %s}' % (device.id, value)
    res = client.post(
        "/api/v1/telemetry",
        content=body,
        headers={"X-API-Key": device.api_key, "Content-Type": "application/json"},
    )
    assert res.status_code == 422
    assert db.query(Telemetry).filter(Telemetry.device_id == device.id).count() == 0


def test_ingest_still_accepts_null_and_omitted_readings(client, device):
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), "temperature": 21.0, "humidity": None},
        headers={"X-API-Key": device.api_key},
    )
    assert res.status_code == 201
