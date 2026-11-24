"""
Fixes from the confirm pass: failure counting on every proof route, the email change aftermath, the
sessions routes and their absolute lifetime, the cookie paths, per-origin CORS, logging of database errors
and secrets and one-time invitations.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from passlib.context import CryptContext
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.config import Settings, settings
from app.services.keys import derive_key
from app.cors import EXPOSED_HEADERS, PerOriginCORS
from app.models.user import User
from app.models.user_session import UserSession
from app.routes.auth import _agent_label, _create_invite, create_access_token
from app.services import email_service, heavy_reads, ws_manager
from tests._shape import plain

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD = "Passw0rd!x"


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _headers(user):
    return _bearer(create_access_token({"sub": str(user.id), "role": user.role}))


def _user(db, email, role="technician", password=PASSWORD, **extra):
    u = User(name=email.split("@")[0], email=email, role=role,
             password_hash=_pwd_ctx.hash(password) if password else None, **extra)
    db.add(u)
    db.flush()
    return u


def _login(client, email, user_agent=None):
    headers = {"User-Agent": user_agent} if user_agent else {}
    res = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}, headers=headers)
    assert res.status_code == 200, res.text
    return res


def _sid(res):
    return jwt.decode(res.json()["access_token"], derive_key("access"), algorithms=[settings.algorithm])["sid"]


# ── wrong guesses count towards the lock everywhere ─────────────────────────

def test_wrong_passwords_on_change_password_lock_the_account(client, db):
    user = _user(db, "g1@test.com")
    body = {"old_password": "wrong-password", "new_password": "Changed123!"}
    codes = [client.post("/api/v1/auth/change-password", json=body, headers=_headers(user)).status_code for _ in range(6)]
    assert codes[:5] == [400] * 5 and codes[5] == 429
    db.refresh(user)
    assert user.failed_login_attempts >= 5
    # the right password is refused while this source is made to wait, so a guess cannot be confirmed by trying it
    good = {"old_password": PASSWORD, "new_password": "Changed123!"}
    assert client.post("/api/v1/auth/change-password", json=good, headers=_headers(user)).status_code == 429


def test_wrong_codes_on_two_step_disable_lock_the_account(client, db):
    secret = pyotp.random_base32()
    user = _user(db, "g2@test.com", password=None, oauth_provider="google", oauth_id="g-g2", totp_secret=secret, totp_enabled=True)
    codes = [client.post("/api/v1/auth/2fa/disable", json={"code": "000000"}, headers=_headers(user)).status_code for _ in range(6)]
    # a wrong proof is 400, never 401, so the dashboard does not treat it as an expired token and retry
    assert codes[:5] == [400] * 5 and codes[5] == 429


def test_wrong_codes_on_two_step_confirm_lock_the_account(client, db):
    user = _user(db, "g3@test.com")
    assert client.post("/api/v1/auth/2fa/enable", json={"password": PASSWORD}, headers=_headers(user)).status_code == 200
    codes = [client.post("/api/v1/auth/2fa/confirm", json={"code": "000000"}, headers=_headers(user)).status_code for _ in range(6)]
    assert codes[:5] == [400] * 5 and codes[5] == 429


def test_a_right_code_still_works_before_the_lock(client, db):
    user = _user(db, "g4@test.com")
    secret = client.post("/api/v1/auth/2fa/enable", json={"password": PASSWORD}, headers=_headers(user)).json()["secret"]
    client.post("/api/v1/auth/2fa/confirm", json={"code": "000000"}, headers=_headers(user))
    assert client.post("/api/v1/auth/2fa/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=_headers(user)).status_code == 200


def test_a_password_account_with_two_step_needs_the_code_as_well_to_delete(client, db):
    secret = pyotp.random_base32()
    user = _user(db, "g5@test.com", totp_secret=secret, totp_enabled=True)
    only_password = client.request("DELETE", "/api/v1/auth/me", json={"password": PASSWORD}, headers=_headers(user))
    assert (only_password.status_code, plain(only_password)) == (400, {"detail": "Enter a current two-step code to delete your account"})
    both = client.request("DELETE", "/api/v1/auth/me", json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()}, headers=_headers(user))
    assert both.status_code == 204


def test_changing_the_email_with_two_step_on_needs_the_code_too(client, db):
    secret = pyotp.random_base32()
    user = _user(db, "g6@test.com", totp_secret=secret, totp_enabled=True)
    res = client.patch("/api/v1/auth/me", json={"email": "g6new@test.com", "current_password": PASSWORD}, headers=_headers(user))
    assert (res.status_code, plain(res)) == (400, {"detail": "Enter a current two-step code to change your email"})


# ── changing the email ──────────────────────────────────────────────────────

@pytest.fixture
def sent(monkeypatch):
    mail = []
    monkeypatch.setattr(email_service, "send_email", lambda to, subject, text, html_body=None, reply_to=None: mail.append((to, subject, text)) or True)
    return mail


def test_changing_the_email_ends_every_other_session_and_keeps_this_one(client, db, sent):
    user = _user(db, "e1@test.com")
    mine = _login(client, "e1@test.com")
    client.cookies.clear()
    theirs = _login(client, "e1@test.com")
    res = client.patch("/api/v1/auth/me", json={"email": "e1new@test.com", "current_password": PASSWORD}, headers=_bearer(mine.json()["access_token"]))
    assert res.status_code == 200
    assert client.get("/api/v1/auth/me", headers=_bearer(mine.json()["access_token"])).status_code == 200
    # the other browser is signed out and its refresh token no longer works
    assert client.get("/api/v1/auth/me", headers=_bearer(theirs.json()["access_token"])).status_code == 401
    rows = {str(r.id): r for r in db.query(UserSession).filter(UserSession.user_id == user.id).all()}
    assert rows[_sid(mine)].revoked_at is None and rows[_sid(theirs)].revoked_at is not None


def test_the_old_address_is_told_with_the_time_and_only_a_masked_new_address(client, db, sent):
    user = _user(db, "e2@test.com")
    client.patch("/api/v1/auth/me", json={"email": "newperson@test.com", "current_password": PASSWORD}, headers=_headers(user))
    (to, subject, text), = sent
    assert to == ["e2@test.com"]
    assert "sign-in address" in subject
    assert "n***@test.com" in text and "newperson@test.com" not in text
    assert "(UTC)" in text and "support@phaemos.com" in text


def test_no_notice_when_the_email_did_not_change(client, db, sent):
    user = _user(db, "e3@test.com")
    client.patch("/api/v1/auth/me", json={"name": "Just A Name"}, headers=_headers(user))
    client.patch("/api/v1/auth/me", json={"email": "e3@test.com"}, headers=_headers(user))
    assert sent == []


def test_a_failed_notice_does_not_undo_the_change(client, db, monkeypatch):
    user = _user(db, "e4@test.com")

    def boom(*args, **kwargs):
        raise RuntimeError("vendor down")

    monkeypatch.setattr(email_service, "send_email", boom)
    res = client.patch("/api/v1/auth/me", json={"email": "e4new@test.com", "current_password": PASSWORD}, headers=_headers(user))
    assert res.status_code == 200 and res.json()["email"] == "e4new@test.com"


def test_the_address_is_masked_for_the_notice():
    assert email_service.mask_address("jane@example.com") == "j***@example.com"
    assert email_service.mask_address("nonsense") == "***"


# ── sessions: lifetime, list, end ───────────────────────────────────────────

def test_a_session_has_an_absolute_lifetime_however_often_it_is_refreshed(client, db):
    _user(db, "s1@test.com")
    res = _login(client, "s1@test.com")
    row = db.query(UserSession).filter(UserSession.id == uuid.UUID(_sid(res))).one()
    assert client.post("/api/v1/auth/refresh").status_code == 200
    # the sliding 7 days never carry it past the absolute end
    db.refresh(row)
    assert row.expires_at <= row.created_at + timedelta(days=settings.session_max_days)
    row.created_at = datetime.now(timezone.utc) - timedelta(days=settings.session_max_days, seconds=5)
    db.flush()
    assert client.post("/api/v1/auth/refresh").status_code == 401
    db.refresh(row)
    assert row.revoked_at is not None


def test_the_last_refresh_before_the_end_expires_no_later_than_the_end(client, db):
    _user(db, "s2@test.com")
    res = _login(client, "s2@test.com")
    row = db.query(UserSession).filter(UserSession.id == uuid.UUID(_sid(res))).one()
    row.created_at = datetime.now(timezone.utc) - timedelta(days=settings.session_max_days) + timedelta(days=2)
    db.flush()
    assert client.post("/api/v1/auth/refresh").status_code == 200
    db.refresh(row)
    assert row.expires_at <= row.created_at + timedelta(days=settings.session_max_days)
    assert row.expires_at - datetime.now(timezone.utc) < timedelta(days=2, minutes=1)


def test_the_session_list_shows_own_sessions_with_a_label_and_the_current_one(client, db):
    _user(db, "s3@test.com")
    mac = _login(client, "s3@test.com", "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605 Chrome/120 Safari/537")
    client.cookies.clear()
    phone = _login(client, "s3@test.com", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605 Version/17 Safari/604")
    res = client.get("/api/v1/auth/sessions", headers=_bearer(mac.json()["access_token"]))
    assert res.status_code == 200
    rows = res.json()
    assert {r["label"] for r in rows} == {"Chrome on macOS", "Safari on iOS"}
    assert {r["id"] for r in rows} == {_sid(mac), _sid(phone)}
    assert [r["id"] for r in rows if r["current"]] == [_sid(mac)]
    for row in rows:
        assert set(row) == {"id", "label", "created_at", "last_used_at", "current"}
    # no address, user agent or token is shown or stored
    assert "127.0.0.1" not in res.text and "Mozilla" not in res.text


def test_the_list_holds_only_the_callers_live_sessions(client, db):
    _user(db, "s4a@test.com")
    other = _user(db, "s4b@test.com")
    db.add(UserSession(user_id=other.id, current_jti="x", expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    res = _login(client, "s4a@test.com")
    client.post("/api/v1/auth/logout")
    rows = client.get("/api/v1/auth/sessions", headers=_bearer(res.json()["access_token"]))
    # the access token of a signed-out session is refused, so nothing is listed
    assert rows.status_code == 401
    fresh = _login(client, "s4a@test.com")
    assert [r["id"] for r in client.get("/api/v1/auth/sessions", headers=_bearer(fresh.json()["access_token"])).json()] == [_sid(fresh)]


def test_a_person_can_end_one_of_their_own_sessions(client, db):
    _user(db, "s5@test.com")
    mine = _login(client, "s5@test.com")
    client.cookies.clear()
    other = _login(client, "s5@test.com")
    res = client.delete(f"/api/v1/auth/sessions/{_sid(other)}", headers=_bearer(mine.json()["access_token"]))
    assert res.status_code == 204
    assert client.get("/api/v1/auth/me", headers=_bearer(other.json()["access_token"])).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_bearer(mine.json()["access_token"])).status_code == 200
    # ending it again is a 404 and so is one that never existed
    assert client.delete(f"/api/v1/auth/sessions/{_sid(other)}", headers=_bearer(mine.json()["access_token"])).status_code == 404
    assert client.delete(f"/api/v1/auth/sessions/{uuid.uuid4()}", headers=_bearer(mine.json()["access_token"])).status_code == 404


def test_another_persons_session_cannot_be_ended_and_looks_like_it_does_not_exist(client, db):
    _user(db, "s6a@test.com")
    victim = _user(db, "s6b@test.com")
    row = UserSession(user_id=victim.id, current_jti="x", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    db.add(row)
    db.flush()
    mine = _login(client, "s6a@test.com")
    res = client.delete(f"/api/v1/auth/sessions/{row.id}", headers=_bearer(mine.json()["access_token"]))
    assert (res.status_code, plain(res)) == (404, {"detail": "Session not found"})
    db.refresh(row)
    assert row.revoked_at is None


def test_sign_out_everywhere_else_keeps_the_caller(client, db):
    user = _user(db, "s7@test.com")
    mine = _login(client, "s7@test.com")
    client.cookies.clear()
    _login(client, "s7@test.com")
    client.cookies.clear()
    _login(client, "s7@test.com")
    res = client.post("/api/v1/auth/sessions/end-others", headers=_bearer(mine.json()["access_token"]))
    assert (res.status_code, res.json()) == (200, {"ended": 2})
    live = [r for r in db.query(UserSession).filter(UserSession.user_id == user.id).all() if r.revoked_at is None]
    assert [str(r.id) for r in live] == [_sid(mine)]


def test_the_session_routes_need_a_sign_in_and_are_rate_limited(client, db):
    assert client.get("/api/v1/auth/sessions").status_code == 401
    assert client.post("/api/v1/auth/sessions/end-others").status_code == 401
    assert client.delete(f"/api/v1/auth/sessions/{uuid.uuid4()}").status_code == 401
    user = _user(db, "s8@test.com")
    codes = [client.post("/api/v1/auth/sessions/end-others", headers=_headers(user)).status_code for _ in range(12)]
    assert 429 in codes


@pytest.mark.parametrize("agent,label", [
    ("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537 Chrome/120 Safari/537 Edg/120", "Edge on Windows"),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0", "Firefox on Linux"),
    ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537 Chrome/120 Mobile Safari/537", "Chrome on Android"),
    ("curl/8.0", "Browser"),
    (None, None),
    ("", None),
])
def test_the_label_is_coarse(agent, label):
    assert _agent_label(agent) == label


# ── the refresh cookie ──────────────────────────────────────────────────────

def test_logout_clears_every_copy_of_the_cookie(client, db):
    _user(db, "c1@test.com")
    _login(client, "c1@test.com")
    res = client.post("/api/v1/auth/logout")
    cleared = sorted(h.split("Path=")[1].split(";")[0] for h in res.headers.get_list("set-cookie") if h.startswith("refresh_token="))
    assert cleared == sorted(["/api/v1/auth", "/api/v1/auth/logout", "/api/v1/auth/refresh"])


# ── CORS with credentials for the dashboard only ────────────────────────────

def _cors_client():
    app = FastAPI()

    @app.get("/x")
    def x():
        return {"ok": True}

    app.add_middleware(
        PerOriginCORS,
        credentialed=["https://app.example.com"],
        others=["https://app.example.com", "https://www.example.com"],
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"], expose_headers=EXPOSED_HEADERS,
    )
    return TestClient(app)


def test_the_dashboard_origin_gets_credentials():
    res = _cors_client().get("/x", headers={"Origin": "https://app.example.com"})
    assert res.headers["access-control-allow-origin"] == "https://app.example.com"
    assert res.headers["access-control-allow-credentials"] == "true"
    assert "x-total-count" in res.headers["access-control-expose-headers"].lower()


def test_the_public_site_origin_gets_cors_without_credentials():
    res = _cors_client().get("/x", headers={"Origin": "https://www.example.com"})
    assert res.headers["access-control-allow-origin"] == "https://www.example.com"
    assert "access-control-allow-credentials" not in res.headers
    pre = _cors_client().options("/x", headers={"Origin": "https://www.example.com", "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 200 and "access-control-allow-credentials" not in pre.headers


def test_an_unknown_origin_gets_nothing():
    res = _cors_client().get("/x", headers={"Origin": "https://evil.example.net"})
    assert "access-control-allow-origin" not in res.headers


def test_the_first_allowed_origin_is_the_credentialed_one_unless_set(monkeypatch):
    monkeypatch.setattr(settings, "allowed_origins", "https://app.example.com, https://www.example.com")
    monkeypatch.setattr(settings, "credentialed_origins", "")
    assert settings.credentialed_origin_list == ["https://app.example.com"]
    monkeypatch.setattr(settings, "credentialed_origins", "https://a.example.com,https://b.example.com")
    assert settings.credentialed_origin_list == ["https://a.example.com", "https://b.example.com"]


# ── what reaches the log ────────────────────────────────────────────────────

def test_the_engine_hides_statement_parameters():
    from app.db import engine
    assert engine.hide_parameters is True


def test_a_failed_statement_logs_its_kind_and_never_its_values(caplog):
    from app import errors

    class FakePg(Exception):
        pgcode = "23505"

    app = FastAPI()
    errors.install(app)

    @app.get("/boom")
    def boom():
        raise IntegrityError("INSERT INTO users (email) VALUES (%(e)s)", {"e": "someone@example.com"}, FakePg("Key (email)=(someone@example.com) already exists."))

    with caplog.at_level(logging.ERROR, logger="app.errors"):
        res = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert res.status_code == 500 and res.json()["code"] == "database_error" and set(res.json()) == {"code", "detail", "request_id"}
    assert "someone@example.com" not in caplog.text and "already exists" not in caplog.text
    assert "FakePg" in caplog.text and "23505" in caplog.text and "/boom" in caplog.text


def test_a_refused_start_names_the_setting_and_never_part_of_its_value():
    weak = "tinykey-value-9f3"
    with pytest.raises(ValidationError) as refused:
        Settings(_env_file=None, database_url="postgresql://user:dbpassword99@db/x", secret_key=weak, environment="production")
    text = str(refused.value)
    assert "SECRET_KEY must be a random value" in text
    assert weak not in text and "dbpassword99" not in text


# ── invitations are one time ────────────────────────────────────────────────

def test_an_invitation_cannot_be_used_twice_even_after_the_account_is_deleted(client, db):
    token = _create_invite(db, "once@test.com", "admin")
    body = {"token": token, "name": "Once", "password": PASSWORD}
    first = client.post("/api/v1/auth/accept-invite", json=body)
    assert first.status_code == 201 and first.json()["role"] == "admin"
    # the account is deleted inside the 48 hours. The same link must not make another one
    user = db.query(User).filter(User.email == "once@test.com").one()
    _user(db, "keeper@test.com", "admin")
    db.delete(user)
    db.flush()
    again = client.post("/api/v1/auth/accept-invite", json=body)
    assert (again.status_code, plain(again)) == (400, {"detail": "This invitation has already been used"})
    assert db.query(User).filter(User.email == "once@test.com").first() is None


def test_an_invitation_name_over_the_column_is_a_422_not_a_500(client, db):
    token = _create_invite(db, "long@test.com", "viewer")
    res = client.post("/api/v1/auth/accept-invite", json={"token": token, "name": "n" * 101, "password": PASSWORD})
    assert res.status_code == 422


# ── small ───────────────────────────────────────────────────────────────────

def test_lengths_that_overflowed_a_column_are_refused(client, db):
    admin = _user(db, "l1@test.com", "admin")
    base = {"device_id": str(uuid.uuid4()), "condition": "gt", "threshold": 1.0, "severity": "warning"}
    assert client.post("/api/v1/alert-rules", json={**base, "metric": "m" * 51}, headers=_headers(admin)).status_code == 422
    assert client.post("/api/v1/webhooks", json={"password": PASSWORD, "name": "w" * 201, "url": "https://8.8.8.8/x"}, headers=_headers(admin)).status_code == 422


def test_a_refused_heavy_read_leaves_no_slot_entry(monkeypatch):
    heavy_reads.reset()
    monkeypatch.setitem(heavy_reads.RATES, "export", 0)
    with pytest.raises(Exception):
        with heavy_reads.heavy_read("nobody", "export"):
            pass
    assert "nobody" not in heavy_reads._running_by_user


def test_a_socket_that_cannot_keep_up_is_closed_so_it_reconnects(monkeypatch):
    closed = []

    class Slow:
        async def send_text(self, data):
            await asyncio.sleep(10)

        async def close(self, code=1000):
            closed.append(code)

    monkeypatch.setattr(ws_manager, "_SEND_SECONDS", 0.05)
    slow = Slow()
    ws_manager.subscribe("dev-slow", slow)
    asyncio.run(ws_manager.broadcast("dev-slow", "{}"))
    assert closed == [1013]
    assert slow not in ws_manager._connections["dev-slow"]
