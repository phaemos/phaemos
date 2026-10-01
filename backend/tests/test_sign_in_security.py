import secrets

import pyotp
import pytest
from passlib.context import CryptContext
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.models.device import Device
from app.models.user import User
from app.routes.auth import (
    _identity, _oauth_finish, create_access_token, create_challenge_token, create_refresh_token,
)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_PASSWORD = "Secret123!"


def _user(db, email, role="viewer", totp=False):
    user = User(name="Test", email=email, password_hash=_pwd.hash(_PASSWORD), role=role)
    if totp:
        user.totp_secret = pyotp.random_base32()
        user.totp_enabled = True
    db.add(user)
    db.flush()
    return user


def _bearer(user):
    return {"Authorization": f"Bearer {create_access_token(_identity(user))}"}


def _login(client, email, password=_PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


# ── password sign-in with two-factor authentication ───────────────────────────

def test_password_alone_does_not_sign_in_a_2fa_account(client, db):
    _user(db, "mfa1@example.com", totp=True)
    res = _login(client, "mfa1@example.com")
    assert res.status_code == 200
    body = res.json()
    assert body["mfa_required"] is True
    assert body["mfa_token"]
    assert body["access_token"] is None
    assert "refresh_token" not in res.cookies


def test_challenge_and_code_complete_sign_in(client, db):
    user = _user(db, "mfa2@example.com", totp=True)
    challenge = _login(client, "mfa2@example.com").json()["mfa_token"]
    code = pyotp.TOTP(user.totp_secret).now()
    res = client.post("/api/v1/auth/2fa/verify", json={"mfa_token": challenge, "code": code})
    assert res.status_code == 200
    assert "refresh_token" in res.cookies
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "mfa2@example.com"


def test_code_without_a_challenge_is_refused(client, db):
    user = _user(db, "mfa3@example.com", totp=True)
    code = pyotp.TOTP(user.totp_secret).now()
    assert client.post("/api/v1/auth/2fa/verify", json={"code": code}).status_code == 401
    # the old query-string form named the user directly and must not work.
    old = client.post(f"/api/v1/auth/2fa/verify?code={code}&user_id={user.id}")
    assert old.status_code in (401, 422)


def test_a_code_is_accepted_only_once(client, db):
    user = _user(db, "mfa4@example.com", totp=True)
    code = pyotp.TOTP(user.totp_secret).now()
    first = _login(client, "mfa4@example.com").json()["mfa_token"]
    assert client.post("/api/v1/auth/2fa/verify", json={"mfa_token": first, "code": code}).status_code == 200
    second = _login(client, "mfa4@example.com").json()["mfa_token"]
    assert client.post("/api/v1/auth/2fa/verify", json={"mfa_token": second, "code": code}).status_code == 401


def test_wrong_codes_lock_the_account(client, db):
    _user(db, "mfa5@example.com", totp=True)
    challenge = _login(client, "mfa5@example.com").json()["mfa_token"]
    for _ in range(5):
        res = client.post("/api/v1/auth/2fa/verify", json={"mfa_token": challenge, "code": "000000"})
        assert res.status_code == 401
    res = client.post("/api/v1/auth/2fa/verify", json={"mfa_token": challenge, "code": "000000"})
    assert res.status_code == 429


# ── token types and sessions ──────────────────────────────────────────────────

def test_only_access_tokens_reach_protected_routes(client, db):
    user = _user(db, "types@example.com")
    for token in (create_refresh_token(_identity(user)), create_challenge_token(_identity(user))):
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401


def test_refresh_needs_a_refresh_token(client, db):
    user = _user(db, "refresh@example.com")
    client.cookies.set("refresh_token", create_access_token(_identity(user)))
    assert client.post("/api/v1/auth/refresh").status_code == 401
    client.cookies.clear()


def test_password_change_ends_other_sessions(client, db):
    user = _user(db, "pw@example.com")
    old = _bearer(user)
    res = client.post(
        "/api/v1/auth/change-password",
        json={"old_password": _PASSWORD, "new_password": "Changed123!"},
        headers=old,
    )
    assert res.status_code == 204
    assert "refresh_token" in res.cookies
    assert client.get("/api/v1/auth/me", headers=old).status_code == 401


def test_password_check_handles_oauth_only_accounts(client, db):
    user = User(name="OAuth", email="oauth-only@example.com", password_hash=None)
    db.add(user)
    db.flush()
    assert _login(client, "oauth-only@example.com", "Anything123").status_code == 401


# ── enrolment ─────────────────────────────────────────────────────────────────

def test_enable_is_refused_while_2fa_is_on(client, db):
    user = _user(db, "enrol1@example.com", totp=True)
    res = client.post("/api/v1/auth/2fa/enable", headers=_bearer(user))
    assert res.status_code == 409
    db.refresh(user)
    assert user.totp_enabled is True


def test_confirming_2fa_ends_other_sessions(client, db):
    user = _user(db, "enrol2@example.com")
    old = _bearer(user)
    secret = client.post("/api/v1/auth/2fa/enable", headers=old).json()["secret"]
    res = client.post(f"/api/v1/auth/2fa/confirm?code={pyotp.TOTP(secret).now()}", headers=old)
    assert res.status_code == 200
    fresh = {"Authorization": f"Bearer {res.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=old).status_code == 401
    assert client.get("/api/v1/auth/me", headers=fresh).status_code == 200


# ── OAuth ─────────────────────────────────────────────────────────────────────

def test_oauth_start_sets_a_state(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client")
    res = client.get("/api/v1/auth/google", follow_redirects=False)
    assert res.status_code in (302, 307)
    state = res.cookies.get("oauth_state")
    assert state and f"state={state}" in res.headers["location"]


@pytest.mark.parametrize("provider", ["google", "github"])
def test_oauth_callback_needs_the_matching_state(client, monkeypatch, provider):
    monkeypatch.setattr(settings, f"{provider}_client_id", "test-client")
    client.cookies.set("oauth_state", "expected", path="/api/v1/auth")
    for query in ("code=x", "code=x&state=forged"):
        res = client.get(f"/api/v1/auth/{provider}/callback?{query}", follow_redirects=False)
        assert res.status_code == 400
    client.cookies.clear()


def test_oauth_never_puts_a_token_in_the_url(db):
    user = _user(db, "oauth1@example.com")
    res = _oauth_finish(db, user)
    assert "token" not in res.headers["location"].split("?", 1)[-1].replace("step=oauth", "")
    assert "refresh_token=" in res.headers.get("set-cookie", "")


def test_oauth_sign_in_still_asks_for_the_code(db):
    user = _user(db, "oauth2@example.com", totp=True)
    res = _oauth_finish(db, user)
    assert res.headers["location"].endswith("/login?step=mfa")
    cookies = res.headers.get("set-cookie", "")
    assert "signin_challenge=" in cookies
    assert "refresh_token=" not in cookies


# ── WebSocket ─────────────────────────────────────────────────────────────────

def test_websocket_refuses_tokens_that_are_not_access_tokens(client, db):
    user = _user(db, "ws@example.com")
    device = Device(name="WS", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32))
    db.add(device)
    db.flush()
    for token in (create_refresh_token(_identity(user)), create_challenge_token(_identity(user))):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/telemetry/{device.id}?token={token}") as ws:
                ws.receive_text()


# ── device permissions ────────────────────────────────────────────────────────

def _device(db, owner=None):
    device = Device(name="Node", location="Lab", type="esp32",
                    api_key=secrets.token_urlsafe(32), owner_id=owner.id if owner else None)
    db.add(device)
    db.flush()
    return device


def test_viewers_cannot_change_devices_or_see_keys(client, db):
    viewer = _user(db, "viewer@example.com")
    device = _device(db)
    headers = _bearer(viewer)
    assert client.post(f"/api/v1/devices/{device.id}/rotate-key", headers=headers).status_code == 403
    assert client.patch(f"/api/v1/devices/{device.id}", json={"name": "X"}, headers=headers).status_code == 403
    assert client.delete(f"/api/v1/devices/{device.id}", headers=headers).status_code == 403


def test_technicians_manage_only_their_own_devices(client, db):
    tech = _user(db, "tech@example.com", role="technician")
    other = _user(db, "other@example.com", role="technician")
    mine, theirs = _device(db, tech), _device(db, other)
    headers = _bearer(tech)
    assert client.post(f"/api/v1/devices/{mine.id}/rotate-key", headers=headers).status_code == 200
    assert client.post(f"/api/v1/devices/{theirs.id}/rotate-key", headers=headers).status_code == 403
    assert client.delete(f"/api/v1/devices/{mine.id}", headers=headers).status_code == 403


def test_admins_can_delete_devices(client, db):
    admin = _user(db, "admin2@example.com", role="admin")
    device = _device(db)
    assert client.delete(f"/api/v1/devices/{device.id}", headers=_bearer(admin)).status_code == 204


# ── rate limits ───────────────────────────────────────────────────────────────

def test_spoofed_proxy_headers_do_not_escape_the_sign_in_limit(client, db):
    _user(db, "limit@example.com")
    codes = []
    for n in range(6):
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "limit@example.com", "password": "Wrong123!"},
            headers={"X-Real-IP": f"203.0.113.{n}", "X-Forwarded-For": f"198.51.100.{n}"},
        )
        codes.append(res.status_code)
    # the test client is not a trusted proxy, so every request shares one bucket.
    assert 429 in codes
