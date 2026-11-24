"""
Access tokens: what a token may and may not do, the denials made by construction, the same 401 for every bad token, limits that
cannot be escaped with more tokens and the audit trail.
"""

import inspect
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIWebSocketRoute
from passlib.context import CryptContext
from sqlalchemy import text
from starlette.requests import Request

from app.limiter import _rate_key
from app.main import app
from app.models.api_token import ApiToken
from app.models.device import Device
from app.models.user import User
from app.routes.auth import create_access_token
from app.services import token_access

PASSWORD = "Passw0rd!x"
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _user(db, email, role="admin", **extra):
    user = User(name=email.split("@")[0], email=email, role=role, password_hash=_pwd.hash(PASSWORD), **extra)
    db.add(user)
    db.flush()
    return user


def _session(user):
    return {"Authorization": "Bearer " + create_access_token({"sub": str(user.id), "role": user.role})}


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _make(client, user, scope="read", name="ci", **extra):
    res = client.post("/api/v1/auth/tokens", json={"name": name, "scope": scope, "password": PASSWORD, **extra}, headers=_session(user))
    assert res.status_code == 201, res.text
    return res.json()


def _machine(db, owner=None):
    device = Device(name="Press", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32), owner_id=owner.id if owner else None)
    db.add(device)
    db.flush()
    return device


# ── every route is in exactly one stated class ──────────────────────────────

# (method, path) -> (class, least scope). A new route that is not in this table fails the test below and so does a route
# whose class no longer matches. A route that should be session only or needs a higher scope, is stated here on purpose
STATED = {
    ("GET", "/"): ("public", None),
    ("GET", "/api/v1/alert-metrics"): ("token", 'read'),
    ("GET", "/api/v1/alert-rules"): ("token", 'read'),
    ("POST", "/api/v1/alert-rules"): ("token", 'admin'),
    ("DELETE", "/api/v1/alert-rules/{rule_id}"): ("token", 'admin'),
    ("PUT", "/api/v1/alert-rules/{rule_id}"): ("token", 'admin'),
    ("GET", "/api/v1/alerts"): ("token", 'read'),
    ("PATCH", "/api/v1/alerts/{alert_id}/resolve"): ("token", 'operate'),
    ("GET", "/api/v1/audit-logs"): ("token", 'admin'),
    ("GET", "/api/v1/audit-logs/export"): ("token", 'admin'),
    ("POST", "/api/v1/auth/2fa/confirm"): ("session_only", None),
    ("POST", "/api/v1/auth/2fa/disable"): ("session_only", None),
    ("POST", "/api/v1/auth/2fa/enable"): ("session_only", None),
    ("POST", "/api/v1/auth/2fa/verify"): ("public", None),
    ("POST", "/api/v1/auth/accept-invite"): ("public", None),
    ("GET", "/api/v1/auth/apple"): ("public", None),
    ("POST", "/api/v1/auth/change-password"): ("session_only", None),
    ("GET", "/api/v1/auth/github"): ("public", None),
    ("GET", "/api/v1/auth/github/callback"): ("public", None),
    ("GET", "/api/v1/auth/google"): ("public", None),
    ("GET", "/api/v1/auth/google/callback"): ("public", None),
    ("GET", "/api/v1/auth/invitations"): ("session_only", None),
    ("DELETE", "/api/v1/auth/invitations/{invitation_id}"): ("session_only", None),
    ("POST", "/api/v1/auth/invite"): ("session_only", None),
    ("POST", "/api/v1/auth/invite/check"): ("public", None),
    ("POST", "/api/v1/auth/link/{provider}"): ("session_only", None),
    ("POST", "/api/v1/auth/login"): ("public", None),
    ("POST", "/api/v1/auth/logout"): ("public", None),
    ("DELETE", "/api/v1/auth/me"): ("session_only", None),
    ("GET", "/api/v1/auth/me"): ("session_only", None),
    ("PATCH", "/api/v1/auth/me"): ("session_only", None),
    ("GET", "/api/v1/auth/me/export"): ("session_only", None),
    ("POST", "/api/v1/auth/me/phone/confirm"): ("session_only", None),
    ("POST", "/api/v1/auth/me/phone/send-code"): ("session_only", None),
    ("GET", "/api/v1/auth/microsoft"): ("public", None),
    ("GET", "/api/v1/auth/microsoft/callback"): ("public", None),
    ("GET", "/api/v1/auth/providers"): ("public", None),
    ("POST", "/api/v1/auth/refresh"): ("public", None),
    ("POST", "/api/v1/auth/register"): ("public", None),
    ("POST", "/api/v1/auth/reset-password"): ("public", None),
    ("GET", "/api/v1/auth/sessions"): ("session_only", None),
    ("POST", "/api/v1/auth/sessions/end-others"): ("session_only", None),
    ("DELETE", "/api/v1/auth/sessions/{session_id}"): ("session_only", None),
    ("GET", "/api/v1/auth/tokens"): ("token", 'read'),
    ("POST", "/api/v1/auth/tokens"): ("session_only", None),
    ("DELETE", "/api/v1/auth/tokens/{token_id}"): ("session_only", None),
    ("GET", "/api/v1/auth/users"): ("session_only", None),
    ("DELETE", "/api/v1/auth/users/{user_id}"): ("session_only", None),
    ("POST", "/api/v1/auth/users/{user_id}/clear-two-step"): ("session_only", None),
    ("POST", "/api/v1/auth/users/{user_id}/deactivate"): ("session_only", None),
    ("POST", "/api/v1/auth/users/{user_id}/reactivate"): ("session_only", None),
    ("POST", "/api/v1/auth/users/{user_id}/reset-link"): ("session_only", None),
    ("PATCH", "/api/v1/auth/users/{user_id}/role"): ("session_only", None),
    ("GET", "/api/v1/auth/whoami"): ("token", 'read'),
    ("POST", "/api/v1/contact"): ("public", None),
    ("POST", "/api/v1/demo/start"): ("token", 'admin'),
    ("POST", "/api/v1/demo/stop"): ("token", 'admin'),
    ("GET", "/api/v1/devices"): ("token", 'read'),
    ("POST", "/api/v1/devices"): ("token", 'admin'),
    ("POST", "/api/v1/devices/batch/firmware-update"): ("token", 'admin'),
    ("DELETE", "/api/v1/devices/{device_id}"): ("token", 'admin'),
    ("GET", "/api/v1/devices/{device_id}"): ("token", 'read'),
    ("PATCH", "/api/v1/devices/{device_id}"): ("token", 'operate'),
    ("POST", "/api/v1/devices/{device_id}/accept-counter"): ("token", 'admin'),
    ("POST", "/api/v1/devices/{device_id}/rotate-key"): ("session_only", None),
    ("POST", "/api/v1/devices/{device_id}/tags"): ("token", 'admin'),
    ("DELETE", "/api/v1/devices/{device_id}/tags/{tag}"): ("token", 'admin'),
    ("GET", "/api/v1/firmware/download"): ("device_key", None),
    ("GET", "/api/v1/firmware/latest"): ("device_key", None),
    ("POST", "/api/v1/firmware/upload"): ("session_only", None),
    ("GET", "/api/v1/health/summary"): ("token", 'read'),
    ("GET", "/api/v1/maintenance-windows"): ("token", 'read'),
    ("POST", "/api/v1/maintenance-windows"): ("token", 'admin'),
    ("DELETE", "/api/v1/maintenance-windows/{window_id}"): ("token", 'admin'),
    ("PATCH", "/api/v1/maintenance-windows/{window_id}"): ("token", 'admin'),
    ("GET", "/api/v1/ml/anomalies/{device_id}"): ("token", 'read'),
    ("POST", "/api/v1/ml/retrain"): ("token", 'admin'),
    ("POST", "/api/v1/ml/score"): ("token", 'admin'),
    ("GET", "/api/v1/ml/status"): ("token", 'read'),
    # a person's verdict on an alert is day-to-day work on alerts, like resolving one. Lifting the bound on how far a retrain
    # may move a machine's normal defeats the guard against a slow forged walk, so it is a signed-in admin with fresh proof
    ("POST", "/api/v1/ml/alerts/{alert_id}/verdict"): ("token", "operate"),
    ("POST", "/api/v1/ml/machines/{device_id}/accept-move"): ("session_only", None),
    # which node is a machine's ambient reference is configuration of the model: an admin's change
    ("PUT", "/api/v1/ml/machines/{device_id}/ambient-source"): ("token", "admin"),
    ("POST", "/api/v1/telemetry"): ("device_key", None),
    ("GET", "/api/v1/telemetry/export"): ("token", 'read'),
    ("GET", "/api/v1/telemetry/{device_id}"): ("token", 'read'),
    ("GET", "/api/v1/telemetry/{device_id}/latest"): ("token", 'read'),
    ("GET", "/api/v1/tickets"): ("token", 'read'),
    ("POST", "/api/v1/tickets"): ("token", 'operate'),
    ("GET", "/api/v1/tickets/assignees"): ("token", 'read'),
    ("GET", "/api/v1/tickets/{ticket_id}"): ("token", 'read'),
    ("PATCH", "/api/v1/tickets/{ticket_id}"): ("token", 'operate'),
    ("GET", "/api/v1/webhooks"): ("token", 'admin'),
    ("POST", "/api/v1/webhooks"): ("session_only", None),
    ("DELETE", "/api/v1/webhooks/{webhook_id}"): ("token", 'admin'),
    ("PATCH", "/api/v1/webhooks/{webhook_id}"): ("session_only", None),
    ("POST", "/api/v1/webhooks/{webhook_id}/test"): ("token", 'admin'),
    ("GET", "/status"): ("public", None),
}
# routes that moved or were added in the conventions round. The old /auth paths above are the deprecated aliases of these
STATED.update({
    ("GET", "/api/v1/users"): ("session_only", None),
    ("DELETE", "/api/v1/users/{user_id}"): ("session_only", None),
    ("POST", "/api/v1/users/{user_id}/deactivate"): ("session_only", None),
    ("POST", "/api/v1/users/{user_id}/reactivate"): ("session_only", None),
    ("PATCH", "/api/v1/users/{user_id}/role"): ("session_only", None),
    ("POST", "/api/v1/users/{user_id}/clear-two-step"): ("session_only", None),
    ("POST", "/api/v1/users/{user_id}/reset-link"): ("session_only", None),
    ("GET", "/api/v1/invitations"): ("session_only", None),
    ("POST", "/api/v1/invitations"): ("session_only", None),
    ("DELETE", "/api/v1/invitations/{invitation_id}"): ("session_only", None),
    ("POST", "/api/v1/service-accounts"): ("session_only", None),
    ("GET", "/api/v1/tokens"): ("token", "read"),
    ("POST", "/api/v1/tokens"): ("session_only", None),
    ("DELETE", "/api/v1/tokens/{token_id}"): ("session_only", None),
    ("DELETE", "/api/v1/tokens/current"): ("token", "read"),
    ("GET", "/api/v1/fleet/summary"): ("token", "read"),
    # routes the ingest round added
    ("POST", "/api/v1/telemetry/batch"): ("device_key", None),
    ("GET", "/api/v1/alerts/{alert_id}"): ("token", "read"),
    ("POST", "/api/v1/alerts/{alert_id}/resolve"): ("token", "operate"),
    ("GET", "/api/v1/alert-rules/{rule_id}"): ("token", "read"),
    ("PATCH", "/api/v1/alert-rules/{rule_id}"): ("token", "admin"),
    ("GET", "/api/v1/webhooks/{webhook_id}"): ("token", "admin"),
    ("POST", "/api/v1/webhooks/{webhook_id}/rotate-secret"): ("session_only", None),
    ("GET", "/api/v1/maintenance-windows/{window_id}"): ("token", "read"),
    ("GET", "/livez"): ("public", None),
    # scraped by Prometheus on the internal network. Nginx answers 404 for it from outside. The API cannot tell the two apart,
    # so it carries no data about people: request counts and timings only
    ("GET", "/metrics"): ("public", None),
    ("GET", "/readyz"): ("public", None),
})
# the demo routes exist only when the demo is switched on
OPTIONAL = {("POST", "/api/v1/demo/start"), ("POST", "/api/v1/demo/stop")}
STATED.update({("POST", "/api/v1/demo/start"): ("token", "admin"), ("POST", "/api/v1/demo/stop"): ("token", "admin")})


def _walk():
    for route in token_access.iter_routes(app):
        for method in sorted((getattr(route, "methods", None) or set()) - {"HEAD", "OPTIONS"}):
            yield route, method, token_access.classify(route, method)


def test_every_route_is_in_exactly_one_stated_class_and_the_table_is_printed(capsys):
    seen = {}
    for route, method, kind in _walk():
        key = (method, route.path_format)
        assert key not in seen, f"{key} is registered twice"
        seen[key] = (kind.kind, kind.least_scope)
    unlisted = sorted(set(seen) - set(STATED))
    assert not unlisted, f"routes nobody classified (add them to STATED on purpose): {unlisted}"
    gone = sorted(k for k in set(STATED) - set(seen) if k not in OPTIONAL)
    assert not gone, f"routes in the table that no longer exist: {gone}"
    wrong = {k: (seen[k], STATED[k]) for k in seen if seen[k] != STATED[k]}
    assert not wrong, f"routes whose class changed (found, stated): {wrong}"
    assert not [k for k, v in seen.items() if v[0] == token_access.UNCLASSIFIED]
    with capsys.disabled():
        print("\nroute class table (method, path, class, least scope)")
        for (method, path), (kind, least) in sorted(seen.items(), key=lambda item: (item[0][1], item[0][0])):
            print(f"  {method:6} {path:55} {kind:13} {least or '-'}")


def test_the_live_socket_takes_a_session_and_never_a_token():
    # the socket is not an HTTP route, so the walk above does not see it. It takes a session's access token only, because it
    # decodes it as a JWT (see test_the_socket_refuses_an_access_token)
    from app.routes import ws
    assert [r.path for r in ws.router.routes] == ["/ws/telemetry/{device_id}"]
    assert isinstance(ws.router.routes[0], APIWebSocketRoute)


def test_the_socket_refuses_an_access_token(client, db):
    user = _user(db, "ws1@test.com")
    machine = _machine(db)
    token = _make(client, user, "admin")["token"]
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/telemetry/{machine.id}") as ws:
            ws.send_json({"type": "auth", "token": token})
            ws.receive_json()


def _fill(path):
    return re.sub(r"\{[^}]+\}", lambda m: str(uuid.uuid4()) if "id" in m.group(0) else "x", path)


def test_a_token_is_refused_on_every_session_only_route(client, db):
    user = _user(db, "so1@test.com")
    token = _make(client, user, "admin")["token"]
    checked = 0
    for method, path in sorted(STATED):
        if STATED[(method, path)][0] != token_access.SESSION_ONLY:
            continue
        res = client.request(method, _fill(path), headers=_bearer(token), json={})
        assert (res.status_code, res.json()["detail"]) == (403, token_access.SESSION_NEEDED), (method, path, res.text)
        checked += 1
    assert checked >= 25


def test_a_read_token_cannot_make_any_change_and_an_operate_token_cannot_make_an_admin_change(client, db):
    user = _user(db, "sc1@test.com")
    read = _make(client, user, "read")["token"]
    operate = _make(client, user, "operate")["token"]
    for (method, path), (kind, least) in sorted(STATED.items()):
        # a token revoking itself is the one write open to every scope
        if kind != token_access.TOKEN or (method == "GET" and least != "admin") or (method != "GET" and least == "read"):
            continue
        res = client.request(method, _fill(path), headers=_bearer(read), json={})
        assert res.status_code == 403 and "scope" in res.json()["detail"], (method, path, res.text)
        if least == "admin":
            res = client.request(method, _fill(path), headers=_bearer(operate), json={})
            assert res.status_code == 403 and "needs admin" in res.json()["detail"], (method, path, res.text)


def test_a_read_token_cannot_read_the_audit_trail_or_the_webhook_list(client, db):
    admin = _user(db, "ad1@test.com")
    read = _make(client, admin, "read")["token"]
    full = _make(client, admin, "admin")["token"]
    for path in ("/api/v1/audit-logs", "/api/v1/audit-logs/export", "/api/v1/webhooks"):
        assert client.get(path, headers=_bearer(read)).status_code == 403, path
        assert client.get(path, headers=_bearer(full)).status_code == 200, path
    # the rule is the mechanism: every route that depends on require_admin needs admin for every method
    from app.routes.auth import require_admin
    for route, method, kind in _walk():
        calls = [part.call for part in token_access._walk(route.dependant)]
        if require_admin in calls and kind.kind == token_access.TOKEN:
            assert kind.least_scope == "admin", (method, route.path_format)


