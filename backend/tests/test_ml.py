def test_retrain_requires_admin(client, db):
    # I create a real viewer row so get_current_user succeeds and the role guard
    # (403) is what terminates the request, not a missing-user 401.
    from passlib.context import CryptContext
    from app.models.user import User
    from app.routes.auth import create_access_token
    viewer = User(
        name="Viewer",
        email="viewer@test.com",
        password_hash=CryptContext(schemes=["bcrypt"], deprecated="auto").hash("Viewer1!"),
        role="viewer",
    )
    db.add(viewer)
    db.flush()
    token = create_access_token({"sub": str(viewer.id), "role": viewer.role})
    res = client.post("/api/v1/ml/retrain", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


def test_retrain_accepted_then_cooldown(client, auth_headers):
    import app.routes.ml as ml_module
    # I reset the cooldown so this test is independent of execution order.
    ml_module._last_retrain = None

    res = client.post("/api/v1/ml/retrain", headers=auth_headers)
    assert res.status_code == 202
    assert "started" in res.json()["detail"].lower()

    # Second call within 1 hour must be rejected with 429.
    res2 = client.post("/api/v1/ml/retrain", headers=auth_headers)
    assert res2.status_code == 429

    # Clean up so other tests are unaffected.
    ml_module._last_retrain = None


def test_score_without_model(client, auth_headers):
    # Without a trained model file, score_reading() returns 0.0 / False as a
    # safe pass-through so the system works before ML training is done.
    res = client.post("/api/v1/ml/score", json={
        "device_id": "00000000-0000-0000-0000-000000000000",
        "temperature": 22.5,
        "humidity": 50.0,
    }, headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["anomaly_score"] == 0.0
    assert body["is_anomaly"] is False


def test_score_response_schema(client, auth_headers):
    res = client.post("/api/v1/ml/score", json={
        "device_id": "00000000-0000-0000-0000-000000000000",
        "temperature": 99.9,
        "vibration_x": 50.0,
    }, headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["anomaly_score"], float)
    assert isinstance(body["is_anomaly"], bool)


def test_anomaly_history_empty(client, device, auth_headers):
    res = client.get(f"/api/v1/ml/anomalies/{device.id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []
