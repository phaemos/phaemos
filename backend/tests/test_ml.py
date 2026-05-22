def test_score_without_model(client):
    # Without a trained model file, score_reading() returns 0.0 / False as a
    # safe pass-through so the system works before ML training is done.
    res = client.post("/api/v1/ml/score", json={
        "device_id": "00000000-0000-0000-0000-000000000000",
        "temperature": 22.5,
        "humidity": 50.0,
    })
    assert res.status_code == 200
    body = res.json()
    assert body["anomaly_score"] == 0.0
    assert body["is_anomaly"] is False


def test_score_response_schema(client):
    res = client.post("/api/v1/ml/score", json={
        "device_id": "00000000-0000-0000-0000-000000000000",
        "temperature": 99.9,
        "vibration_x": 50.0,
    })
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["anomaly_score"], float)
    assert isinstance(body["is_anomaly"], bool)


def test_anomaly_history_empty(client, device):
    res = client.get(f"/api/v1/ml/anomalies/{device.id}")
    assert res.status_code == 200
    assert res.json() == []
