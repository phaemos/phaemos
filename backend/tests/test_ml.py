import pytest


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


@pytest.fixture
def no_model(monkeypatch):
    # these two tests are about the route with no model, whether or not a trained file exists on this machine
    from app.services import ml_service
    monkeypatch.setattr(ml_service, "_model", None)
    monkeypatch.setattr(ml_service, "_load_model", lambda: None)


def test_score_without_model(client, auth_headers, no_model):
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


def test_score_response_schema(client, auth_headers, no_model):
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


def _token(db, role, name):
    from passlib.context import CryptContext
    from app.models.user import User
    from app.routes.auth import create_access_token
    user = User(name=name, email=f"{name}@test.com", role=role,
                password_hash=CryptContext(schemes=["bcrypt"], deprecated="auto").hash("Pass1!word"))
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'role': user.role})}"}


@pytest.mark.parametrize("role", ["viewer", "technician"])
def test_score_is_admin_only_as_the_docs_say(client, db, no_model, role):
    res = client.post("/api/v1/ml/score", json={"device_id": "x", "temperature": 20.0}, headers=_token(db, role, role))
    assert res.status_code == 403


def test_score_uses_the_machine_access_rule_for_a_machine_that_exists(client, db, device, auth_headers, no_model):
    res = client.post("/api/v1/ml/score", json={"device_id": str(device.id), "temperature": 20.0}, headers=auth_headers)
    assert res.status_code == 200


def test_status_reports_the_model_and_the_nightly_schedule(client, auth_headers, db):
    res = client.get("/api/v1/ml/status", headers=_token(db, "viewer", "viewer2"))
    assert res.status_code == 200
    body = res.json()
    assert {"state", "models", "last_retrain", "schedule"} <= set(body)
    assert body["schedule"]["nightly_utc"] == "03:30"


def test_the_cooldown_answer_has_its_own_code(client, auth_headers):
    import app.routes.ml as ml_module
    ml_module._last_retrain = None
    client.post("/api/v1/ml/retrain", headers=auth_headers)
    res = client.post("/api/v1/ml/retrain", headers=auth_headers)
    assert res.status_code == 429 and res.json()["code"] == "retrain_cooldown"
    ml_module._last_retrain = None


def test_the_anomaly_history_is_paged_and_counts_its_rows(client, device, auth_headers):
    res = client.get(f"/api/v1/ml/anomalies/{device.id}?limit=5&offset=0", headers=auth_headers)
    assert res.status_code == 200 and res.headers["X-Total-Count"] == "0"
    assert client.get(f"/api/v1/ml/anomalies/{device.id}?limit=1001", headers=auth_headers).status_code == 422


def test_the_status_lists_machines_and_the_cap(client, db):
    body = client.get("/api/v1/ml/status", headers=_token(db, "viewer", "viewer3")).json()
    assert body["max_machine_models"] == 24 and isinstance(body["machines"], list)


def test_a_person_can_confirm_a_machine_alert_as_a_fault(client, db, device, auth_headers):
    from app.models.alert import Alert
    alert = Alert(device_id=device.id, message="Anomaly detected", severity="warning", category="machine", kind="anomaly")
    db.add(alert)
    db.flush()
    res = client.post(f"/api/v1/ml/alerts/{alert.id}/verdict", json={"fault": True}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["fault_confirmed"] is True
    db.refresh(alert)
    assert alert.fault_confirmed is True
    res = client.post(f"/api/v1/ml/alerts/{alert.id}/verdict", json={"fault": False}, headers=auth_headers)
    assert res.json()["fault_confirmed"] is False


def test_a_verdict_is_audited_with_who_gave_it(client, db, device, auth_headers, admin_user):
    from sqlalchemy import text
    from app.models.alert import Alert
    alert = Alert(device_id=device.id, message="Anomaly detected", severity="warning", category="machine", kind="anomaly")
    db.add(alert)
    db.flush()
    client.post(f"/api/v1/ml/alerts/{alert.id}/verdict", json={"fault": True}, headers=auth_headers)
    row = db.execute(text("SELECT user_id, detail FROM audit_log WHERE action = 'alert_verdict' AND resource_id = :id"),
                     {"id": str(alert.id)}).one()
    assert row[0] == str(admin_user.id) and "a real fault" in row[1]


def test_a_viewer_cannot_give_a_verdict(client, db, device):
    from passlib.context import CryptContext
    from app.models.alert import Alert
    from app.models.user import User
    from app.routes.auth import create_access_token
    viewer = User(name="V", email="viewer2@test.com", role="viewer",
                  password_hash=CryptContext(schemes=["bcrypt"], deprecated="auto").hash("Viewer1!"))
    db.add(viewer)
    alert = Alert(device_id=device.id, message="Anomaly detected", severity="warning", category="machine", kind="anomaly")
    db.add(alert)
    db.flush()
    token = create_access_token({"sub": str(viewer.id), "role": viewer.role})
    res = client.post(f"/api/v1/ml/alerts/{alert.id}/verdict", json={"fault": True}, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code in (403, 404)
    db.refresh(alert)
    assert alert.fault_confirmed is None


def test_a_verdict_on_an_alert_that_is_not_a_machine_alert_is_404(client, db, device, auth_headers):
    from app.models.alert import Alert
    alert = Alert(device_id=device.id, message="silent", severity="warning", category="monitoring", kind="offline")
    db.add(alert)
    db.flush()
    assert client.post(f"/api/v1/ml/alerts/{alert.id}/verdict", json={"fault": True}, headers=auth_headers).status_code == 404


def test_an_admin_accepts_a_move_and_the_next_retrain_may_use_it(client, device, auth_headers, tmp_path, monkeypatch):
    from app.services import ml_service
    monkeypatch.setattr(ml_service, "MODEL_PATH", str(tmp_path / "model.pkl"))
    # without fresh proof it is refused and nothing is accepted
    refused = client.post(f"/api/v1/ml/machines/{device.id}/accept-move", json={}, headers=auth_headers)
    assert refused.status_code == 400 and ml_service.accepted_moves() == {}
    res = client.post(f"/api/v1/ml/machines/{device.id}/accept-move", json={"password": "Admin1234!"}, headers=auth_headers)
    assert res.status_code == 200 and "Retrain to apply it" in res.json()["detail"]
    assert str(device.id) in ml_service.accepted_moves()


def test_a_retrain_raises_one_notice_for_an_unmonitored_machine_and_resolves_it_later(db, device):
    from app.models.alert import Alert
    from app.tasks import model_retrain
    model_retrain.raise_notices({str(device.id): "its own model was refused"}, {}, [device.id], db=db)
    model_retrain.raise_notices({str(device.id): "its own model was refused"}, {}, [device.id], db=db)
    rows = db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "unmonitored").all()
    assert len(rows) == 1 and rows[0].category == "monitoring" and "its own model was refused" in rows[0].message
    assert rows[0].resolved is False
    model_retrain.raise_notices({}, {str(device.id): "a person must accept the move"}, [device.id], db=db)
    db.refresh(rows[0])
    assert rows[0].resolved is True
    move = db.query(Alert).filter(Alert.device_id == device.id, Alert.kind == "model_move").one()
    assert move.message.startswith("Anomaly model needs a person: a person must accept the move")