def test_no_get_route_a_token_may_call_writes():
    # `read` must not cause a write, so a GET handler that changes state would be a hole. This reads each handler's source
    writes = re.compile(r"\.commit\(|\.add\(|\.delete\(|log_action\(|\.flush\(|INSERT |UPDATE |DELETE FROM")
    for route, method, kind in _walk():
        if kind.kind == token_access.TOKEN and method == "GET":
            assert not writes.search(inspect.getsource(route.endpoint)), f"GET {route.path_format} writes"


def test_a_read_token_reads_and_an_operate_token_edits_a_machine_but_not_its_owner(client, db):
    admin = _user(db, "op1@test.com")
    other = _user(db, "op2@test.com", "technician")
    machine = _machine(db)
    read = _make(client, admin, "read")["token"]
    operate = _make(client, admin, "operate")["token"]
    full = _make(client, admin, "admin")["token"]
    assert client.get("/api/v1/devices", headers=_bearer(read)).status_code == 200
    assert client.get(f"/api/v1/devices/{machine.id}", headers=_bearer(read)).status_code == 200
    assert client.patch(f"/api/v1/devices/{machine.id}", json={"name": "New"}, headers=_bearer(read)).status_code == 403
    assert client.patch(f"/api/v1/devices/{machine.id}", json={"name": "New"}, headers=_bearer(operate)).status_code == 200
    refused = client.patch(f"/api/v1/devices/{machine.id}", json={"owner_id": str(other.id)}, headers=_bearer(operate))
    assert (refused.status_code, refused.json()["detail"]) == (403, "Only an admin can change owner_id")
    assert client.patch(f"/api/v1/devices/{machine.id}", json={"owner_id": str(other.id)}, headers=_bearer(full)).status_code == 200
    # the same admin account on a session may, which shows it is the token's scope that refused
    assert client.patch(f"/api/v1/devices/{machine.id}", json={"owner_id": None}, headers=_session(admin)).status_code == 200


def test_an_admin_scope_token_deletes_a_machine_and_the_audit_row_names_the_token(client, db):
    admin = _user(db, "au1@test.com")
    machine = _machine(db)
    made = _make(client, admin, "admin")
    assert client.delete(f"/api/v1/devices/{machine.id}", headers=_bearer(made["token"])).status_code == 204
    row = db.execute(text("SELECT detail FROM audit_log WHERE action = 'device_deleted' AND resource_id = :id"), {"id": str(machine.id)}).one()
    assert f"[via token {made['id']}]" in row.detail
    # a session leaves no such mark and the export carries the detail column
    other = _machine(db)
    assert client.delete(f"/api/v1/devices/{other.id}", headers=_session(admin)).status_code == 204
    row = db.execute(text("SELECT detail FROM audit_log WHERE action = 'device_deleted' AND resource_id = :id"), {"id": str(other.id)}).one()
    assert "via token" not in row.detail
    export = client.get("/api/v1/audit-logs/export", headers=_session(admin))
    assert export.status_code == 200 and f"[via token {made['id']}]" in export.text


def test_lowering_a_role_or_deactivating_an_account_takes_effect_on_the_next_call(client, db):
    admin = _user(db, "rl1@test.com")
    token = _make(client, admin, "admin")["token"]
    assert client.get("/api/v1/webhooks", headers=_bearer(token)).status_code == 200
    machine = _machine(db)
    admin.role = "viewer"
    db.flush()
    after = client.get("/api/v1/webhooks", headers=_bearer(token))
    # the admin scope is only as good as the role now, so the token falls to operate and is refused
    assert after.status_code == 403 and "needs admin" in after.json()["detail"]
    assert client.delete(f"/api/v1/devices/{machine.id}", headers=_bearer(token)).status_code == 403
    assert client.get("/api/v1/auth/whoami", headers=_bearer(token)).json()["role"] == "viewer"
    admin.is_active = False
    db.flush()
    assert client.get("/api/v1/auth/whoami", headers=_bearer(token)).status_code == 401


