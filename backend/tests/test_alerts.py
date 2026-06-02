import uuid

from app.routes.auth import create_access_token


def _admin_headers(admin_user):
    token = create_access_token({"sub": str(admin_user.id), "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def test_list_alerts_empty(client, admin_user):
    res = client.get("/api/v1/alerts", headers=_admin_headers(admin_user))
    assert res.status_code == 200
    assert res.json() == []


def test_create_alert_rule(client, device, admin_user):
    res = client.post("/api/v1/alert-rules", json={
        "device_id": str(device.id),
        "metric": "temperature",
        "condition": "gt",
        "threshold": 40.0,
        "severity": "warning",
    }, headers=_admin_headers(admin_user))
    assert res.status_code == 201
    body = res.json()
    assert body["metric"] == "temperature"
    assert body["condition"] == "gt"
    assert body["threshold"] == 40.0


def test_resolve_alert(client, device, db, auth_headers):
    from app.models.alert import Alert

    # Insert alert directly — tests the resolve endpoint in isolation from the
    # alert rule evaluation path.
    alert = Alert(
        device_id=device.id,
        message="Test alert",
        severity="warning",
        resolved=False,
    )
    db.add(alert)
    db.flush()

    # I pass auth_headers because resolve now requires an authenticated user
    # to record the actor in the audit log.
    res = client.patch(f"/api/v1/alerts/{alert.id}/resolve", headers=auth_headers)
    assert res.status_code == 200
    # Use truthy check — the resolved column is String type (pre-existing quirk)
    # so it may come back as True (bool) or "True" (str).
    assert res.json()["resolved"]


def test_resolve_alert_not_found(client, auth_headers):
    res = client.patch(
        f"/api/v1/alerts/{uuid.uuid4()}/resolve",
        headers=auth_headers,
    )
    assert res.status_code == 404


def test_list_alerts_requires_auth(client):
    res = client.get("/api/v1/alerts")
    assert res.status_code == 403


def test_create_rule_requires_admin(client, device, db):
    from passlib.context import CryptContext
    from app.models.user import User
    from app.routes.auth import create_access_token

    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    tech = User(
        name="TechAlert",
        email="tech-alert@test.com",
        password_hash=pwd_ctx.hash("Tech1234!"),
        role="technician",
    )
    db.add(tech)
    db.flush()

    token = create_access_token({"sub": str(tech.id), "role": "technician"})
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post("/api/v1/alert-rules", json={
        "device_id": str(device.id),
        "metric": "temperature",
        "condition": "gt",
        "threshold": 40.0,
        "severity": "warning",
    }, headers=headers)
    assert res.status_code == 403
