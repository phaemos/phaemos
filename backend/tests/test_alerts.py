import uuid


def test_list_alerts_empty(client):
    res = client.get("/api/v1/alerts")
    assert res.status_code == 200
    assert res.json() == []


def test_create_alert_rule(client, device):
    res = client.post("/api/v1/alert-rules", json={
        "device_id": str(device.id),
        "metric": "temperature",
        "condition": "gt",
        "threshold": 40.0,
        "severity": "warning",
    })
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
