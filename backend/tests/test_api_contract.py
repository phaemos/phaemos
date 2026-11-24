"""
The API conventions on the routes of alerts, rules, tickets, maintenance windows, webhooks, devices and readings: filters, paging,
keyset cursors, item reads, partial updates, idempotent creates, the signed json webhook and the aliases kept for one release.
"""

import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models.alert import Alert, AlertRule
from app.models.device import Device
from app.models.maintenance import MaintenanceWindow
from app.models.telemetry import Telemetry
from app.models.ticket import Ticket
from app.models.user import User
from app.models.webhook import Webhook
from app.routes.auth import create_access_token, hash_password
from app.services import alert_service, cooldown, idempotency, ingest_limit, webhook_service

PASSWORD = "Passw0rd!x"
V1 = "/api/v1"


def _user(db, role, email):
    user = User(name=email.split("@")[0], email=email, password_hash=hash_password(PASSWORD), role=role)
    db.add(user)
    db.flush()
    return user


def _h(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'role': user.role})}"}


@pytest.fixture
def admin(db):
    return _user(db, "admin", "contract-admin@example.com")


@pytest.fixture
def tech(db):
    return _user(db, "technician", "contract-tech@example.com")


@pytest.fixture(autouse=True)
def _clean_idempotency():
    idempotency.reset()
    yield
    idempotency.reset()


def _alert(db, device, minutes_ago, **kw):
    a = Alert(
        device_id=device.id, message=f"m{minutes_ago}", severity=kw.pop("severity", "warning"), resolved=kw.pop("resolved", False),
        triggered_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago), category=kw.pop("category", "machine"),
        kind=kw.pop("kind", None), **kw,
    )
    db.add(a)
    db.flush()
    return a


# -- alerts -----------------------------------------------------------------------------------

