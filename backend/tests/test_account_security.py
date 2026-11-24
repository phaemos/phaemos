"""
Fixes from the attacker's-eye security audit: failing closed, the lockout redesign, sign-in answers that do not give an
address away, invitations in a table, a key for each purpose, admin control of accounts, fresh proof for dangerous admin
actions and two-step secrets encrypted at rest.
"""

import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pyotp
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from passlib.context import CryptContext
from pydantic import ValidationError
from sqlalchemy import event, text
from starlette.requests import Request

from app.config import DEVELOPMENT_ONLY, Settings, settings
from app.limiter import _real_ip
from app.models.invitation import Invitation
from app.models.user import User
from app.models.user_session import UserSession
from app.routes import auth as auth_module
from app.routes.auth import _create_invite, create_access_token, decode_token, verify_password
from app.services import email_service, signin_guard, two_step_secrets
from app.services.keys import PURPOSES, derive_key
from tests._shape import plain

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD = "Passw0rd!x"
REPO = Path(__file__).resolve().parents[2]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _headers(user, sid=None):
    claims = {"sub": str(user.id), "role": user.role}
    if sid:
        claims["sid"] = sid
    return _bearer(create_access_token(claims))


def _user(db, email, role="technician", password=PASSWORD, **extra):
    u = User(name=email.split("@")[0], email=email, role=role,
             password_hash=_pwd_ctx.hash(password) if password else None, **extra)
    db.add(u)
    db.flush()
    return u


def _strong_key():
    return secrets.token_hex(32)


def _settings(**values):
    return Settings(_env_file=None, database_url=values.pop("database_url", "postgresql://u:p@db:5432/x"), **values)


class _Clock:
    now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def no_address_rate_limit(monkeypatch):
    # the per-address limit (5 sign-ins a minute) runs on the real clock and would answer before the guard these tests are
    # about. It is covered by its own tests
    from app.limiter import limiter
    monkeypatch.setattr(limiter, "enabled", False)


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(signin_guard, "_now", clock)
    return clock


# ── M1 and M2: fail closed ──────────────────────────────────────────────────

def test_an_unset_environment_is_production(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    s = _settings(secret_key=_strong_key())
    assert s.environment == "production" and not s.is_development


@pytest.mark.parametrize("value", ["", "  ", "dev", "Dev", "develop", "local", "test", "staging", "prod", "production", "1"])
def test_only_the_word_development_is_development(value):
    assert not _settings(secret_key=_strong_key(), environment=value).is_development


def test_development_must_be_stated():
    s = _settings(secret_key="short", environment=" Development ")
    assert s.is_development


@pytest.mark.parametrize("host,allowed", [
    ("localhost", True), ("127.0.0.1", True), ("db", True), ("host.docker.internal", True),
    ("db.example.com", False), ("203.0.113.9", False), ("prod-db.internal.example", False),
])
def test_development_runs_only_against_a_database_on_this_machine(host, allowed):
    url = f"postgresql://u:p@{host}:5432/x"
    if allowed:
        assert _settings(secret_key="short", environment="development", database_url=url).is_development
    else:
        with pytest.raises(ValidationError, match="ENVIRONMENT=development is only allowed"):
            _settings(secret_key="short", environment="development", database_url=url)


def test_every_relaxation_development_allows_is_listed_in_one_place():
    text_ = "\n".join(DEVELOPMENT_ONLY).lower()
    for word in ("registration", "docs", "secure", "http webhook", "turnstile", "secret_key", "token=", "demo", "database"):
        assert word in text_


def test_the_start_up_log_says_which_mode_this_is(caplog, monkeypatch):
    from app.main import _log_how_we_are_running
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "trusted_proxies", "")
    with caplog.at_level(logging.WARNING, logger="app.startup"):
        _log_how_we_are_running()
    assert "environment: production" in caplog.text
    assert "forwarded headers: none: forwarded headers are ignored" in caplog.text
    assert "development allows" not in caplog.text
    caplog.clear()
    monkeypatch.setattr(settings, "environment", "development")
    with caplog.at_level(logging.WARNING, logger="app.startup"):
        _log_how_we_are_running()
    assert "DEVELOPMENT (security controls are relaxed)" in caplog.text
    assert "development allows: open registration" in caplog.text


def test_trusted_proxies_default_to_none(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    s = _settings(secret_key=_strong_key())
    assert s.trusted_proxies == "" and s.trusted_proxy_networks == []
    mode, warning = s.proxy_mode()
    assert mode.startswith("none") and warning is None


def test_a_wide_private_range_in_production_is_warned_about():
    s = _settings(secret_key=_strong_key(), environment="production", trusted_proxies="10.0.0.0/8,172.29.0.1/32")
    mode, warning = s.proxy_mode()
    assert "trusting X-Real-IP from 10.0.0.0/8, 172.29.0.1/32" in mode
    assert "10.0.0.0/8" in warning and "wide private range" in warning
    one = _settings(secret_key=_strong_key(), environment="production", trusted_proxies="172.29.0.1/32")
    assert one.proxy_mode()[1] is None


def _request(peer, real_ip=None):
    headers = [(b"x-real-ip", real_ip.encode())] if real_ip else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234), "method": "GET", "path": "/"})


def test_with_no_trusted_proxy_a_forwarded_header_is_ignored_everywhere(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "")
    # the rate limit key, the sign-in source and the socket address are all the peer, whatever the header says
    assert _real_ip(_request("10.0.0.5", "198.51.100.1")) == "10.0.0.5"
    assert _real_ip(_request("127.0.0.1", "198.51.100.1")) == "127.0.0.1"
    from app.middleware import _client_source
    assert _client_source({"client": ("10.0.0.5", 1), "headers": [(b"x-real-ip", b"198.51.100.1")]}) == "10.0.0.5"
    from app.routes.ws import _client_address

    class Fake:
        client = type("C", (), {"host": "10.0.0.5"})()
        headers = {"x-real-ip": "198.51.100.1"}

    assert _client_address(Fake()) == "10.0.0.5"


def test_a_trusted_proxy_is_believed_and_nobody_else(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "172.29.0.1/32")
    assert _real_ip(_request("172.29.0.1", "198.51.100.1")) == "198.51.100.1"
    assert _real_ip(_request("172.29.0.2", "198.51.100.1")) == "172.29.0.2"


def test_a_session_id_is_always_required_outside_development(monkeypatch):
    # the suite turns the rule off through the environment, so start from the default
    monkeypatch.delenv("REQUIRE_SESSION_ID", raising=False)
    assert _settings(secret_key=_strong_key(), environment="production", require_session_id=False).session_id_required is True
    assert _settings(secret_key="short", environment="development", require_session_id=False).session_id_required is False
    assert _settings(secret_key="short", environment="development").session_id_required is True


# ── H5: a stranger cannot lock anyone out ───────────────────────────────────

def _app_client(db, peer="127.0.0.1"):
    from app.db import get_db
    from app.main import app
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, client=(peer, 5000))


def _login(client, email, password, source):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}, headers={"X-Real-IP": source})


def _attack(client, email, sources, tries=5):
    results = []
    for source in sources:
        for _ in range(tries):
            results.append(_login(client, email, "wrong-password", source))
    return results


SOURCES = [f"198.51.100.{n}" for n in range(1, 13)]


def test_the_delay_grows_with_failures_and_stops_at_a_ceiling():
    delays = [signin_guard._delay_for(n) for n in range(1, 12)]
    assert delays[:4] == [0, 0, 0, 0]
    assert delays[4:9] == [30, 60, 120, 240, 480]
    assert max(delays) == signin_guard.PAIR_MAX_DELAY == 900


def test_five_wrong_passwords_delay_that_source_only_and_never_lock_the_account(client, db, clock):
    user = _user(db, "h5a@test.com")
    me = _app_client(db)
    first = [_login(me, "h5a@test.com", "wrong-password", "198.51.100.1").status_code for _ in range(5)]
    assert first == [401] * 5
    blocked = _login(me, "h5a@test.com", PASSWORD, "198.51.100.1")
    # even the right password waits from the source that has just failed five times
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) <= 30
    # another source is not affected at all
    assert _login(me, "h5a@test.com", PASSWORD, "203.0.113.77").status_code == 200
    db.refresh(user)
    assert user.locked_until is None
    # and the delayed source gets in once the wait is over
    clock.now += 31
    assert _login(me, "h5a@test.com", PASSWORD, "198.51.100.1").status_code == 200


def test_the_attack_then_the_real_admin_signs_in(client, db, clock, monkeypatch):
    # many addresses, many tries, against an admin account: the admin is never slowed by strangers
    notices = []
    monkeypatch.setattr(email_service, "send_signin_attempts_notice", lambda to: notices.append(to) or True)
    admin = _user(db, "h5-admin@test.com", "admin")
    attacker = _app_client(db)
    results = _attack(attacker, "h5-admin@test.com", SOURCES)
    assert {r.status_code for r in results} <= {401, 429}
    key = signin_guard.account_key(user_id=admin.id)
    assert (signin_guard.store.get(f"acct:{key}") or 0) >= signin_guard.ACCOUNT_THRESHOLD
    owner = _app_client(db)
    res = _login(owner, "h5-admin@test.com", PASSWORD, "203.0.113.50")
    assert res.status_code == 200 and res.json()["access_token"]
    db.refresh(admin)
    assert admin.locked_until is None
    # the owner was told once, not once for each attempt
    assert notices == ["h5-admin@test.com"]


def test_the_attack_then_a_browser_that_signed_in_before_gets_through(client, db, clock):
    user = _user(db, "h5-known@test.com")
    owner = _app_client(db)
    # the owner has signed in from this browser before, which leaves a signed cookie for this account
    assert _login(owner, "h5-known@test.com", PASSWORD, "203.0.113.60").status_code == 200
    attacker = _app_client(db)
    _attack(attacker, "h5-known@test.com", SOURCES)
    key = signin_guard.account_key(user_id=user.id)
    assert (signin_guard.store.get(f"acct:{key}") or 0) >= signin_guard.ACCOUNT_THRESHOLD
    # a stranger's attempt from a new address is made to wait, because the account is being guessed at
    stranger = _login(attacker, "h5-known@test.com", PASSWORD, "203.0.113.99")
    assert stranger.status_code == 429 and stranger.headers["Retry-After"] == str(signin_guard.ACCOUNT_SLOT)
    # the owner's browser carries the cookie, so it is not slowed, even from a new address
    res = _login(owner, "h5-known@test.com", PASSWORD, "203.0.113.61")
    assert res.status_code == 200


def test_the_attack_then_an_owner_on_a_new_browser_gets_in_after_a_short_wait(client, db, clock):
    _user(db, "h5-new@test.com")
    attacker = _app_client(db)
    _attack(attacker, "h5-new@test.com", SOURCES)
    owner = _app_client(db)
    waiting = _login(owner, "h5-new@test.com", PASSWORD, "203.0.113.70")
    assert waiting.status_code == 429
    clock.now += signin_guard.ACCOUNT_SLOT + 1
    assert _login(owner, "h5-new@test.com", PASSWORD, "203.0.113.70").status_code == 200


def test_the_cookie_of_another_account_does_not_help(client, db, clock):
    _user(db, "h5-a@test.com")
    _user(db, "h5-b@test.com")
    mine = _app_client(db)
    _login(mine, "h5-b@test.com", PASSWORD, "203.0.113.80")
    _attack(_app_client(db), "h5-a@test.com", SOURCES)
    # a cookie for b is no use against a
    assert _login(mine, "h5-a@test.com", PASSWORD, "203.0.113.81").status_code == 429


def test_an_unknown_address_is_counted_exactly_like_a_known_one(client, db, clock):
    _user(db, "h5-real@test.com")
    me = _app_client(db)
    known = [_login(me, "h5-real@test.com", "wrong-password", "198.51.100.5") for _ in range(6)]
    unknown = [_login(me, "h5-nobody@test.com", "wrong-password", "198.51.100.6") for _ in range(6)]
    assert [r.status_code for r in known] == [r.status_code for r in unknown] == [401] * 5 + [429]
    assert known[5].json()["detail"].replace("h5-real", "") == unknown[5].json()["detail"].replace("h5-nobody", "")
    assert known[5].headers["Retry-After"] == unknown[5].headers["Retry-After"]
    assert plain(known[0]) == plain(unknown[0]) == {"detail": "Invalid credentials"}


def test_unknown_addresses_are_slowed_account_wide_too_so_the_slowdown_is_not_an_oracle(client, db, clock):
    me = _app_client(db)
    _attack(me, "h5-ghost@test.com", SOURCES)
    stranger = _login(me, "h5-ghost@test.com", "wrong-password", "203.0.113.90")
    assert stranger.status_code == 429


def test_a_two_step_code_wrong_many_times_slows_the_source_and_not_the_account(client, db, clock):
    secret = pyotp.random_base32()
    user = _user(db, "h5-2fa@test.com", totp_secret=secret, totp_enabled=True)
    me = _app_client(db)
    challenge = _login(me, "h5-2fa@test.com", PASSWORD, "203.0.113.1").json()["mfa_token"]
    for _ in range(5):
        assert me.post("/api/v1/auth/2fa/verify", json={"mfa_token": challenge, "code": "000000"}, headers={"X-Real-IP": "198.51.100.2"}).status_code == 401
    assert me.post("/api/v1/auth/2fa/verify", json={"mfa_token": challenge, "code": "000000"}, headers={"X-Real-IP": "198.51.100.2"}).status_code == 429
    ok = me.post("/api/v1/auth/2fa/verify", json={"mfa_token": challenge, "code": pyotp.TOTP(secret).now()}, headers={"X-Real-IP": "203.0.113.2"})
    assert ok.status_code == 200
    db.refresh(user)
    assert user.locked_until is None


def test_a_right_password_clears_the_count_for_that_source(client, db, clock):
    _user(db, "h5-clear@test.com")
    me = _app_client(db)
    for _ in range(3):
        _login(me, "h5-clear@test.com", "wrong-password", "198.51.100.9")
    assert _login(me, "h5-clear@test.com", PASSWORD, "198.51.100.9").status_code == 200
    for _ in range(4):
        assert _login(me, "h5-clear@test.com", "wrong-password", "198.51.100.9").status_code == 401


def test_the_owner_is_told_at_most_once_a_day(db, clock, monkeypatch):
    sent = []
    monkeypatch.setattr(email_service, "send_signin_attempts_notice", lambda to: sent.append(to) or True)
    user = _user(db, "h5-notice@test.com")
    for _ in range(signin_guard.ACCOUNT_THRESHOLD + 20):
        auth_module._record_failure(db, user)
    assert sent == ["h5-notice@test.com"]
    clock.now += 25 * 3600
    for _ in range(signin_guard.ACCOUNT_THRESHOLD):
        auth_module._record_failure(db, user)
    assert sent == ["h5-notice@test.com", "h5-notice@test.com"]


def test_what_a_stranger_with_many_addresses_can_still_do_is_one_try_per_slot(client, db, clock):
    # past the threshold every try from an unknown browser takes the single slot, so guessing is limited to one in ten seconds
    _user(db, "h5-many@test.com")
    me = _app_client(db)
    _attack(me, "h5-many@test.com", SOURCES)
    passed = 0
    for n in range(30):
        res = _login(me, "h5-many@test.com", "wrong-password", f"192.0.2.{n + 1}")
        passed += res.status_code == 401
        clock.now += 1
    assert passed <= 4


def test_the_guard_works_without_redis(monkeypatch):
    monkeypatch.setattr(signin_guard, "memory_only", False)
    monkeypatch.setattr(signin_guard, "_redis", None)
    monkeypatch.setattr(signin_guard, "_redis_down_until", 0.0)
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1")
    signin_guard.reset()
    key = signin_guard.account_key(email="nobody@test.com")
    for _ in range(5):
        signin_guard.record_failure(key, source="s")
    with pytest.raises(HTTPException) as slow:
        signin_guard.check(key, source="s")
    assert slow.value.status_code == 429


# ── M3: nothing in the answer, status or work tells a known address from an unknown one ──

def test_sign_in_does_one_password_check_for_every_kind_of_address(client, db, monkeypatch):
    calls = []
    real = auth_module.verify_password

    def spy(plain, hashed):
        calls.append(hashed)
        return real(plain, hashed)

    monkeypatch.setattr(auth_module, "verify_password", spy)
    _user(db, "m3-known@test.com")
    _user(db, "m3-provider@test.com", password=None, oauth_provider="github", oauth_id="gh-m3")
    inactive = _user(db, "m3-off@test.com", is_active=False)
    for email in ("m3-known@test.com", "m3-nobody@test.com", "m3-provider@test.com", "m3-off@test.com"):
        calls.clear()
        res = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
        assert (res.status_code, plain(res)) == (401, {"detail": "Invalid credentials"})
        assert len(calls) == 1, email
    # an unknown address is checked against the dummy hash, which is a real bcrypt hash
    calls.clear()
    client.post("/api/v1/auth/login", json={"email": "m3-nobody@test.com", "password": "x"})
    assert calls == [auth_module._DUMMY_HASH]
    # even the right password for a deactivated account is the same answer
    assert plain(client.post("/api/v1/auth/login", json={"email": "m3-off@test.com", "password": PASSWORD})) == {"detail": "Invalid credentials"}
    assert inactive.is_active is False


def test_a_nul_byte_in_a_password_is_a_422_for_every_address(client, db):
    _user(db, "m3-nul@test.com")
    for email in ("m3-nul@test.com", "m3-nobody@test.com"):
        res = client.post("/api/v1/auth/login", json={"email": email, "password": "abc\u0000def"})
        assert res.status_code == 422, email


def test_verify_password_treats_a_bad_input_as_a_wrong_password():
    assert verify_password("abc\u0000", auth_module.hash_password("Passw0rd!x")) is False
    assert verify_password("x", "not-a-hash") is False
    assert verify_password("x", None) is False


@pytest.mark.parametrize("path,body", [
    ("/api/v1/auth/register", {"name": "a\u0000b", "email": "nul1@test.com", "password": PASSWORD}),
    ("/api/v1/auth/register", {"name": "ok", "email": "nul2@test.com", "password": "Passw0rd!\u0000"}),
    ("/api/v1/auth/accept-invite", {"token": "t\u0000", "name": "n", "password": PASSWORD}),
    ("/api/v1/contact", {"name": "a\u0000b", "email": "x@test.com", "subject": "s", "message": "m"}),
])
def test_text_with_a_nul_character_is_refused_before_it_reaches_the_database(client, path, body):
    res = client.post(path, json=body)
    assert res.status_code == 422
    assert plain(res) == {"detail": "Text must not contain NUL characters"}


def test_nul_is_refused_in_tickets_labels_and_the_query_string(client, db):
    admin = _user(db, "m3-admin@test.com", "admin")
    h = _headers(admin)
    assert client.post("/api/v1/tickets", json={"title": "a\u0000b"}, headers=h).status_code == 422
    assert client.post("/api/v1/tickets", content='{"title": "x", "description": "\\u0000"}', headers={**h, "Content-Type": "application/json"}).status_code == 422
    assert client.get("/api/v1/tickets?status=%00", headers=h).status_code == 422
    # the same request without it is fine and a body that really needs a backslash is not harmed
    assert client.post("/api/v1/tickets", json={"title": "a b", "description": "path C:\\temp"}, headers=h).status_code == 201


def test_a_login_by_email_is_not_case_sensitive_and_only_one_account_per_mailbox(client, db):
    _user(db, "case@test.com")
    assert client.post("/api/v1/auth/login", json={"email": "CASE@Test.com", "password": PASSWORD}).status_code == 200
    again = client.post("/api/v1/auth/register", json={"name": "Twin", "email": "Case@test.COM", "password": PASSWORD})
    assert again.status_code == 400
    assert client.post("/api/v1/auth/register", json={"name": "Mixed", "email": "Mixed.Case@Test.com", "password": PASSWORD}).status_code == 201
    assert db.query(User).filter(User.email == "mixed.case@test.com").count() == 1


def test_common_passwords_are_refused(client):
    for pw in ("Password1", "Passw0rd", "Admin1234", "Changeme"):
        res = client.post("/api/v1/auth/register", json={"name": "x", "email": f"{pw}@test.com", "password": pw})
        # some of these fail an older rule first. All are refused
        assert res.status_code == 422, pw
    assert client.post("/api/v1/auth/register", json={"name": "x", "email": "uncommon@test.com", "password": "Tr1cky-Tree-9"}).status_code == 201


# ── M4: keys, session ids, invitations ──────────────────────────────────────

def test_every_purpose_has_its_own_stable_key():
    keys = {p: derive_key(p) for p in PURPOSES}
    assert len(set(keys.values())) == len(PURPOSES)
    assert all(len(k) == 32 for k in keys.values())
    assert derive_key("access") == keys["access"]
    assert derive_key("access") != settings.secret_key.encode()
    with pytest.raises(ValueError):
        derive_key("not-a-purpose")
    with pytest.raises(ValueError):
        derive_key("access", previous=True)   # no previous key is set


def test_the_purposes_the_other_builders_need_exist():
    for purpose in ("model_file", "audit_export", "two_step_secret"):
        assert purpose in PURPOSES


