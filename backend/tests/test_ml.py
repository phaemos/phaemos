def test_retrain_requires_admin(client, db):
    # create a real viewer row so get_current_user succeeds and the role guard
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
    # reset the cooldown so this test is independent of execution order.
    ml_module._last_retrain = None

    res = client.post("/api/v1/ml/retrain", headers=auth_headers)
    assert res.status_code == 202
    assert "started" in res.json()["detail"].lower()

    # second call within 1 hour must be rejected with 429.
    res2 = client.post("/api/v1/ml/retrain", headers=auth_headers)
    assert res2.status_code == 429

    # clean up so other tests are unaffected.
    ml_module._last_retrain = None


def test_score_without_model(client, auth_headers):
    # without a trained model file, score_reading() returns 0.0 / False as a
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


def _healthy(rng, node, n):
    # two node types with different sensors, like an esp32 and a pico
    if node == "esp32":
        return [{"node_type": node, "temperature": rng.normal(24, 1), "vibration_x": rng.normal(0.2, 0.05),
                 "vibration_y": rng.normal(0.2, 0.05), "current_ma": rng.normal(300, 15)} for _ in range(n)]
    return [{"node_type": node, "temperature": rng.normal(21, 0.8), "humidity": rng.normal(45, 3),
             "light_level": rng.normal(300, 30)} for _ in range(n)]


def test_healthy_readings_are_rarely_flagged_and_faults_are_caught():
    import numpy as np
    from app.services import ml_service

    rng = np.random.default_rng(1)
    bundle, summary = ml_service.train(_healthy(rng, "esp32", 400) + _healthy(rng, "pico_w", 400))
    assert set(bundle) == {"default", "esp32", "pico_w"}
    assert "esp32 on 400 rows" in summary

    ml_service._model = bundle
    try:
        healthy = [ml_service.score_reading(r) for r in _healthy(np.random.default_rng(2), "esp32", 300)]
        flagged = sum(is_anomaly for _, is_anomaly in healthy) / len(healthy)
        assert flagged < 0.12
        assert np.median([score for score, _ in healthy]) < 0.3

        # a worn bearing: vibration ten times its normal level
        faulty = [{**r, "vibration_x": r["vibration_x"] * 10, "vibration_y": r["vibration_y"] * 10}
                  for r in _healthy(np.random.default_rng(3), "esp32", 100)]
        caught = sum(ml_service.score_reading(r)[1] for r in faulty) / len(faulty)
        assert caught > 0.95
    finally:
        ml_service._model = None


def test_a_single_model_saved_by_an_earlier_version_still_scores():
    import numpy as np
    from sklearn.ensemble import IsolationForest
    from app.services import ml_service

    X = np.random.default_rng(4).normal(size=(200, len(ml_service.FEATURE_COLS)))
    ml_service._model = IsolationForest(random_state=42).fit(X)
    try:
        score, _ = ml_service.score_reading(dict(zip(ml_service.FEATURE_COLS, X[0])))
        assert 0.0 <= score <= 1.0
    finally:
        ml_service._model = None