def test_alerts_filter_by_device_severity_kind_and_time(client, db, admin, device):
    other = Device(name="Other", api_key=secrets.token_urlsafe(32))
    db.add(other)
    db.flush()
    _alert(db, device, 5, severity="critical", kind="rule")
    _alert(db, device, 10, severity="warning", kind="anomaly")
    _alert(db, other, 15, severity="critical", kind="rule")
    got = lambda **q: client.get(f"{V1}/alerts", params=q, headers=_h(admin)).json()  # noqa: E731
    assert len(got(device_id=str(device.id))) == 2
    assert len(got(severity="critical")) == 2
    assert [a["kind"] for a in got(device_id=str(device.id), kind="anomaly")] == ["anomaly"]
    since = (datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat()
    assert len(got(**{"from": since})) == 2
    # an unknown value is a 422 and not an empty list
    for bad in ({"severity": "huge"}, {"kind": "nope"}):
        res = client.get(f"{V1}/alerts", params=bad, headers=_h(admin))
        assert res.status_code == 422 and res.json()["code"] == "validation_failed"


def test_a_technician_cannot_filter_their_way_to_another_machine(client, db, tech, device):
    device.owner_id = _user(db, "technician", "someone-else@example.com").id
    db.flush()
    res = client.get(f"{V1}/alerts", params={"device_id": str(device.id)}, headers=_h(tech))
    assert res.status_code == 404 and res.json()["code"] == "device_not_found"


def test_alerts_walk_by_keyset_without_a_repeat_or_a_gap(client, db, admin, device):
    now = datetime.now(timezone.utc)
    for i in range(7):
        # two alerts share every instant, so only the id breaks the tie
        db.add(Alert(device_id=device.id, message=f"a{i}", severity="warning", resolved=False, category="machine",
                     triggered_at=now - timedelta(minutes=i // 2)))
    db.flush()
    seen, cursor = [], None
    for _ in range(10):
        params = {"limit": 3, **({"before": cursor} if cursor else {})}
        res = client.get(f"{V1}/alerts", params=params, headers=_h(admin))
        rows = res.json()
        seen += [r["id"] for r in rows]
        if len(rows) < 3:
            break
        assert "X-Total-Count" not in res.headers if cursor else res.headers["X-Total-Count"] == "7"
        cursor = res.headers["X-Next-Before"]
    assert len(seen) == 7 and len(set(seen)) == 7


def test_one_alert_by_id_and_the_old_device_path_says_it_was_removed(client, db, admin, device):
    alert = _alert(db, device, 1)
    assert client.get(f"{V1}/alerts/{alert.id}", headers=_h(admin)).json()["id"] == str(alert.id)
    gone = client.get(f"{V1}/alerts/{device.id}", headers=_h(admin))
    assert gone.status_code == 410 and gone.json()["code"] == "endpoint_removed" and "alerts?device_id" in gone.json()["detail"]
    missing = client.get(f"{V1}/alerts/{secrets.token_hex(0) or '00000000-0000-4000-8000-000000000000'}", headers=_h(admin))
    assert missing.status_code == 404 and missing.json()["code"] == "alert_not_found"


def test_resolve_is_a_post_and_the_patch_alias_says_it_is_deprecated(client, db, admin, device):
    a, b = _alert(db, device, 1), _alert(db, device, 2)
    assert client.post(f"{V1}/alerts/{a.id}/resolve", headers=_h(admin)).json()["resolved"] is True
    res = client.patch(f"{V1}/alerts/{b.id}/resolve", headers=_h(admin))
    assert res.status_code == 200 and res.headers["Deprecation"] == "true" and "Sunset" in res.headers


# -- alert rules ------------------------------------------------------------------------------

def _rule(db, device, **kw):
    r = AlertRule(device_id=device.id, metric="temperature", condition="gt", threshold=50.0, severity="warning", for_seconds=30, **kw)
    db.add(r)
    db.flush()
    return r


def test_a_rule_is_patched_and_a_null_clears_only_what_may_be_cleared(client, db, admin, device):
    rule = _rule(db, device)
    ok = client.patch(f"{V1}/alert-rules/{rule.id}", json={"threshold": 60.0, "for_seconds": None}, headers=_h(admin))
    assert ok.status_code == 200 and ok.json()["threshold"] == 60.0 and ok.json()["for_seconds"] is None
    bad = client.patch(f"{V1}/alert-rules/{rule.id}", json={"metric": None}, headers=_h(admin))
    assert bad.status_code == 422 and bad.json()["code"] == "validation_failed"
    put = client.put(f"{V1}/alert-rules/{rule.id}", json={"severity": "critical"}, headers=_h(admin))
    assert put.status_code == 200 and put.headers["Deprecation"] == "true"


def test_a_rule_has_an_item_read_and_a_paged_list(client, db, admin, tech, device):
    rule = _rule(db, device)
    assert client.get(f"{V1}/alert-rules/{rule.id}", headers=_h(admin)).json()["id"] == str(rule.id)
    res = client.get(f"{V1}/alert-rules", params={"device_id": str(device.id), "limit": 1}, headers=_h(admin))
    assert res.headers["X-Total-Count"] == "1"
    assert client.get(f"{V1}/alert-rules", params={"metric": "nonsense"}, headers=_h(admin)).status_code == 422
    device.owner_id = _user(db, "technician", "rule-owner@example.com").id
    db.flush()
    assert client.get(f"{V1}/alert-rules/{rule.id}", headers=_h(tech)).json()["code"] == "rule_not_found"


# -- tickets ----------------------------------------------------------------------------------

def test_tickets_filter_by_machine_number_and_a_fixed_status(client, db, admin, device):
    other = Device(name="Other", api_key=secrets.token_urlsafe(32))
    db.add(other)
    db.flush()
    mine = Ticket(device_id=device.id, title="mine", status="open", priority="low", created_by=admin.id)
    theirs = Ticket(device_id=other.id, title="theirs", status="closed", priority="low", created_by=admin.id)
    db.add_all([mine, theirs])
    db.flush()
    db.refresh(mine)
    got = lambda **q: client.get(f"{V1}/tickets", params=q, headers=_h(admin))  # noqa: E731
    assert [t["title"] for t in got(device_id=str(device.id)).json()] == ["mine"]
    assert [t["title"] for t in got(ticket_number=mine.ticket_number).json()] == ["mine"]
    assert got(status="bogus").status_code == 422


def test_a_ticket_patch_clears_the_assignee_and_refuses_other_nulls(client, db, admin, device):
    t = Ticket(device_id=device.id, title="t", status="open", priority="low", created_by=admin.id, assigned_to=admin.id)
    db.add(t)
    db.flush()
    assert client.patch(f"{V1}/tickets/{t.id}", json={"assigned_to": None}, headers=_h(admin)).json()["assigned_to"] is None
    bad = client.patch(f"{V1}/tickets/{t.id}", json={"title": None}, headers=_h(admin))
    assert bad.status_code == 422


# -- maintenance windows ----------------------------------------------------------------------

def _window(client, admin, **kw):
    start = datetime.now(timezone.utc)
    body = {"label": "w", "start_at": start.isoformat(), "end_at": (start + timedelta(hours=2)).isoformat(), **kw}
    return client.post(f"{V1}/maintenance-windows", json=body, headers=_h(admin))


def test_a_window_is_created_with_its_id_and_ended_with_end_at_alone(client, db, admin, device):
    made = _window(client, admin, device_id=str(device.id))
    assert made.status_code == 201 and made.json()["id"]
    wid = made.json()["id"]
    now = datetime.now(timezone.utc)
    res = client.patch(f"{V1}/maintenance-windows/{wid}", json={"end_at": (now + timedelta(seconds=1)).isoformat()}, headers=_h(admin))
    assert res.status_code == 200 and res.json()["label"] == "w"
    assert client.get(f"{V1}/maintenance-windows/{wid}", headers=_h(admin)).json()["id"] == wid


def test_a_window_can_be_made_fleet_wide_with_null_and_bad_values_answer_422_or_404(client, db, admin, device):
    wid = _window(client, admin, device_id=str(device.id)).json()["id"]
    assert client.patch(f"{V1}/maintenance-windows/{wid}", json={"device_id": None}, headers=_h(admin)).json()["device_id"] is None
    assert client.patch(f"{V1}/maintenance-windows/{wid}", json={"label": None}, headers=_h(admin)).status_code == 422
    early = client.patch(f"{V1}/maintenance-windows/{wid}", json={"end_at": "2000-01-01T00:00:00Z"}, headers=_h(admin))
    assert early.status_code == 422 and early.json()["code"] == "invalid_range"
    unknown = _window(client, admin, device_id="00000000-0000-4000-8000-000000000001")
    assert unknown.status_code == 404 and unknown.json()["code"] == "device_not_found"


def test_windows_list_filters_and_pages(client, db, admin, device):
    _window(client, admin, device_id=str(device.id))
    _window(client, admin)
    res = client.get(f"{V1}/maintenance-windows", params={"device_id": str(device.id), "active": "true"}, headers=_h(admin))
    assert len(res.json()) == 1 and res.headers["X-Total-Count"] == "1"


# -- devices ----------------------------------------------------------------------------------

def test_devices_find_by_exact_name_and_by_contains(client, db, admin):
    for name in ("Pump 1", "Old pump", "Fan"):
        db.add(Device(name=name, api_key=secrets.token_urlsafe(32)))
    db.flush()
    names = lambda **q: sorted(d["name"] for d in client.get(f"{V1}/devices", params=q, headers=_h(admin)).json())  # noqa: E731
    assert names(name="pump 1") == ["Pump 1"]
    assert names(search="pump") == ["Old pump", "Pump 1"]
    assert names(search="%") == []
    assert names(status="bogus" if False else "online") == []
    assert client.get(f"{V1}/devices", params={"status": "decommissioned"}, headers=_h(admin)).status_code == 422


def test_a_device_patch_cannot_write_status_and_clears_only_what_may_be_cleared(client, db, admin, device):
    res = client.patch(f"{V1}/devices/{device.id}", json={"status": "decommissioned", "location": None}, headers=_h(admin))
    assert res.status_code == 200 and res.json()["status"] != "decommissioned" and res.json()["location"] is None
    assert client.patch(f"{V1}/devices/{device.id}", json={"name": None}, headers=_h(admin)).status_code == 422


# -- idempotency ------------------------------------------------------------------------------

def test_a_repeated_create_with_the_same_key_makes_one_machine_and_returns_the_same_key(client, db, admin):
    body = {"name": "Idem Press", "location": "Hall", "type": "esp32"}
    headers = {**_h(admin), "Idempotency-Key": "device-create-0001"}
    first = client.post(f"{V1}/devices", json=body, headers=headers)
    again = client.post(f"{V1}/devices", json=body, headers=headers)
    assert first.status_code == again.status_code == 201
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["id"] == first.json()["id"] and again.json()["api_key"] == first.json()["api_key"]
    assert db.query(Device).filter(Device.name == "Idem Press").count() == 1


def test_the_same_key_with_another_body_is_refused_and_another_account_does_not_share_it(client, db, admin, tech):
    headers = {**_h(admin), "Idempotency-Key": "device-create-0002"}
    client.post(f"{V1}/devices", json={"name": "A1", "type": "esp32"}, headers=headers)
    clash = client.post(f"{V1}/devices", json={"name": "A2", "type": "esp32"}, headers=headers)
    assert clash.status_code == 422 and clash.json()["code"] == "idempotency_key_reused"
    # the key is per account: a technician's create with it is theirs and (as a technician) refused by the route, not replayed
    other = client.post(f"{V1}/devices", json={"name": "A1", "type": "esp32"}, headers={**_h(tech), "Idempotency-Key": "device-create-0002"})
    assert other.status_code == 403


def test_without_a_key_a_create_is_not_deduplicated_and_a_bad_key_is_refused(client, db, admin):
    for _ in range(2):
        client.post(f"{V1}/devices", json={"name": "Twice", "type": "esp32"}, headers=_h(admin))
    assert db.query(Device).filter(Device.name == "Twice").count() == 2
    bad = client.post(f"{V1}/devices", json={"name": "X", "type": "esp32"}, headers={**_h(admin), "Idempotency-Key": "short"})
    assert bad.status_code == 422


def test_a_failed_create_does_not_keep_its_key(client, db, admin):
    headers = {**_h(admin), "Idempotency-Key": "device-create-0003"}
    bad = client.post(f"{V1}/devices", json={"name": "F", "type": "esp32", "owner_id": "00000000-0000-4000-8000-000000000002"}, headers=headers)
    assert bad.status_code == 404
    good = client.post(f"{V1}/devices", json={"name": "F", "type": "esp32"}, headers=headers)
    assert good.status_code == 201 and "Idempotent-Replayed" not in good.headers


def test_the_stored_answer_is_encrypted_so_a_device_key_is_not_in_the_store(client, db, admin):
    headers = {**_h(admin), "Idempotency-Key": "device-create-0004"}
    key = client.post(f"{V1}/devices", json={"name": "Enc", "type": "esp32"}, headers=headers).json()["api_key"]
    assert all(key not in stored for _, stored in idempotency._local.values())


def test_rules_tickets_and_windows_accept_a_key_too(client, db, admin, device):
    rule = {"device_id": str(device.id), "metric": "temperature", "condition": "gt", "threshold": 70.0, "severity": "warning"}
    h = {**_h(admin), "Idempotency-Key": "rule-create-00001"}
    first, again = (client.post(f"{V1}/alert-rules", json=rule, headers=h) for _ in range(2))
    assert first.json()["id"] == again.json()["id"] and db.query(AlertRule).filter(AlertRule.device_id == device.id).count() == 1
    h2 = {**_h(admin), "Idempotency-Key": "window-create-001"}
    w1, w2 = (_window_with(client, h2) for _ in range(2))
    assert w1.json()["id"] == w2.json()["id"]
    assert db.query(MaintenanceWindow).count() == 1


def _window_with(client, headers):
    start = datetime(2030, 1, 1, tzinfo=timezone.utc)
    return client.post(f"{V1}/maintenance-windows", json={"label": "k", "start_at": start.isoformat(), "end_at": (start + timedelta(hours=1)).isoformat()}, headers=headers)


# -- webhooks ---------------------------------------------------------------------------------

def _resolves_to(monkeypatch, *addresses):
    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", lambda host, port, *a, **k: [(2, 1, 6, "", (x, port or 443)) for x in addresses])


class _Http:
    posts: list = []
    answers: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False

    def post(self, url, json=None, content=None, headers=None, extensions=None):
        _Http.posts.append({"url": url, "headers": headers, "body": content})
        status = _Http.answers.pop(0) if _Http.answers else 200
        return httpx.Response(status, request=httpx.Request("POST", url))


class _KeepOpen:
    # lets delivery record its outcome through the test's own session and close it without ending the test's transaction
    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


@pytest.fixture
def http(monkeypatch, db):
    monkeypatch.setattr("app.services.webhook_service.SessionLocal", lambda: _KeepOpen(db))
    _Http.posts, _Http.answers = [], []
    _resolves_to(monkeypatch, "8.8.8.8")
    monkeypatch.setattr("app.services.webhook_service.httpx.Client", _Http)
    return _Http


def _make_hook(client, admin, **kw):
    body = {"name": "Ops", "url": "https://hooks.example.org/x", "password": PASSWORD, **kw}
    return client.post(f"{V1}/webhooks", json=body, headers=_h(admin))


def test_a_json_webhook_shows_its_secret_once_and_never_returns_it(client, db, admin, monkeypatch):
    _resolves_to(monkeypatch, "8.8.8.8")
    made = _make_hook(client, admin, format="json")
    assert made.status_code == 201 and made.json()["secret"].startswith("whsec_") and made.json()["has_secret"] is True
    secret, wid = made.json()["secret"], made.json()["id"]
    for res in (client.get(f"{V1}/webhooks/{wid}", headers=_h(admin)), client.get(f"{V1}/webhooks", headers=_h(admin))):
        assert secret not in res.text
    # stored encrypted
    from sqlalchemy import text
    stored = db.execute(text("SELECT secret FROM webhooks WHERE id = CAST(:i AS uuid)"), {"i": wid}).scalar()
    assert stored.startswith("enc:v1:") and secret not in stored
    rotated = client.post(f"{V1}/webhooks/{wid}/rotate-secret", json={"password": PASSWORD}, headers=_h(admin))
    assert rotated.json()["secret"] != secret


def test_a_chat_webhook_has_no_secret_and_a_bad_template_is_refused_when_saved(client, db, admin, monkeypatch):
    _resolves_to(monkeypatch, "8.8.8.8")
    assert _make_hook(client, admin).json()["secret"] is None
    for template in ("{nope}", "{value.real}", "{value!r}", "{value:>9}", "oops {"):
        res = _make_hook(client, admin, template=template)
        assert res.status_code == 422 and res.json()["code"] == "webhook_template_invalid", template
    assert _make_hook(client, admin, template="{device_name}: {metric} {value}").status_code == 201
    assert _make_hook(client, admin, format="json", template="{value}").status_code == 422


def test_a_json_delivery_is_signed_with_a_time_and_verifies(client, db, admin, device, http, monkeypatch):
    secret = _make_hook(client, admin, format="json").json()["secret"]
    wh = db.query(Webhook).one()
    outcome = webhook_service.deliver_all(
        webhook_service.enabled_targets(db),
        {"device_name": "Pump", "device_id": str(device.id), "alert_id": "a1", "metric": "temperature", "value": 81.2,
         "threshold": 80.0, "severity": "critical", "condition": "gt", "reason": "raised", "kind": "rule"},
    )
    assert outcome is True
    (post,) = http.posts
    header = post["headers"]["X-Phaemos-Signature"]
    stamp, signature = (part.split("=", 1)[1] for part in header.split(","))
    assert abs(time.time() - int(stamp)) < 5
    expected = hmac.new(secret.encode(), f"{stamp}.".encode() + post["body"], hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected, signature)
    event = json.loads(post["body"])
    assert event["type"] == "alert.raised" and event["version"] == 1 and event["data"]["device"]["name"] == "Pump"
    assert event["data"]["alert"]["value"] == 81.2 and event["created_at"].endswith("Z")
    assert post["headers"]["X-Phaemos-Event"] == "alert.raised"
    db.refresh(wh)
    assert wh.last_status == 200 and wh.consecutive_failures == 0 and wh.last_delivery_at is not None


def test_a_wrong_secret_or_an_old_time_fails_the_documented_check(client, db, admin, http):
    secret = webhook_secrets_new()
    body = b'{"x":1}'
    header = webhook_service.sign(secret, body, at=int(time.time()) - 600)
    stamp, sig = (p.split("=", 1)[1] for p in header.split(","))
    assert abs(time.time() - int(stamp)) > 300
    assert webhook_service.sign("whsec_other", body, at=int(stamp)) != header


def webhook_secrets_new():
    from app.services import webhook_secrets
    return webhook_secrets.new_secret()


def test_a_failing_receiver_is_tried_three_times_and_the_failure_is_kept(client, db, admin, http):
    _make_hook(client, admin, format="json")
    http.answers = [500, 503, 500]
    assert webhook_service.deliver_all(webhook_service.enabled_targets(db), {"device_name": "P", "severity": "warning"}) is False
    assert len(http.posts) == 3
    wh = db.query(Webhook).one()
    db.refresh(wh)
    assert wh.consecutive_failures == 1 and wh.last_status == 500 and wh.last_error == "http 500"
    # the second delivery succeeds on its second try and the count resets
    http.posts.clear()
    http.answers = [502]
    assert webhook_service.deliver_all(webhook_service.enabled_targets(db), {"device_name": "P", "severity": "warning"}) is True
    db.refresh(wh)
    assert len(http.posts) == 2 and wh.consecutive_failures == 0


def test_a_receiver_that_says_no_is_not_asked_again(client, db, admin, http):
    _make_hook(client, admin, format="json")
    http.answers = [404]
    webhook_service.deliver_all(webhook_service.enabled_targets(db), {"device_name": "P", "severity": "warning"})
    assert len(http.posts) == 1


def test_the_test_route_reports_status_and_time_and_a_failure_is_not_a_200(client, db, admin, http):
    wid = _make_hook(client, admin).json()["id"]
    ok = client.post(f"{V1}/webhooks/{wid}/test", headers=_h(admin))
    assert ok.status_code == 200 and ok.json()["ok"] is True and ok.json()["status"] == 200 and ok.json()["elapsed_ms"] >= 0
    http.answers = [500]
    bad = client.post(f"{V1}/webhooks/{wid}/test", headers=_h(admin))
    assert bad.status_code == 502 and bad.json()["code"] == "webhook_delivery_failed"
    assert bad.json()["errors"][0]["status"] == 500 and "HTTP 500" in bad.json()["detail"]


def test_only_json_webhooks_hear_about_a_resolve(client, db, admin, device, http):
    _make_hook(client, admin, name="chat")
    _make_hook(client, admin, name="json", format="json", url="https://hooks.example.org/j")
    alert = _alert(db, device, 1, kind="rule")
    alert_service.notify_resolved(None, db, device, alert)
    assert len(http.posts) == 1
    assert json.loads(http.posts[0]["body"])["type"] == "alert.resolved"


def test_a_chat_message_to_discord_pings_nobody(client, db, admin, http):
    _make_hook(client, admin, url="https://discord.com/api/webhooks/1/abc")
    webhook_service.deliver_all(webhook_service.enabled_targets(db), {"device_name": "@everyone", "metric": "t", "value": 1, "threshold": 2, "severity": "info"})
    assert json.loads(http.posts[0]["body"])["allowed_mentions"] == {"parse": []}


def test_webhook_lists_page_and_filter(client, db, admin, monkeypatch):
    _resolves_to(monkeypatch, "8.8.8.8")
    for n in range(3):
        _make_hook(client, admin, name=f"w{n}")
    res = client.get(f"{V1}/webhooks", params={"limit": 2}, headers=_h(admin))
    assert len(res.json()) == 2 and res.headers["X-Total-Count"] == "3"


# -- readings ---------------------------------------------------------------------------------

def test_readings_walk_by_keyset_and_accept_from_and_to(client, db, admin, device):
    now = datetime.now(timezone.utc)
    for i in range(7):
        db.add(Telemetry(device_id=device.id, temperature=float(i), recorded_at=now - timedelta(seconds=10 * (i // 2))))
    db.flush()
    seen, cursor = [], None
    for _ in range(10):
        res = client.get(f"{V1}/telemetry/{device.id}", params={"limit": 3, **({"before": cursor} if cursor else {})}, headers=_h(admin))
        rows = res.json()
        seen += [r["id"] for r in rows]
        assert "X-Total-Count" not in res.headers
        if len(rows) < 3:
            break
        cursor = res.headers["X-Next-Before"]
    assert len(seen) == 7 and len(set(seen)) == 7
    since = (now - timedelta(seconds=15)).isoformat()
    assert len(client.get(f"{V1}/telemetry/{device.id}", params={"from": since}, headers=_h(admin)).json()) == 4
    assert len(client.get(f"{V1}/telemetry/{device.id}", params={"from_ts": since}, headers=_h(admin)).json()) == 4
    assert client.get(f"{V1}/telemetry/{device.id}", params={"before": "garbage"}, headers=_h(admin)).status_code == 422


# -- the daily limits and the 429 headers -------------------------------------------------------

def test_the_daily_limits_are_on_alert_metrics_for_every_role(client, db, tech, monkeypatch):
    monkeypatch.setattr(cooldown, "_redis_down_until", time.monotonic() + 1000)
    cooldown._local_daily.clear()
    cooldown.count_daily("email", 50)
    body = client.get(f"{V1}/alert-metrics", headers=_h(tech)).json()
    email = body["daily_limits"]["email"]
    assert email["reached"] is True and email["count"] == 50 and email["limit"] == 50 and email["resets_at"].endswith("Z")
    assert body["daily_limits"]["sms"]["reached"] is False
    assert set(email) == {"limit", "count", "reached", "resets_at"}
    cooldown._local_daily.clear()


def test_every_hand_raised_429_carries_retry_after_and_the_rate_limit_headers(client, db, device, monkeypatch):
    monkeypatch.setattr(ingest_limit, "MAX_POSTS", 1)
    h = {"X-API-Key": device.api_key}
    client.post(f"{V1}/telemetry", json={"temperature": 1.0}, headers=h)
    res = client.post(f"{V1}/telemetry", json={"temperature": 1.0}, headers=h)
    assert res.status_code == 429 and res.json()["code"] == "device_rate_limited"
    assert int(res.headers["Retry-After"]) >= 1 and "X-RateLimit-Limit" in res.headers and res.headers["X-RateLimit-Remaining"] == "0"
    monkeypatch.setattr(ingest_limit, "BATCH_ITEMS_PER_DEVICE", 1)
    big = client.post(f"{V1}/telemetry/batch", json={"readings": [{"temperature": 1.0}] * 2}, headers=h)
    assert big.status_code == 429 and "X-RateLimit-Reset" in big.headers


def test_firmware_checks_are_limited_per_device_and_not_per_address(client, db, device):
    other = Device(name="Hub 2", api_key=secrets.token_urlsafe(32))
    db.add(other)
    db.flush()
    from app.routes import firmware
    for _ in range(firmware.LATEST_PER_MINUTE):
        client.get(f"{V1}/firmware/latest", headers={"X-API-Key": device.api_key})
    over = client.get(f"{V1}/firmware/latest", headers={"X-API-Key": device.api_key})
    assert over.status_code == 429 and over.json()["code"] == "device_rate_limited" and "Retry-After" in over.headers
    # another hub behind the same address still gets through (a 404 here only because no firmware was uploaded)
    assert client.get(f"{V1}/firmware/latest", headers={"X-API-Key": other.api_key}).status_code in (200, 404)


# -- service accounts are never an owner or an assignee ---------------------------------------

def _service(db):
    user = User(name="svc", email="svc@example.com", password_hash=hash_password(PASSWORD), role="technician", is_service=True)
    db.add(user)
    db.flush()
    return user


def test_a_service_account_cannot_own_a_machine_and_is_refused_like_an_unknown_user(client, db, admin, device):
    svc = _service(db)
    unknown = client.patch(f"{V1}/devices/{device.id}", json={"owner_id": "00000000-0000-4000-8000-0000000000aa"}, headers=_h(admin))
    refused = client.patch(f"{V1}/devices/{device.id}", json={"owner_id": str(svc.id)}, headers=_h(admin))
    assert (refused.status_code, refused.json()["code"], refused.json()["detail"]) == (unknown.status_code, unknown.json()["code"], unknown.json()["detail"])
    assert refused.status_code == 404
    made = client.post(f"{V1}/devices", json={"name": "S", "type": "esp32", "owner_id": str(svc.id)}, headers=_h(admin))
    assert made.status_code == 404


def test_a_service_account_cannot_be_assigned_a_ticket_and_is_not_listed(client, db, admin, device):
    svc = _service(db)
    t = Ticket(device_id=device.id, title="t", status="open", priority="low", created_by=admin.id)
    db.add(t)
    db.flush()
    unknown = client.patch(f"{V1}/tickets/{t.id}", json={"assigned_to": "00000000-0000-4000-8000-0000000000bb"}, headers=_h(admin))
    refused = client.patch(f"{V1}/tickets/{t.id}", json={"assigned_to": str(svc.id)}, headers=_h(admin))
    assert (refused.status_code, refused.json()["code"]) == (unknown.status_code, unknown.json()["code"]) == (404, "assignee_not_found")
    assert str(svc.id) not in [p["id"] for p in client.get(f"{V1}/tickets/assignees", headers=_h(admin)).json()]