def test_ending_the_sessions_or_a_password_change_ends_the_tokens(client, db):
    user = _user(db, "rv1@test.com", "technician")
    made = _make(client, user, "read")
    assert client.get("/api/v1/auth/whoami", headers=_bearer(made["token"])).status_code == 200
    user.token_version = (user.token_version or 0) + 1
    db.flush()
    assert client.get("/api/v1/auth/whoami", headers=_bearer(made["token"])).status_code == 401


# ── every bad token gets the same answer for the same cost ──────────────────

def test_unknown_malformed_expired_and_revoked_tokens_cost_one_hash_and_answer_the_same(client, db, monkeypatch):
    user = _user(db, "bad1@test.com", "technician")
    expired = _make(client, user)
    revoked = _make(client, user)
    wrong = _make(client, user)
    db.query(ApiToken).filter(ApiToken.id == expired["id"]).update({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    assert client.delete(f"/api/v1/auth/tokens/{revoked['id']}", headers=_session(user)).status_code == 204
    good = _make(client, user)
    bad = {
        "unknown": "pht_" + "0" * 12 + "_" + "A" * 43,
        "malformed": "pht_not-a-token",
        "empty": "pht_",
        "huge": "pht_" + "z" * 5000,
        "expired": expired["token"],
        "revoked": revoked["token"],
        "wrong secret": wrong["token"][:-1] + ("A" if wrong["token"][-1] != "A" else "B"),
    }
    calls = []
    real = token_access._digest
    monkeypatch.setattr(token_access, "_digest", lambda key, value: calls.append(1) or real(key, value))
    answers = set()
    for name, token in bad.items():
        calls.clear()
        res = client.get("/api/v1/auth/whoami", headers=_bearer(token))
        assert len(calls) == 1, (name, len(calls))
        answers.add((res.status_code, res.json()["code"], res.json()["detail"], res.headers.get("www-authenticate")))
    assert answers == {(401, "token_invalid", "Invalid or expired token", "Bearer")}
    calls.clear()
    assert client.get("/api/v1/auth/whoami", headers=_bearer(good["token"])).status_code == 200
    assert len(calls) == 1


# ── limits are counted per token and cannot be escaped with more tokens ─────

def test_a_limit_is_counted_per_verified_token_and_a_forged_header_gets_no_bucket_of_its_own():
    def request(state=None):
        req = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "client": ("203.0.113.9", 1), "query_string": b""})
        if state:
            req.state.rate_key = state
        return req
    assert _rate_key(request()) == "203.0.113.9"
    assert _rate_key(request("token:abc")) == "token:abc"


def test_a_forged_authorization_header_does_not_change_the_key(client):
    # the key is set only after the token is checked, so a made-up token is refused first and never reaches a limit
    res = client.get("/api/v1/auth/whoami", headers=_bearer("pht_" + "1" * 12 + "_" + "B" * 43))
    assert res.status_code == 401


def test_many_tokens_share_one_account_ceiling(client, db, monkeypatch):
    user = _user(db, "lim1@test.com", "technician")
    tokens = [_make(client, user, name=f"t{n}")["token"] for n in range(4)]
    monkeypatch.setattr(token_access, "ACCOUNT_REQUESTS_PER_MINUTE", 3)
    statuses = [client.get("/api/v1/auth/whoami", headers=_bearer(tokens[n % 4])).status_code for n in range(5)]
    assert statuses == [200, 200, 200, 429, 429]


def test_two_tokens_on_one_address_have_separate_per_route_limits(client, db):
    user = _user(db, "lim2@test.com", "admin")
    one, two = (_make(client, user, "admin", name=n)["token"] for n in ("one", "two"))
    url = f"/api/v1/webhooks/{uuid.uuid4()}/test"
    # this route allows 10 a minute. Both tokens come from one address
    first = [client.post(url, headers=_bearer(one)).status_code for _ in range(11)]
    assert first[:10] == [404] * 10 and first[10] == 429
    # the other token has its own count, so two scripts behind one address do not starve each other
    assert client.post(url, headers=_bearer(two)).status_code == 404


# ── making, listing and revoking ────────────────────────────────────────────

