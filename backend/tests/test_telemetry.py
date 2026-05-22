def test_ingest_missing_api_key(client, device):
    # X-API-Key is a required header — omitting it returns 422 (validation error).
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


def test_get_telemetry_empty(client, device):
    res = client.get(f"/api/v1/telemetry/{device.id}")
    assert res.status_code == 200
    assert res.json() == []


def test_get_latest_not_found(client, device):
    res = client.get(f"/api/v1/telemetry/{device.id}/latest")
    assert res.status_code == 404


def test_get_latest_after_ingest(client, device):
    client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), "temperature": 30.0},
        headers={"X-API-Key": device.api_key},
    )
    res = client.get(f"/api/v1/telemetry/{device.id}/latest")
    assert res.status_code == 200
    assert res.json()["temperature"] == 30.0