def test_a_token_signed_for_another_purpose_is_refused(client, db):
    user = _user(db, "k1@test.com")
    claims = {"sub": str(user.id), "role": "admin", "type": "access", "ver": 0, "sid": str(uuid.uuid4()),
              "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    for purpose in ("refresh", "reset", "challenge"):
        forged = jwt.encode(claims, derive_key(purpose), algorithm="HS256")
        assert client.get("/api/v1/auth/me", headers=_bearer(forged)).status_code == 401
    # a token signed with the raw secret, as before this change, is refused too
    assert client.get("/api/v1/auth/me", headers=_bearer(jwt.encode(claims, settings.secret_key, algorithm="HS256"))).status_code == 401


def test_a_rotated_key_still_verifies_what_the_old_key_signed_and_signs_nothing_with_the_old_one(monkeypatch):
    old = settings.secret_key
    token = create_access_token({"sub": str(uuid.uuid4()), "role": "viewer"})
    monkeypatch.setattr(settings, "secret_key", _strong_key())
    monkeypatch.setattr(settings, "secret_key_previous", old)
    assert decode_token(token)["role"] == "viewer"
    fresh = create_access_token({"sub": str(uuid.uuid4()), "role": "viewer"})
    # the new token is not accepted under the old key alone
    with pytest.raises(jwt.InvalidTokenError):
        jwt.decode(fresh, derive_key("access", previous=True), algorithms=["HS256"])
    # and with the previous key removed, the old token stops working
    monkeypatch.setattr(settings, "secret_key_previous", "")
    with pytest.raises(HTTPException):
        decode_token(token)


def test_an_access_token_with_no_session_id_is_refused_when_the_rule_is_on(client, db, monkeypatch):
    user = _user(db, "k2@test.com")
    monkeypatch.setattr(settings, "require_session_id", True)
    assert client.get("/api/v1/auth/me", headers=_headers(user)).status_code == 401
    row = UserSession(user_id=user.id, current_jti="j", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    db.add(row)
    db.flush()
    assert client.get("/api/v1/auth/me", headers=_headers(user, str(row.id))).status_code == 200
    # a refresh and a challenge token carry no session id as an access token would and are not affected
    login = client.post("/api/v1/auth/login", json={"email": "k2@test.com", "password": PASSWORD})
    assert login.status_code == 200 and client.get("/api/v1/auth/me", headers=_bearer(login.json()["access_token"])).status_code == 200


def test_an_invitation_is_a_row_holding_only_the_hash_of_its_token(db):
    admin = _user(db, "inv-admin@test.com", "admin")
    token = _create_invite(db, "invitee@test.com", "technician", admin)
    row = db.query(Invitation).filter(Invitation.email == "invitee@test.com").one()
    assert row.token_hash != token and len(row.token_hash) == 64 and token not in row.token_hash
    assert (row.role, row.invited_by) == ("technician", admin.id)
    assert row.used_at is None and row.cancelled_at is None
    assert datetime.now(timezone.utc) < row.expires_at <= datetime.now(timezone.utc) + timedelta(hours=48, seconds=5)
    # 256 random bits, not a signed claim
    assert len(token) >= 43 and "." not in token


def test_a_new_invitation_to_an_address_cancels_the_one_before(client, db):
    first = _create_invite(db, "again@test.com", "viewer")
    second = _create_invite(db, "again@test.com", "viewer")
    assert client.post("/api/v1/auth/invite/check", json={"token": first}).json() == {"status": "expired"}
    assert client.post("/api/v1/auth/invite/check", json={"token": second}).json() == {"status": "valid"}


def test_an_invitation_that_is_used_cancelled_or_expired_cannot_be_accepted(client, db):
    body = lambda t: {"token": t, "name": "N", "password": PASSWORD}  # noqa: E731
    cancelled = _create_invite(db, "c@test.com", "viewer")
    db.query(Invitation).filter(Invitation.email == "c@test.com").update({"cancelled_at": datetime.now(timezone.utc)})
    db.flush()
    assert client.post("/api/v1/auth/accept-invite", json=body(cancelled)).status_code == 400
    ok = _create_invite(db, "u@test.com", "viewer")
    assert client.post("/api/v1/auth/accept-invite", json=body(ok)).status_code == 201
    assert plain(client.post("/api/v1/auth/accept-invite", json=body(ok))) == {"detail": "This invitation has already been used"}
    row = db.query(Invitation).filter(Invitation.email == "u@test.com").one()
    assert row.used_at is not None


def test_a_made_up_token_finds_nothing(client):
    assert client.post("/api/v1/auth/accept-invite", json={"token": secrets.token_urlsafe(32), "name": "N", "password": PASSWORD}).status_code == 400


# ── M5: admin control of accounts ───────────────────────────────────────────

@pytest.fixture
def admins(db):
    one = _user(db, "root1@test.com", "admin")
    two = _user(db, "root2@test.com", "admin")
    return one, two


def _post(client, path, user, **body):
    return client.post(path, json={"password": PASSWORD, **body}, headers=_headers(user))


def _delete(client, path, user, **body):
    return client.request("DELETE", path, json={"password": PASSWORD, **body}, headers=_headers(user))


def _audit(db, action):
    return db.execute(text("SELECT user_id, resource_id, detail FROM audit_log WHERE action = :a ORDER BY created_at"), {"a": action}).all()


def test_every_account_action_needs_the_admins_fresh_proof(client, db, admins):
    one, _ = admins
    target = _user(db, "p-target@test.com")
    inv = _create_invite(db, "p-inv@test.com", "viewer")
    inv_id = str(db.query(Invitation).filter(Invitation.email == "p-inv@test.com").one().id)
    calls = [
        ("post", f"/api/v1/auth/users/{target.id}/deactivate"), ("post", f"/api/v1/auth/users/{target.id}/reactivate"),
        ("patch", f"/api/v1/auth/users/{target.id}/role"), ("post", f"/api/v1/auth/users/{target.id}/clear-two-step"),
        ("post", f"/api/v1/auth/users/{target.id}/reset-link"), ("delete", f"/api/v1/auth/users/{target.id}"),
        ("delete", f"/api/v1/auth/invitations/{inv_id}"),
    ]
    for method, path in calls:
        signin_guard.reset()   # five wrong proofs from one place make it wait, which is not what this test is about
        body = {"role": "viewer"} if path.endswith("/role") else {}
        none = client.request(method.upper(), path, json=body, headers=_headers(one))
        wrong = client.request(method.upper(), path, json={**body, "password": "wrong-password"}, headers=_headers(one))
        assert none.status_code == 400 and wrong.status_code == 400, path
        assert none.json()["detail"].startswith("Enter your current password to "), path
    db.refresh(target)
    assert target.is_active and target.role == "technician"
    assert inv


def test_a_non_admin_cannot_use_any_of_them(client, db):
    tech = _user(db, "tech@test.com")
    target = _user(db, "t2@test.com")
    for path in (f"/api/v1/auth/users/{target.id}/deactivate", f"/api/v1/auth/users/{target.id}/clear-two-step"):
        assert _post(client, path, tech).status_code == 403
    assert client.get("/api/v1/auth/invitations", headers=_headers(tech)).status_code == 403


def test_deactivating_ends_every_session_and_the_account_can_do_nothing(client, db, admins):
    one, _ = admins
    target = _user(db, "d1@test.com")
    session = client.post("/api/v1/auth/login", json={"email": "d1@test.com", "password": PASSWORD})
    access = session.json()["access_token"]
    refresh = session.cookies.get("refresh_token", path="/api/v1/auth/refresh")
    assert client.get("/api/v1/auth/me", headers=_bearer(access)).status_code == 200
    assert _post(client, f"/api/v1/auth/users/{target.id}/deactivate", one).status_code == 204
    db.refresh(target)
    assert target.is_active is False and target.deactivated_at is not None
    assert client.get("/api/v1/auth/me", headers=_bearer(access)).status_code == 401
    client.cookies.clear()
    for path in ("/api/v1/auth/refresh", "/api/v1/auth/logout"):
        client.cookies.set("refresh_token", refresh, path=path)
    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert plain(client.post("/api/v1/auth/login", json={"email": "d1@test.com", "password": PASSWORD})) == {"detail": "Invalid credentials"}
    assert db.query(UserSession).filter(UserSession.user_id == target.id, UserSession.revoked_at.is_(None)).count() == 0
    assert len(_audit(db, "user_deactivated")) == 1


def test_a_deactivated_account_cannot_sign_in_by_a_provider_reset_or_invitation(client, db, admins, monkeypatch):
    one, _ = admins
    target = _user(db, "d2@test.com", password=None, oauth_provider="google", oauth_id="g-d2")
    _post(client, f"/api/v1/auth/users/{target.id}/deactivate", one)
    with pytest.raises(HTTPException) as refused:
        auth_module._oauth_finish(db, target)
    assert refused.value.status_code == 403
    assert client.post(f"/api/v1/auth/users/{target.id}/reset-link", json={"password": PASSWORD}, headers=_headers(one)).status_code == 409
    token = _create_invite(db, "d2@test.com", "viewer")
    assert client.post("/api/v1/auth/accept-invite", json={"token": token, "name": "N", "password": PASSWORD}).status_code == 400


def test_reactivating_lets_the_person_sign_in_again(client, db, admins):
    one, _ = admins
    target = _user(db, "d3@test.com")
    _post(client, f"/api/v1/auth/users/{target.id}/deactivate", one)
    assert _post(client, f"/api/v1/auth/users/{target.id}/reactivate", one).status_code == 204
    assert client.post("/api/v1/auth/login", json={"email": "d3@test.com", "password": PASSWORD}).status_code == 200
    assert len(_audit(db, "user_reactivated")) == 1


def test_changing_a_role(client, db, admins):
    one, _ = admins
    target = _user(db, "r1@test.com", "viewer")
    res = client.patch(f"/api/v1/auth/users/{target.id}/role", json={"password": PASSWORD, "role": "technician"}, headers=_headers(one))
    assert res.status_code == 204
    db.refresh(target)
    assert target.role == "technician"
    assert _audit(db, "user_role_changed")[0].detail == "viewer->technician"
    bad = client.patch(f"/api/v1/auth/users/{target.id}/role", json={"password": PASSWORD, "role": "superuser"}, headers=_headers(one))
    assert bad.status_code == 422


def test_clearing_two_step_for_a_lost_authenticator(client, db, admins):
    one, _ = admins
    secret = pyotp.random_base32()
    target = _user(db, "t-2fa@test.com", totp_secret=secret, totp_enabled=True)
    assert _post(client, f"/api/v1/auth/users/{target.id}/clear-two-step", one).status_code == 204
    db.refresh(target)
    assert (target.totp_enabled, target.totp_secret) == (False, None)
    assert client.post("/api/v1/auth/login", json={"email": "t-2fa@test.com", "password": PASSWORD}).json().get("mfa_required") is not True
    assert len(_audit(db, "user_two_step_cleared")) == 1


def test_an_admin_cannot_act_on_themselves(client, db, admins):
    one, _ = admins
    for method, path, body in (
        ("post", f"/api/v1/auth/users/{one.id}/deactivate", {}),
        ("patch", f"/api/v1/auth/users/{one.id}/role", {"role": "viewer"}),
        ("delete", f"/api/v1/auth/users/{one.id}", {}),
    ):
        res = client.request(method.upper(), path, json={"password": PASSWORD, **body}, headers=_headers(one))
        assert res.status_code == 403 and "your own account" in res.json()["detail"], path
    db.refresh(one)
    assert one.is_active and one.role == "admin"


def test_the_last_active_admin_cannot_be_demoted_deactivated_or_removed(client, db):
    boss = _user(db, "boss@test.com", "admin")
    helper = _user(db, "helper@test.com", "admin")
    # helper is the only other admin. Deactivate them, then the boss is the last active one
    assert _post(client, f"/api/v1/auth/users/{helper.id}/deactivate", boss).status_code == 204
    # a third admin's action would be needed to touch the boss and the boss cannot act on themselves. Make one
    third = _user(db, "third@test.com", "admin")
    assert _post(client, f"/api/v1/auth/users/{boss.id}/deactivate", third).status_code == 204
    # now third is the last active admin and the deactivated ones cannot act. A viewer made admin cannot either, so
    # check the guard directly: nothing may remove the only active admin
    with pytest.raises(HTTPException) as refused:
        from app.routes.admin_users import _last_admin_guard
        _last_admin_guard(db, third, "removed")
    assert refused.value.status_code == 409 and "last active admin" in refused.value.detail


def test_two_admins_cannot_each_remove_the_other(client, db, admins):
    one, two = admins
    # the first removal succeeds
    assert _delete(client, f"/api/v1/auth/users/{two.id}", one).status_code == 204
    # the second, from the admin that was just removed, is refused: that admin no longer exists and nobody may remove the last one
    again = _delete(client, f"/api/v1/auth/users/{one.id}", two)
    assert again.status_code in (401, 403, 409)
    assert db.query(User).filter(User.id == one.id).count() == 1


def test_two_admins_cannot_each_demote_the_other_at_once(client, db, admins):
    one, two = admins
    assert client.patch(f"/api/v1/auth/users/{two.id}/role", json={"password": PASSWORD, "role": "viewer"}, headers=_headers(one)).status_code == 204
    # two is a viewer now. A stale token still says admin, but the role is read from the database
    res = client.patch(f"/api/v1/auth/users/{one.id}/role", json={"password": PASSWORD, "role": "viewer"}, headers=_headers(two))
    assert res.status_code == 403
    assert db.query(User).filter(User.role == "admin", User.is_active.is_(True)).count() == 1


def test_the_admin_rows_are_locked_in_a_fixed_order_before_the_guard_counts(client, db, admins):
    one, two = admins
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    bind = db.get_bind()
    event.listen(bind, "before_cursor_execute", record)
    try:
        _post(client, f"/api/v1/auth/users/{two.id}/deactivate", one)
    finally:
        event.remove(bind, "before_cursor_execute", record)
    locks = [s for s in statements if "FROM users" in s and "FOR UPDATE" in s and "users.role =" in s]
    assert locks and all("ORDER BY users.id" in s for s in locks)
    # the lock comes before the count of other active admins
    first_lock = next(i for i, s in enumerate(statements) if s in locks)
    count = next(i for i, s in enumerate(statements) if "count(" in s.lower() and "users" in s and "is_active" in s)
    assert first_lock < count


def test_removing_an_account(client, db, admins):
    from app.models.device import Device
    from app.models.ticket import Ticket
    one, _ = admins
    target = _user(db, "rm@test.com")
    other = _user(db, "rm-other@test.com")
    machine = Device(name="M", type="esp32", api_key=secrets.token_urlsafe(32), owner_id=target.id)
    db.add(machine)
    ticket = Ticket(title="t", status="open", created_by=target.id, assigned_to=target.id)
    db.add(ticket)
    db.flush()
    # a machine it owns must be handed on first
    blocked = _delete(client, f"/api/v1/auth/users/{target.id}", one)
    assert (blocked.status_code, plain(blocked)) == (409, {"detail": "Hand your machines to another person first"})
    machine.owner_id = other.id
    db.flush()
    session_row = UserSession(user_id=target.id, current_jti="j", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    db.add(session_row)
    db.flush()
    assert _delete(client, f"/api/v1/auth/users/{target.id}", one).status_code == 204
    assert db.query(User).filter(User.id == target.id).count() == 0
    db.expire_all()
    kept = db.query(Ticket).filter(Ticket.id == ticket.id).one()
    assert kept.created_by is None and kept.assigned_to is None and kept.title == "t"
    assert db.query(UserSession).filter(UserSession.user_id == target.id).count() == 0
    # the audit trail is kept and holds an id, never an address
    rows = _audit(db, "user_removed")
    assert [r.resource_id for r in rows] == [str(target.id)] and "@" not in (rows[0].detail or "")


def test_a_reset_link_goes_to_the_accounts_own_address_and_never_to_the_admin(client, db, admins, monkeypatch):
    one, _ = admins
    target = _user(db, "reset-me@test.com")
    mail = []
    monkeypatch.setattr(email_service, "send_email", lambda to, subject, text_, html_body=None, reply_to=None: mail.append((to, text_)) or True)
    res = _post(client, f"/api/v1/auth/users/{target.id}/reset-link", one)
    assert res.status_code == 200 and res.json() == {"message": "A reset link was sent to the account's own address", "detail": "A reset link was sent to the account's own address", "email_sent": True}
    assert "token" not in res.text and "reset-password" not in res.text
    (to, body), = mail
    assert to == ["reset-me@test.com"]
    token = re.search(r"#token=([\w\-\.]+)", body).group(1)
    assert len(_audit(db, "password_reset_link_sent")) == 1
    # the person chooses a new password with it, once
    new = "Tr1cky-Tree-9"
    ok = client.post("/api/v1/auth/reset-password", json={"token": token, "password": new})
    assert ok.status_code == 204
    assert client.post("/api/v1/auth/login", json={"email": "reset-me@test.com", "password": new}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "reset-me@test.com", "password": PASSWORD}).status_code == 401
    again = client.post("/api/v1/auth/reset-password", json={"token": token, "password": "An0ther-Tree-8"})
    assert (again.status_code, plain(again)) == (400, {"detail": "This reset link is invalid or has expired"})


def test_a_reset_ends_every_session_and_keeps_two_step(client, db, admins, monkeypatch):
    one, _ = admins
    secret = pyotp.random_base32()
    target = _user(db, "reset2@test.com", totp_secret=secret, totp_enabled=True)
    row = UserSession(user_id=target.id, current_jti="j", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    db.add(row)
    db.flush()
    mail = []
    monkeypatch.setattr(email_service, "send_email", lambda to, subject, text_, html_body=None, reply_to=None: mail.append(text_) or True)
    _post(client, f"/api/v1/auth/users/{target.id}/reset-link", one, code="")
    # a second link inside ten minutes is refused, so the route cannot be used to mail someone repeatedly
    assert _post(client, f"/api/v1/auth/users/{target.id}/reset-link", one).status_code == 429
    token = re.search(r"#token=([\w\-\.]+)", mail[0]).group(1)
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "password": "Tr1cky-Tree-9"}).status_code == 204
    db.refresh(target)
    db.refresh(row)
    assert row.revoked_at is not None and target.totp_enabled is True


@pytest.mark.parametrize("make", ["junk", "expired", "access", "weak", "wrong_marker", "inactive"])
def test_every_bad_reset_link_gets_the_same_answer(client, db, make):
    from app.routes.admin_users import _password_marker
    user = _user(db, f"rb-{make}@test.com", is_active=(make != "inactive"))
    good = {"sub": str(user.id), "ver": 0, "pw": _password_marker(user)}
    token = {
        "junk": "not-a-token",
        "expired": auth_module._encode(good, "reset", timedelta(seconds=-5)),
        "access": create_access_token({"sub": str(user.id)}),
        "weak": auth_module._encode(good, "reset", timedelta(hours=1)),
        "wrong_marker": auth_module._encode({**good, "pw": "0000000000000000"}, "reset", timedelta(hours=1)),
        "inactive": auth_module._encode(good, "reset", timedelta(hours=1)),
    }[make]
    password = "password" if make == "weak" else "Tr1cky-Tree-9"
    res = client.post("/api/v1/auth/reset-password", json={"token": token, "password": password})
    if make == "weak":
        # a common password is refused by the same rules as everywhere else
        assert res.status_code == 422
    else:
        assert (res.status_code, plain(res)) == (400, {"detail": "This reset link is invalid or has expired"})


def test_a_reset_link_needs_the_email_to_work(client, db, admins, monkeypatch):
    one, _ = admins
    target = _user(db, "noemail@test.com")
    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: False)
    res = _post(client, f"/api/v1/auth/users/{target.id}/reset-link", one)
    assert (res.status_code, res.json()["detail"]) == (503, "The email could not be sent, so no reset link was made available")