def test_a_token_is_shown_once_and_only_its_hash_is_stored(client, db):
    user = _user(db, "mk1@test.com", "technician")
    made = _make(client, user, "operate", name="  laptop  ", expires_in_days=30)
    assert set(made) == {"id", "name", "scope", "created_at", "expires_at", "account_id", "token"}
    assert made["name"] == "laptop" and made["scope"] == "operate"
    assert re.fullmatch(r"pht_[0-9a-f]{12}_[A-Za-z0-9_-]{43}", made["token"]) and made["token"].split("_")[1] == made["id"]
    row = db.get(ApiToken, made["id"])
    secret = made["token"].split("_", 2)[2]
    assert secret not in row.secret_hash and len(row.secret_hash) == 64 and row.secret_hash != secret
    listed = client.get("/api/v1/auth/tokens", headers=_session(user)).json()
    assert [t["id"] for t in listed] == [made["id"]]
    assert "token" not in listed[0] and secret not in str(listed)
    assert set(listed[0]) == {"id", "name", "scope", "created_at", "expires_at", "last_used_at", "account_id", "created_by"}
    # a token may list the tokens too and see no secret
    assert client.get("/api/v1/auth/tokens", headers=_bearer(made["token"])).status_code == 200
    expires = datetime.fromisoformat(made["expires_at"])
    assert timedelta(days=29, hours=23) < expires - datetime.now(timezone.utc) < timedelta(days=30, hours=1)


def test_making_a_token_needs_proof_a_session_and_a_valid_body(client, db):
    user = _user(db, "mk2@test.com", "technician")
    body = {"name": "x", "scope": "read"}
    assert client.post("/api/v1/auth/tokens", json=body, headers=_session(user)).status_code == 400
    assert client.post("/api/v1/auth/tokens", json={**body, "password": "wrong"}, headers=_session(user)).status_code == 400
    token = _make(client, user)["token"]
    refused = client.post("/api/v1/auth/tokens", json={**body, "password": PASSWORD}, headers=_bearer(token))
    assert (refused.status_code, refused.json()["detail"]) == (403, token_access.SESSION_NEEDED)
    for bad in ({"name": "", "scope": "read"}, {"name": "x" * 61, "scope": "read"}, {"name": "a\nb", "scope": "read"},
                {"name": "x", "scope": "root"}, {"name": "x", "scope": "read", "expires_in_days": 0},
                {"name": "x", "scope": "read", "expires_in_days": 366}):
        assert client.post("/api/v1/auth/tokens", json={**bad, "password": PASSWORD}, headers=_session(user)).status_code == 422, bad
    made = _make(client, user)
    assert datetime.fromisoformat(made["expires_at"]) - datetime.now(timezone.utc) > timedelta(days=89)


def test_only_an_admin_account_can_make_an_admin_token_and_there_are_at_most_twenty(client, db, monkeypatch):
    # twenty proofs in a minute is the proof limit and this test makes more than that on purpose
    from app.services import signin_guard
    monkeypatch.setattr(signin_guard, "proof_rate_ok", lambda key: True)
    tech = _user(db, "mk3@test.com", "technician")
    res = client.post("/api/v1/auth/tokens", json={"name": "x", "scope": "admin", "password": PASSWORD}, headers=_session(tech))
    assert (res.status_code, res.json()["detail"]) == (403, "Only an admin account can have an admin token")
    from app.limiter import limiter
    limiter.enabled = False
    try:
        for n in range(20):
            _make(client, tech, name=f"t{n}")
        over = client.post("/api/v1/auth/tokens", json={"name": "x", "scope": "read", "password": PASSWORD}, headers=_session(tech))
        assert over.status_code == 409
        first = client.get("/api/v1/auth/tokens", headers=_session(tech)).json()[0]["id"]
        assert client.delete(f"/api/v1/auth/tokens/{first}", headers=_session(tech)).status_code == 204
        assert client.post("/api/v1/auth/tokens", json={"name": "x", "scope": "read", "password": PASSWORD}, headers=_session(tech)).status_code == 201
    finally:
        limiter.enabled = True


