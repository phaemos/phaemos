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
    # All v2 sensor fields must reach the DB - previously only 6 fields were
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