def test_the_user_list_shows_state_second_factor_last_sign_in_and_sessions(client, db, admins):
    one, _ = admins
    target = _user(db, "list@test.com", totp_enabled=True, totp_secret=pyotp.random_base32(), last_login=datetime(2026, 11, 20, tzinfo=timezone.utc))
    for _ in range(2):
        db.add(UserSession(user_id=target.id, current_jti="j", expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    db.add(UserSession(user_id=target.id, current_jti="j", expires_at=datetime.now(timezone.utc) + timedelta(days=1), revoked_at=datetime.now(timezone.utc)))
    db.flush()
    rows = {r["email"]: r for r in client.get("/api/v1/auth/users", headers=_headers(one)).json()}
    row = rows["list@test.com"]
    assert (row["role"], row["is_active"], row["totp_enabled"], row["session_count"]) == ("technician", True, True, 2)
    assert row["last_login"].startswith("2026-11-20")
    assert "phone_number" not in row and "password_hash" not in row


def test_pending_invitations_can_be_listed_and_cancelled(client, db, admins):
    one, _ = admins
    token = _create_invite(db, "pending@test.com", "viewer", one)
    used = _create_invite(db, "usedinv@test.com", "viewer", one)
    client.post("/api/v1/auth/accept-invite", json={"token": used, "name": "U", "password": PASSWORD})
    rows = client.get("/api/v1/auth/invitations", headers=_headers(one)).json()
    assert [r["email"] for r in rows] == ["pending@test.com"]
    assert set(rows[0]) == {"id", "email", "role", "invited_by_name", "created_at", "expires_at"}
    assert "token" not in str(rows)
    res = _delete(client, f"/api/v1/auth/invitations/{rows[0]['id']}", one)
    assert res.status_code == 204
    assert client.post("/api/v1/auth/invite/check", json={"token": token}).json() == {"status": "expired"}
    assert client.get("/api/v1/auth/invitations", headers=_headers(one)).json() == []
    assert _delete(client, f"/api/v1/auth/invitations/{rows[0]['id']}", one).status_code == 404
    assert len(_audit(db, "invitation_cancelled")) == 1


# ── M10: fresh proof for the dangerous admin actions ────────────────────────

def test_inviting_an_admin_needs_the_proof_and_other_roles_do_not(client, db, admins):
    one, _ = admins
    body = {"email": "newadmin@test.com", "role": "admin"}
    res = client.post("/api/v1/auth/invite", json=body, headers=_headers(one))
    assert (res.status_code, plain(res)) == (400, {"detail": "Enter your current password to invite an admin"})
    assert client.post("/api/v1/auth/invite", json={**body, "password": "wrong-password"}, headers=_headers(one)).status_code == 400
    assert client.post("/api/v1/auth/invite", json={**body, "password": PASSWORD}, headers=_headers(one)).status_code == 201
    assert client.post("/api/v1/auth/invite", json={"email": "viewer-inv@test.com", "role": "viewer"}, headers=_headers(one)).status_code == 201
    assert len(_audit(db, "invitation_created")) == 2


def test_the_dangerous_admin_routes_ask_for_proof_with_these_messages(client, db, admins, monkeypatch, tmp_path):
    from app.models.device import Device
    one, _ = admins
    wh = client.post("/api/v1/webhooks", json={"name": "n", "url": "https://8.8.8.8/x"}, headers=_headers(one))
    assert (wh.status_code, plain(wh)) == (400, {"detail": "Enter your current password to add a webhook"})
    created = client.post("/api/v1/webhooks", json={"name": "n", "url": "https://8.8.8.8/x", "password": PASSWORD}, headers=_headers(one))
    assert created.status_code == 201
    patch = client.patch(f"/api/v1/webhooks/{created.json()['id']}", json={"enabled": False}, headers=_headers(one))
    assert (patch.status_code, plain(patch)) == (400, {"detail": "Enter your current password to change a webhook"})
    monkeypatch.setattr(settings, "firmware_storage_path", str(tmp_path))
    files = {"file": ("fw.bin", b"abc", "application/octet-stream")}
    up = client.post("/api/v1/firmware/upload?version=1.0.0", files=files, headers=_headers(one))
    assert (up.status_code, plain(up)) == (400, {"detail": "Enter your current password to upload firmware"})
    assert client.post("/api/v1/firmware/upload?version=1.0.0", files=files, data={"password": "wrong-password"}, headers=_headers(one)).status_code == 400
    assert client.post("/api/v1/firmware/upload?version=1.0.0", files=files, data={"password": PASSWORD}, headers=_headers(one)).status_code == 201
    machine = Device(name="M", type="esp32", api_key=secrets.token_urlsafe(32))
    db.add(machine)
    db.flush()
    rot = client.post(f"/api/v1/devices/{machine.id}/rotate-key", headers=_headers(one))
    assert (rot.status_code, plain(rot)) == (400, {"detail": "Enter your current password to rotate this machine's key"})
    assert client.post(f"/api/v1/devices/{machine.id}/rotate-key", json={"password": PASSWORD}, headers=_headers(one)).status_code == 200


def test_a_wrong_proof_is_400_and_never_401_and_a_bad_token_is_401(client, db, admins):
    one, _ = admins
    for headers, expected in ((_headers(one), 400), ({}, 401), (_bearer("junk"), 401)):
        res = client.post("/api/v1/webhooks", json={"name": "n", "url": "https://8.8.8.8/x", "password": "wrong-password"}, headers=headers)
        assert res.status_code == expected


def test_the_proof_asks_for_a_code_when_two_step_is_on(client, db):
    secret = pyotp.random_base32()
    boss = _user(db, "boss2fa@test.com", "admin", totp_secret=secret, totp_enabled=True)
    body = {"name": "n", "url": "https://8.8.8.8/x"}
    only_pw = client.post("/api/v1/webhooks", json={**body, "password": PASSWORD}, headers=_headers(boss))
    assert (only_pw.status_code, plain(only_pw)) == (400, {"detail": "Enter a current two-step code to add a webhook"})
    ok = client.post("/api/v1/webhooks", json={**body, "password": PASSWORD, "code": pyotp.TOTP(secret).now()}, headers=_headers(boss))
    assert ok.status_code == 201


def test_a_provider_only_admin_proves_it_with_the_session_that_returned_from_the_provider(client, db):
    boss = _user(db, "boss-prov@test.com", "admin", password=None, oauth_provider="google", oauth_id="g-boss")
    stale = UserSession(user_id=boss.id, current_jti="a", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    fresh = UserSession(user_id=boss.id, current_jti="b", expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                        provider_signin_at=datetime.now(timezone.utc))
    db.add_all([stale, fresh])
    db.flush()
    body = {"name": "n", "url": "https://8.8.8.8/x"}
    refused = client.post("/api/v1/webhooks", json=body, headers=_headers(boss, str(stale.id)))
    assert (refused.status_code, plain(refused)) == (400, {"detail": "Sign in with Google again within the last 5 minutes to add a webhook"})
    assert client.post("/api/v1/webhooks", json=body, headers=_headers(boss, str(fresh.id))).status_code == 201


def test_a_technician_owner_can_rotate_their_own_machines_key_with_their_password(client, db):
    from app.models.device import Device
    tech = _user(db, "owner-tech@test.com")
    mine = Device(name="M", type="esp32", api_key=secrets.token_urlsafe(32), owner_id=tech.id)
    db.add(mine)
    db.flush()
    assert client.post(f"/api/v1/devices/{mine.id}/rotate-key", headers=_headers(tech)).status_code == 400
    assert client.post(f"/api/v1/devices/{mine.id}/rotate-key", json={"password": PASSWORD}, headers=_headers(tech)).status_code == 200


def test_the_proof_routes_are_rate_limited_and_wrong_proofs_slow_the_source(client, db, admins):
    one, _ = admins
    codes = [client.post("/api/v1/webhooks", json={"name": "n", "url": "https://8.8.8.8/x", "password": "wrong-password"}, headers=_headers(one)).status_code for _ in range(8)]
    assert codes[:5] == [400] * 5 and 429 in codes[5:]


def test_the_proof_rate_cap_is_per_account_and_per_minute(db, clock):
    user = _user(db, "cap@test.com")
    key = signin_guard.account_key(user_id=user.id)
    assert all(signin_guard.proof_rate_ok(key) for _ in range(20))
    assert signin_guard.proof_rate_ok(key) is False
    clock.now += 61
    assert signin_guard.proof_rate_ok(key) is True


# ── M6: two-step secrets at rest ────────────────────────────────────────────

def _raw_secret(db, user):
    return db.execute(text("SELECT totp_secret FROM users WHERE id = :i"), {"i": str(user.id)}).scalar()


def test_a_two_step_secret_is_stored_encrypted_and_works(client, db):
    user = _user(db, "enc@test.com")
    secret = client.post("/api/v1/auth/2fa/enable", json={"password": PASSWORD}, headers=_headers(user)).json()["secret"]
    stored = _raw_secret(db, user)
    assert stored.startswith("enc:v1:") and secret not in stored
    code = pyotp.TOTP(secret).now()
    assert client.post("/api/v1/auth/2fa/confirm", json={"code": code}, headers=_headers(user)).status_code == 200
    db.refresh(user)
    assert user.totp_enabled and user.totp_secret == secret
    assert _raw_secret(db, user).startswith("enc:v1:")


def test_a_secret_in_clear_from_before_is_readable_and_encrypted_once(db):
    user = _user(db, "legacy@test.com", totp_enabled=True)
    db.execute(text("UPDATE users SET totp_secret = 'JBSWY3DPEHPK3PXP' WHERE id = :i"), {"i": str(user.id)})
    db.expire_all()
    assert db.query(User).filter(User.id == user.id).one().totp_secret == "JBSWY3DPEHPK3PXP"
    assert two_step_secrets.encrypt_legacy(db) == 1
    stored = _raw_secret(db, user)
    assert stored.startswith("enc:v1:") and "JBSWY3DPEHPK3PXP" not in stored
    db.expire_all()
    assert db.query(User).filter(User.id == user.id).one().totp_secret == "JBSWY3DPEHPK3PXP"
    # safe to run twice
    assert two_step_secrets.encrypt_legacy(db) == 0
    assert _raw_secret(db, user) == stored


def test_a_rotated_key_reads_the_old_secrets_and_the_next_pass_re_encrypts_them(db, monkeypatch):
    user = _user(db, "rot@test.com")
    user.totp_secret = "JBSWY3DPEHPK3PXP"
    db.flush()
    before = _raw_secret(db, user)
    old = settings.secret_key
    monkeypatch.setattr(settings, "secret_key", _strong_key())
    monkeypatch.setattr(settings, "secret_key_previous", old)
    db.expire_all()
    assert db.query(User).filter(User.id == user.id).one().totp_secret == "JBSWY3DPEHPK3PXP"
    assert two_step_secrets.encrypt_legacy(db) == 1
    after = _raw_secret(db, user)
    assert after != before
    # and with the previous key removed it still reads, because it is now under the current one
    monkeypatch.setattr(settings, "secret_key_previous", "")
    db.expire_all()
    assert db.query(User).filter(User.id == user.id).one().totp_secret == "JBSWY3DPEHPK3PXP"


def test_a_secret_no_key_opens_is_unusable_and_logged_not_leaked(db, monkeypatch, caplog):
    user = _user(db, "lost@test.com", totp_enabled=True)
    user.totp_secret = "JBSWY3DPEHPK3PXP"
    db.flush()
    monkeypatch.setattr(settings, "secret_key", _strong_key())
    db.expire_all()
    with caplog.at_level(logging.ERROR):
        assert db.query(User).filter(User.id == user.id).one().totp_secret is None
    assert "JBSWY3DPEHPK3PXP" not in caplog.text and "could not be decrypted" in caplog.text


def test_the_secret_is_never_in_the_export_or_a_reply(client, db):
    user = _user(db, "noleak@test.com")
    secret = client.post("/api/v1/auth/2fa/enable", json={"password": PASSWORD}, headers=_headers(user)).json()["secret"]
    export = client.get("/api/v1/auth/me/export", headers=_headers(user))
    assert secret not in export.text and "enc:v1" not in export.text


def test_the_start_up_pass_encrypts_what_is_left(db, monkeypatch):
    user = _user(db, "startup@test.com")
    db.execute(text("UPDATE users SET totp_secret = 'JBSWY3DPEHPK3PXP' WHERE id = :i"), {"i": str(user.id)})
    from app.main import _encrypt_two_step_secrets
    monkeypatch.setattr("app.db.SessionLocal", lambda: _Keep(db))
    _encrypt_two_step_secrets()
    assert _raw_secret(db, user).startswith("enc:v1:")


class _Keep:
    def __init__(self, session):
        self._s = session

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass


def test_there_are_no_recovery_codes_to_hash():
    # recovery codes do not exist in this product. A lost authenticator is handled by an admin clearing two-step
    assert not hasattr(User, "recovery_codes")


# ── lows ────────────────────────────────────────────────────────────────────

def test_the_cookie_routes_refuse_a_page_on_another_origin(client, db):
    _user(db, "o1@test.com")
    login = client.post("/api/v1/auth/login", json={"email": "o1@test.com", "password": PASSWORD})
    assert login.status_code == 200
    assert client.post("/api/v1/auth/refresh", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/v1/auth/refresh", headers={"Origin": "http://localhost:3000"}).status_code == 200
    assert client.post("/api/v1/auth/refresh").status_code in (200, 401)


def test_the_root_does_not_say_which_environment_this_is(client):
    res = client.get("/")
    assert res.status_code == 200 and "environment" not in res.json()


def test_replies_carry_nosniff_and_the_account_routes_are_not_cached(client, db):
    root = client.get("/")
    assert root.headers["x-content-type-options"] == "nosniff" and "cache-control" not in root.headers
    _user(db, "hdr@test.com")
    login = client.post("/api/v1/auth/login", json={"email": "hdr@test.com", "password": PASSWORD})
    assert login.headers["cache-control"] == "no-store" and login.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/v1/auth/providers").headers["cache-control"] == "no-store"


def test_an_unsent_email_does_not_log_its_link_unless_asked(caplog, monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "")
    link = "https://app.example/accept-invite#token=SECRETTOKEN"
    with caplog.at_level(logging.INFO):
        email_service.send_invite("a@test.com", link, "viewer")
        email_service.send_password_reset("a@test.com", "https://app.example/reset-password#token=SECRETRESET")
    assert "SECRETTOKEN" not in caplog.text and "SECRETRESET" not in caplog.text
    monkeypatch.setattr(settings, "log_email_bodies", True)
    with caplog.at_level(logging.INFO):
        email_service.send_invite("a@test.com", link, "viewer")
    assert "SECRETTOKEN" in caplog.text


def test_ticket_status_and_priority_are_fixed_lists(client, db):
    admin = _user(db, "tk@test.com", "admin")
    h = _headers(admin)
    assert client.post("/api/v1/tickets", json={"title": "t", "priority": "urgent"}, headers=h).status_code == 422
    made = client.post("/api/v1/tickets", json={"title": "t", "priority": "high"}, headers=h)
    assert made.status_code == 201
    tid = made.json()["id"]
    assert client.patch(f"/api/v1/tickets/{tid}", json={"status": "decommissioned"}, headers=h).status_code == 422
    assert client.patch(f"/api/v1/tickets/{tid}", json={"status": "in_progress"}, headers=h).status_code == 200


def test_the_audit_export_is_signed_with_its_own_key(client, db):
    import hashlib
    import hmac
    admin = _user(db, "aud@test.com", "admin")
    res = client.get("/api/v1/audit-logs/export", headers=_headers(admin))
    assert res.status_code == 200
    sig = next(v for k, v in res.headers.items() if "signature" in k.lower() or "hmac" in k.lower())
    assert sig == hmac.new(derive_key("audit_export"), res.content, hashlib.sha256).hexdigest()


def test_the_container_hides_the_server_header():
    docker = REPO / "backend" / "Dockerfile"
    if not docker.is_file():
        pytest.skip("backend/Dockerfile is not present in this environment")
    assert "--no-server-header" in docker.read_text()


# ── migrations ──────────────────────────────────────────────────────────────

_MIGRATIONS = REPO / "backend" / "migrations"
_CHANGING = re.compile(r"^\s*(ALTER\s+TABLE|CREATE\s+(UNIQUE\s+)?INDEX|CREATE\s+TABLE|UPDATE)\b", re.I | re.M)


@pytest.mark.skipif(not _MIGRATIONS.is_dir(), reason="backend/migrations is not present in this environment")
@pytest.mark.parametrize("name", ["032_accounts_hardening.sql", "033_email_lower_case.sql"])
def test_the_new_migrations_are_conditional_have_a_lock_timeout_and_need_no_superuser(name):
    sql = (_MIGRATIONS / name).read_text()
    assert re.search(r"^SET lock_timeout = '\d+s';", sql, re.M)
    outside = re.sub(r"\$\$.*?\$\$", "", re.sub(r"--[^\n]*", "", sql), flags=re.S)
    assert not _CHANGING.search(outside), name
    for needs_superuser in ("CREATE EXTENSION", "COPY ", "ALTER SYSTEM", "SUPERUSER", "CREATE ROLE"):
        assert needs_superuser not in sql.upper(), name


# ── the NUL check and the machine ingest route ──────────────────────────────

def _run_guard(method, path, body=b'{"a": "\\u0000"}', query=b"", ctype=b"application/json"):
    import asyncio
    from app.middleware import NulGuard
    reached = []

    async def app(scope, receive, send):
        msg = await receive()
        reached.append(msg.get("body"))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    sent = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": method, "path": path, "query_string": query,
             "headers": [(b"content-type", ctype), (b"content-length", str(len(body)).encode())]}
    state = {"given": False}

    async def receive():
        if not state["given"]:
            state["given"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    asyncio.run(NulGuard(app)(scope, receive, send))
    return sent[0]["status"], reached


def test_only_the_device_ingest_route_is_exempt_from_the_nul_check():
    from app.middleware import EXEMPT
    # the single reading and the batch: both clean a bad string and keep the reading
    assert EXEMPT == {("POST", "/api/v1/telemetry"), ("POST", "/api/v1/telemetry/batch")}
    # the exempt route reaches the app untouched, so the ingest path can clean the field and keep the reading
    assert _run_guard("POST", "/api/v1/telemetry") == (200, [b'{"a": "\\u0000"}'])
    assert _run_guard("POST", "/api/v1/telemetry/batch") == (200, [b'{"a": "\\u0000"}'])
    # nothing near it is exempt: another method, a longer path, a trailing slash, a sub-route or the same path elsewhere
    for method, path in (("PATCH", "/api/v1/telemetry"), ("POST", "/api/v1/telemetry/"), ("POST", "/api/v1/telemetry/export"),
                         ("POST", "/api/v1/telemetry/abc"), ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/devices"),
                         ("POST", "/api/v1/firmware/upload"), ("DELETE", "/api/v1/telemetry")):
        status, reached = _run_guard(method, path)
        assert (status, reached) == (422, []), (method, path)


def test_the_middleware_does_not_touch_multipart_websockets_or_a_body_it_cannot_bound():
    from app.middleware import _MAX_BODY_TO_CHECK
    # a multipart upload is passed through unread, even with a NUL in it
    assert _run_guard("POST", "/api/v1/firmware/upload", ctype=b"multipart/form-data; boundary=x")[0] == 200
    # a body declared larger than the cap is not read here
    big = b"x" * (_MAX_BODY_TO_CHECK + 1)
    assert _run_guard("POST", "/api/v1/auth/login", body=big)[0] == 200
    # a websocket scope goes straight through
    import asyncio
    from app.middleware import NulGuard
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    asyncio.run(NulGuard(app)({"type": "websocket", "path": "/ws/telemetry/x", "query_string": b"token=%00"}, None, None))
    assert seen == ["websocket"]
    assert _MAX_BODY_TO_CHECK == 1_000_000


def test_a_reading_with_a_bad_string_is_kept_through_the_real_app(client, db, device):
    # through the whole app: the node type has a NUL, the reading is still stored and the middleware does not answer
    res = client.post("/api/v1/telemetry", json={"device_id": str(device.id), "temperature": 21.0, "node_type": "esp\u0000"},
                      headers={"X-API-Key": device.api_key})
    assert res.status_code == 201


# ── phone numbers confirmed by a code ───────────────────────────────────────

@pytest.fixture
def texts(monkeypatch):
    """A text vendor that is set up, recording what it is asked to send."""
    from app.services import sms_service
    sent = []
    monkeypatch.setattr(sms_service, "is_configured", lambda: True)
    monkeypatch.setattr(sms_service, "send_sms", lambda number, message: sent.append((number, message)) or True)
    return sent


def _code_from(texts):
    return re.search(r"code: (\d{6})", texts[-1][1]).group(1)


def test_a_changed_number_starts_unconfirmed_and_a_confirmed_one_stays_so_when_resent(client, db):
    user = _user(db, "ph1@test.com", phone_number="+447700900010", phone_confirmed_at=datetime.now(timezone.utc))
    me = client.get("/api/v1/auth/me", headers=_headers(user)).json()
    assert me["phone_confirmed"] is True
    same = client.patch("/api/v1/auth/me", json={"phone_number": "+44 7700 900010"}, headers=_headers(user))
    assert same.json()["phone_confirmed"] is True
    changed = client.patch("/api/v1/auth/me", json={"phone_number": "+447700900011", "current_password": PASSWORD}, headers=_headers(user))
    assert changed.status_code == 200 and changed.json()["phone_confirmed"] is False
    db.refresh(user)
    assert user.phone_confirmed_at is None


def test_alert_texts_use_only_a_confirmed_number(db):
    from app.services.alert_service import _phone_confirmed
    user = _user(db, "ph2@test.com", phone_number="+447700900012")
    assert _phone_confirmed(user) is False
    user.phone_confirmed_at = datetime.now(timezone.utc)
    assert _phone_confirmed(user) is True


def test_the_code_is_texted_stored_hashed_and_confirms_the_number(client, db, texts):
    user = _user(db, "ph3@test.com", phone_number="+447700900013")
    res = client.post("/api/v1/auth/me/phone/send-code", headers=_headers(user))
    assert res.status_code == 200 and res.json() == {"sent": True, "message": "A code was sent to your number", "detail": "A code was sent to your number", "expires_in_seconds": 600}
    (number, message), = texts
    assert number == "+447700900013"
    code = _code_from(texts)
    db.refresh(user)
    assert user.phone_code_hash and code not in user.phone_code_hash and len(user.phone_code_hash) == 64
    assert user.phone_code_expires_at > datetime.now(timezone.utc)
    assert client.post("/api/v1/auth/me/phone/confirm", json={"code": code}, headers=_headers(user)).status_code == 204
    db.refresh(user)
    assert user.phone_confirmed_at is not None and user.phone_code_hash is None
    # a code works once
    assert client.post("/api/v1/auth/me/phone/confirm", json={"code": code}, headers=_headers(user)).status_code == 400


def test_a_wrong_code_five_times_ends_the_code(client, db, texts):
    user = _user(db, "ph4@test.com", phone_number="+447700900014")
    client.post("/api/v1/auth/me/phone/send-code", headers=_headers(user))
    code = _code_from(texts)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        res = client.post("/api/v1/auth/me/phone/confirm", json={"code": wrong}, headers=_headers(user))
        assert (res.status_code, plain(res)) == (400, {"detail": "That code is wrong or has expired"})
    # even the right code no longer works: a new one is needed
    assert client.post("/api/v1/auth/me/phone/confirm", json={"code": code}, headers=_headers(user)).status_code == 400
    db.refresh(user)
    assert user.phone_confirmed_at is None


def test_an_expired_code_and_a_code_for_the_old_number_are_refused(client, db, texts):
    user = _user(db, "ph5@test.com", phone_number="+447700900015")
    client.post("/api/v1/auth/me/phone/send-code", headers=_headers(user))
    code = _code_from(texts)
    user.phone_code_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()
    assert client.post("/api/v1/auth/me/phone/confirm", json={"code": code}, headers=_headers(user)).status_code == 400
    client.post("/api/v1/auth/me/phone/send-code", headers=_headers(user))
    code = _code_from(texts)
    client.patch("/api/v1/auth/me", json={"phone_number": "+447700900016", "current_password": PASSWORD}, headers=_headers(user))
    assert client.post("/api/v1/auth/me/phone/confirm", json={"code": code}, headers=_headers(user)).status_code == 400


def test_a_code_made_for_one_account_does_not_confirm_another(client, db, texts):
    one = _user(db, "ph6a@test.com", phone_number="+447700900017")
    two = _user(db, "ph6b@test.com", phone_number="+447700900017")
    client.post("/api/v1/auth/me/phone/send-code", headers=_headers(one))
    code = _code_from(texts)
    assert client.post("/api/v1/auth/me/phone/confirm", json={"code": code}, headers=_headers(two)).status_code == 400


def test_sending_is_limited_for_each_account_and_each_number(client, db, texts):
    from app.limiter import limiter
    limiter.enabled = False
    user = _user(db, "ph7@test.com", phone_number="+447700900018")
    codes = [client.post("/api/v1/auth/me/phone/send-code", headers=_headers(user)).status_code for _ in range(6)]
    # the per-number limit (3) bites before the per-account one (5)
    assert codes[:3] == [200] * 3 and codes[3] == 429
    others = [_user(db, f"ph7-{n}@test.com", phone_number="+447700900019") for n in range(5)]
    results = [client.post("/api/v1/auth/me/phone/send-code", headers=_headers(u)).status_code for u in others]
    assert results[:3] == [200] * 3 and 429 in results[3:]


def test_the_confirm_route_takes_six_digits_only(client, db):
    user = _user(db, "ph8@test.com", phone_number="+447700900020")
    for bad in ("12345", "1234567", "abcdef", "12 456", ""):
        assert client.post("/api/v1/auth/me/phone/confirm", json={"code": bad}, headers=_headers(user)).status_code == 422


def test_no_number_means_no_code(client, db, texts):
    user = _user(db, "ph9@test.com")
    res = client.post("/api/v1/auth/me/phone/send-code", headers=_headers(user))
    assert (res.status_code, plain(res)) == (400, {"detail": "Add a phone number to your profile first"})
    assert texts == []


def test_in_production_without_a_text_vendor_the_answer_is_plain_and_nothing_is_stored(client, db, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    user = _user(db, "ph10@test.com", phone_number="+447700900021")
    # outside development every access token must name a live session
    from app.routes.auth import _start_session
    res = client.post("/api/v1/auth/me/phone/send-code", headers=_headers(user, str(_start_session(db, user).id)))
    assert (res.status_code, plain(res)) == (503, {"detail": "Texts are not set up on this server, so a confirmation code cannot be sent"})
    db.refresh(user)
    assert user.phone_code_hash is None


def test_in_development_without_a_vendor_the_code_is_logged_only_when_asked_for(client, db, monkeypatch, caplog):
    user = _user(db, "ph11@test.com", phone_number="+447700900022")
    with caplog.at_level(logging.INFO):
        res = client.post("/api/v1/auth/me/phone/send-code", headers=_headers(user))
    assert res.status_code == 200 and res.json()["sent"] is False
    assert "A phone confirmation code was issued" in caplog.text and "+447700900022" not in caplog.text
    assert not re.search(r"\b\d{6}\b", caplog.text.replace("447700900022", ""))
    code_hash = db.query(User).filter(User.id == user.id).one().phone_code_hash
    assert code_hash
    caplog.clear()
    monkeypatch.setattr(settings, "log_email_bodies", True)
    with caplog.at_level(logging.INFO):
        client.post("/api/v1/auth/me/phone/send-code", headers=_headers(user))
    logged = re.search(r": (\d{6})", caplog.text).group(1)
    db.refresh(user)
    assert client.post("/api/v1/auth/me/phone/confirm", json={"code": logged}, headers=_headers(user)).status_code == 204


def test_the_phone_routes_need_a_sign_in(client):
    assert client.post("/api/v1/auth/me/phone/send-code").status_code == 401
    assert client.post("/api/v1/auth/me/phone/confirm", json={"code": "123456"}).status_code == 401


@pytest.mark.skipif(not (_MIGRATIONS / "033_email_lower_case.sql").is_file(), reason="the migrations folder is not present in this environment")
def test_migration_033_stops_with_instructions_when_two_accounts_differ_only_in_case(db):
    sql = (_MIGRATIONS / "033_email_lower_case.sql").read_text()
    db.execute(text("DROP INDEX idx_users_email_lower"))
    first = _user(db, "Clash@test.com")
    second = _user(db, "clash@test.com")
    db.flush()
    with pytest.raises(Exception) as stopped:
        db.connection().connection.cursor().execute(sql)
    message = str(stopped.value)
    assert "migration 033 stopped" in message and "docs/deployment.md" in message
    # both ids are named, so the operator knows which accounts to look at
    assert str(first.id) in message and str(second.id) in message