def test_revoking_works_by_session_only_and_another_account_gets_404(client, db):
    one = _user(db, "rk1@test.com", "technician")
    two = _user(db, "rk2@test.com", "technician")
    mine = _make(client, one)
    theirs = _make(client, two)
    assert client.delete(f"/api/v1/auth/tokens/{theirs['id']}", headers=_session(one)).status_code == 404
    assert client.delete("/api/v1/auth/tokens/000000000000", headers=_session(one)).status_code == 404
    assert client.delete("/api/v1/auth/tokens/not-an-id", headers=_session(one)).status_code == 404
    by_token = client.delete(f"/api/v1/auth/tokens/{mine['id']}", headers=_bearer(mine["token"]))
    assert (by_token.status_code, by_token.json()["detail"]) == (403, token_access.SESSION_NEEDED)
    assert client.delete(f"/api/v1/auth/tokens/{mine['id']}", headers=_session(one)).status_code == 204
    assert client.get("/api/v1/auth/whoami", headers=_bearer(mine["token"])).status_code == 401
    assert client.get("/api/v1/auth/whoami", headers=_bearer(theirs["token"])).status_code == 200
    actions = [r.action for r in db.execute(text("SELECT action FROM audit_log WHERE resource = 'api_token' ORDER BY created_at")).all()]
    assert "token_created" in actions and "token_revoked" in actions


def test_whoami_answers_for_a_session_and_a_token(client, db):
    user = _user(db, "wh1@test.com", "technician")
    session = client.get("/api/v1/auth/whoami", headers=_session(user)).json()
    assert session == {"id": str(user.id), "role": "technician", "signed_in_with": "session", "token": None, "is_service": False}
    made = _make(client, user, "operate", name="ci")
    token = client.get("/api/v1/auth/whoami", headers=_bearer(made["token"])).json()
    assert token["signed_in_with"] == "token" and token["id"] == str(user.id)
    assert token["token"] == {"id": made["id"], "name": "ci", "scope": "operate", "expires_at": made["expires_at"]}


def test_last_used_moves_at_most_once_a_minute(client, db):
    user = _user(db, "lu1@test.com", "technician")
    made = _make(client, user)
    assert db.get(ApiToken, made["id"]).last_used_at is None
    client.get("/api/v1/auth/whoami", headers=_bearer(made["token"]))
    first = db.get(ApiToken, made["id"]).last_used_at
    assert first is not None
    client.get("/api/v1/auth/whoami", headers=_bearer(made["token"]))
    assert db.get(ApiToken, made["id"]).last_used_at == first
    db.query(ApiToken).filter(ApiToken.id == made["id"]).update({"last_used_at": first - timedelta(minutes=2)})
    client.get("/api/v1/auth/whoami", headers=_bearer(made["token"]))
    assert db.get(ApiToken, made["id"]).last_used_at > first - timedelta(minutes=1)


def test_the_export_lists_tokens_without_secrets_and_clearing_sessions_revokes_them(client, db):
    user = _user(db, "ex1@test.com", "technician")
    made = _make(client, user)
    bundle = client.get("/api/v1/auth/me/export", headers=_session(user)).json()
    assert [t["id"] for t in bundle["access_tokens"]] == [made["id"]]
    assert made["token"].split("_", 2)[2] not in str(bundle)
    from app.routes.auth import revoke_tokens
    revoke_tokens(db, user.id)
    assert db.get(ApiToken, made["id"]).revoked_at is not None


def test_acts_as_admin_needs_the_admin_scope_for_a_token():
    class Req:
        class state:
            api_token = None
    admin = User(role="admin")
    assert token_access.acts_as_admin(Req, admin) is True
    Req.state.api_token = ApiToken(scope="operate")
    assert token_access.acts_as_admin(Req, admin) is False
    Req.state.api_token = ApiToken(scope="admin")
    assert token_access.acts_as_admin(Req, admin) is True
    assert token_access.acts_as_admin(Req, User(role="technician")) is False


def test_a_read_token_on_an_admin_account_cannot_list_a_service_accounts_tokens(client, db):
    admin = _user(db, "svc-list@test.com", "admin")
    service = _user(db, "svc-list-bot@test.com", "technician", is_service=True)
    read = _make(client, admin, "read")["token"]
    refused = client.get("/api/v1/auth/tokens", params={"account_id": str(service.id)}, headers=_bearer(read))
    assert refused.status_code == 403
    # a session of the same admin still can
    allowed = client.get("/api/v1/auth/tokens", params={"account_id": str(service.id)}, headers=_session(admin))
    assert allowed.status_code == 200
