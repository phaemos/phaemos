"""
Email change limits and notices, the status codes of a wrong proof, clearing the lock count, the refresh grace,
cookie lifetime, the phone proof, ending your own session, invitation checks, migrations, the image and linking
a provider to a password account.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pyotp
import pytest
from fastapi import HTTPException
from passlib.context import CryptContext
from sqlalchemy import event
from starlette.requests import Request

from app.config import settings
from app.services.keys import derive_key
from app.models.user import User
from app.models.user_session import UserSession
from app.routes.auth import (
    LinkRefused, _callback, _create_invite, _link_provider, _oauth_complete, _encode, create_access_token,
)
from app.services import email_service
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


def _login(client, email):
    res = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res


def _cookie(res):
    return res.cookies.get("refresh_token", path="/api/v1/auth/refresh")


def _use_cookie(client, token):
    client.cookies.clear()
    for path in ("/api/v1/auth/refresh", "/api/v1/auth/logout"):
        client.cookies.set("refresh_token", token, path=path)


@pytest.fixture
def sent(monkeypatch):
    mail = []
    monkeypatch.setattr(email_service, "send_email", lambda to, subject, text, html_body=None, reply_to=None: mail.append((to, subject)) or True)
    return mail


def _provider_session(db, user, minutes_ago=0):
    row = UserSession(user_id=user.id, current_jti="j", expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                      provider_signin_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))
    db.add(row)
    db.flush()
    return row, _headers(user, str(row.id))


# ── B6: email change limits and who is told ─────────────────────────────────

def test_the_profile_route_is_rate_limited(client, db):
    user = _user(db, "b6a@test.com")
    codes = [client.patch("/api/v1/auth/me", json={"name": f"N{n}"}, headers=_headers(user)).status_code for n in range(22)]
    assert codes[0] == 200 and 429 in codes


def test_an_account_may_change_its_email_only_so_often_per_hour(client, db, sent, monkeypatch):
    monkeypatch.setattr(settings, "email_changes_per_hour", 2)
    user = _user(db, "b6b@test.com")
    for n in range(2):
        res = client.patch("/api/v1/auth/me", json={"email": f"b6b{n}@test.com", "current_password": PASSWORD}, headers=_headers(user))
        assert res.status_code == 200
    third = client.patch("/api/v1/auth/me", json={"email": "b6b-third@test.com", "current_password": PASSWORD}, headers=_headers(user))
    assert (third.status_code, plain(third)) == (429, {"detail": "You have changed your email too many times. Try again later"})
    db.refresh(user)
    assert user.email == "b6b1@test.com"


def test_and_per_day(client, db, sent, monkeypatch):
    monkeypatch.setattr(settings, "email_changes_per_hour", 100)
    monkeypatch.setattr(settings, "email_changes_per_day", 2)
    user = _user(db, "b6c@test.com")
    for n in range(2):
        assert client.patch("/api/v1/auth/me", json={"email": f"b6c{n}@test.com", "current_password": PASSWORD}, headers=_headers(user)).status_code == 200
    assert client.patch("/api/v1/auth/me", json={"email": "b6c-more@test.com", "current_password": PASSWORD}, headers=_headers(user)).status_code == 429


def test_changes_older_than_the_window_do_not_count(client, db, sent, monkeypatch):
    from app.models.email_change import EmailChange
    monkeypatch.setattr(settings, "email_changes_per_hour", 1)
    monkeypatch.setattr(settings, "email_changes_per_day", 100)
    user = _user(db, "b6d@test.com")
    db.add(EmailChange(user_id=user.id, changed_at=datetime.now(timezone.utc) - timedelta(hours=2)))
    db.flush()
    assert client.patch("/api/v1/auth/me", json={"email": "b6d-new@test.com", "current_password": PASSWORD}, headers=_headers(user)).status_code == 200


def test_the_notice_goes_only_to_an_address_that_has_been_trusted_for_an_hour(client, db, sent, monkeypatch):
    monkeypatch.setattr(settings, "email_changes_per_hour", 100)
    monkeypatch.setattr(settings, "email_changes_per_day", 100)
    # an invited address (email_since is empty) is trusted, so the first change mails it
    user = _user(db, "b6e@test.com")
    for n in range(5):
        res = client.patch("/api/v1/auth/me", json={"email": f"b6e{n}@test.com", "current_password": PASSWORD}, headers=_headers(user))
        assert res.status_code == 200
    # the four after it went to addresses the account had held for seconds, so they are not mailed
    assert sent == [(["b6e@test.com"], "The sign-in address on your PHAEMOS account was changed")]


def test_a_self_registered_address_is_not_mailed_until_it_has_held_for_an_hour(client, db, sent):
    user = _user(db, "b6f@test.com", email_since=datetime.now(timezone.utc) - timedelta(minutes=10))
    client.patch("/api/v1/auth/me", json={"email": "b6f-1@test.com", "current_password": PASSWORD}, headers=_headers(user))
    assert sent == []
    user2 = _user(db, "b6g@test.com", email_since=datetime.now(timezone.utc) - timedelta(hours=2))
    client.patch("/api/v1/auth/me", json={"email": "b6g-1@test.com", "current_password": PASSWORD}, headers=_headers(user2))
    assert [to for to, _ in sent] == [["b6g@test.com"]]


def test_registering_and_changing_set_the_time_the_address_began(client, db, sent):
    res = client.post("/api/v1/auth/register", json={"name": "New", "email": "b6h@test.com", "password": PASSWORD})
    assert res.status_code == 201
    user = db.query(User).filter(User.email == "b6h@test.com").one()
    assert user.email_since is not None
    token = _create_invite(db, "b6i@test.com", "viewer")
    client.post("/api/v1/auth/accept-invite", json={"token": token, "name": "Inv", "password": PASSWORD})
    assert db.query(User).filter(User.email == "b6i@test.com").one().email_since is None


# ── F5: a wrong proof is 400, a bad token is 401 ────────────────────────────

def test_every_route_that_checks_a_proof_answers_400_for_a_wrong_one(client, db):
    secret = pyotp.random_base32()
    pw = _user(db, "f5a@test.com")
    twofa = _user(db, "f5b@test.com", password=None, oauth_provider="google", oauth_id="g-f5", totp_secret=secret, totp_enabled=True)
    wrong_pw = {"current_password": "wrong-password"}
    results = {
        "delete": client.request("DELETE", "/api/v1/auth/me", json={"password": "wrong-password"}, headers=_headers(pw)).status_code,
        "email change": client.patch("/api/v1/auth/me", json={"email": "f5new@test.com", **wrong_pw}, headers=_headers(pw)).status_code,
        "change-password": client.post("/api/v1/auth/change-password", json={"old_password": "wrong-password", "new_password": "Changed123!"}, headers=_headers(pw)).status_code,
        "enable": client.post("/api/v1/auth/2fa/enable", json={"password": "wrong-password"}, headers=_headers(pw)).status_code,
        "confirm": client.post("/api/v1/auth/2fa/confirm", json={"code": "000000"}, headers=_headers(pw)).status_code,
        "disable": client.post("/api/v1/auth/2fa/disable", json={"code": "000000"}, headers=_headers(twofa)).status_code,
    }
    # confirm answers 400 whether the secret was never made ("Call /2fa/enable first") or the code is wrong
    assert results == {name: 400 for name in results}


def test_a_bad_or_missing_token_is_the_only_401(client, db):
    assert client.post("/api/v1/auth/2fa/disable", json={"code": "000000"}).status_code == 401
    assert client.post("/api/v1/auth/2fa/disable", json={"code": "000000"}, headers=_bearer("junk")).status_code == 401


# ── B10: a right proof clears the count ─────────────────────────────────────

def test_a_right_proof_clears_the_wrong_proof_count(client, db, sent):
    user = _user(db, "b10a@test.com")
    for _ in range(3):
        client.patch("/api/v1/auth/me", json={"email": "x@test.com", "current_password": "wrong-password"}, headers=_headers(user))
    db.refresh(user)
    assert user.failed_login_attempts == 3
    ok = client.patch("/api/v1/auth/me", json={"email": "b10a-new@test.com", "current_password": PASSWORD}, headers=_headers(user))
    assert ok.status_code == 200
    db.refresh(user)
    assert user.failed_login_attempts == 0
    # three more typos on another day start from nothing, so they do not lock
    for _ in range(3):
        client.patch("/api/v1/auth/me", json={"email": "y@test.com", "current_password": "wrong-password"}, headers=_headers(user))
    db.refresh(user)
    assert user.failed_login_attempts == 3 and user.locked_until is None


def test_a_change_of_password_and_a_sign_in_clear_the_count(client, db):
    user = _user(db, "b10b@test.com", failed_login_attempts=4)
    assert client.post("/api/v1/auth/change-password", json={"old_password": PASSWORD, "new_password": "Changed123!"}, headers=_headers(user)).status_code == 204
    db.refresh(user)
    assert user.failed_login_attempts == 0
    user.failed_login_attempts = 4
    db.flush()
    assert client.post("/api/v1/auth/login", json={"email": "b10b@test.com", "password": "Changed123!"}).status_code == 200
    db.refresh(user)
    assert user.failed_login_attempts == 0


def test_a_provider_account_cannot_be_locked_through_change_password(client, db):
    user = _user(db, "b10d@test.com", password=None, oauth_provider="github", oauth_id="gh-b10d")
    for _ in range(8):
        res = client.post("/api/v1/auth/change-password", json={"old_password": "anything", "new_password": "Changed123!"}, headers=_headers(user))
        assert (res.status_code, plain(res)) == (400, {"detail": "This account has no password. It signs in through its provider"})
    db.refresh(user)
    assert user.failed_login_attempts == 0 and user.locked_until is None


# ── L3: the refresh grace and the row lock ──────────────────────────────────

def test_a_replay_inside_the_grace_gets_the_same_new_token_back_and_the_session_survives(client, db):
    _user(db, "l3a@test.com")
    first = _cookie(_login(client, "l3a@test.com"))
    second_res = client.post("/api/v1/auth/refresh")
    second = _cookie(second_res)
    assert second != first
    # the second tab presents the token the first one just swapped
    _use_cookie(client, first)
    replay = client.post("/api/v1/auth/refresh")
    assert replay.status_code == 200
    # the same live token again (compared by what it names, since its expiry is stamped when it is issued)
    claims = lambda token: jwt.decode(token, derive_key("refresh"), algorithms=[settings.algorithm])  # noqa: E731
    assert (claims(_cookie(replay))["jti"], claims(_cookie(replay))["sid"]) == (claims(second)["jti"], claims(second)["sid"])
    assert db.query(UserSession).filter(UserSession.revoked_at.is_not(None)).count() == 0
    # and the new token still works
    _use_cookie(client, second)
    assert client.post("/api/v1/auth/refresh").status_code == 200


def test_reuse_after_the_grace_is_theft_and_ends_the_session(client, db):
    _user(db, "l3b@test.com")
    first = _cookie(_login(client, "l3b@test.com"))
    live = _cookie(client.post("/api/v1/auth/refresh"))
    row = db.query(UserSession).one()
    row.rotated_at = datetime.now(timezone.utc) - timedelta(seconds=settings.refresh_grace_seconds + 5)
    db.flush()
    _use_cookie(client, first)
    assert client.post("/api/v1/auth/refresh").status_code == 401
    _use_cookie(client, live)
    assert client.post("/api/v1/auth/refresh").status_code == 401
    db.refresh(row)
    assert row.revoked_at is not None


def test_a_token_two_rotations_old_is_not_forgiven(client, db):
    _user(db, "l3c@test.com")
    first = _cookie(_login(client, "l3c@test.com"))
    client.post("/api/v1/auth/refresh")
    client.post("/api/v1/auth/refresh")
    _use_cookie(client, first)
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_the_refresh_locks_the_session_row(client, db):
    _user(db, "l3d@test.com")
    _login(client, "l3d@test.com")
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    bind = db.get_bind()
    event.listen(bind, "before_cursor_execute", record)
    try:
        assert client.post("/api/v1/auth/refresh").status_code == 200
    finally:
        event.remove(bind, "before_cursor_execute", record)
    assert any("FROM user_sessions" in s and "FOR UPDATE" in s for s in statements)


# ── the cookie lasts no longer than its session ─────────────────────────────

def _max_age(res):
    header = next(h for h in res.headers.get_list("set-cookie") if h.startswith("refresh_token=") and "Max-Age=0" not in h)
    return int(re.search(r"Max-Age=(\d+)", header).group(1))


def test_a_fresh_session_gets_a_seven_day_cookie(client, db):
    _user(db, "l4a@test.com")
    assert abs(_max_age(_login(client, "l4a@test.com")) - 7 * 24 * 3600) < 60


def test_a_session_near_its_end_gets_a_cookie_that_ends_with_it(client, db):
    _user(db, "l4b@test.com")
    _login(client, "l4b@test.com")
    row = db.query(UserSession).one()
    row.created_at = datetime.now(timezone.utc) - timedelta(days=settings.session_max_days) + timedelta(days=2)
    db.flush()
    res = client.post("/api/v1/auth/refresh")
    assert 2 * 24 * 3600 - 120 < _max_age(res) <= 2 * 24 * 3600


# ── L12: the phone number needs proof ───────────────────────────────────────

def test_changing_the_phone_number_needs_the_password(client, db):
    user = _user(db, "p1@test.com")
    res = client.patch("/api/v1/auth/me", json={"phone_number": "+447700900001"}, headers=_headers(user))
    assert (res.status_code, plain(res)) == (400, {"detail": "Enter your current password to change your phone number"})
    db.refresh(user)
    assert user.phone_number is None
    ok = client.patch("/api/v1/auth/me", json={"phone_number": "+447700900001", "current_password": PASSWORD}, headers=_headers(user))
    assert ok.status_code == 200 and ok.json()["phone_number"] == "+447700900001"


def test_sending_the_same_number_again_or_only_a_name_needs_no_proof(client, db):
    user = _user(db, "p2@test.com", phone_number="+447700900002")
    assert client.patch("/api/v1/auth/me", json={"phone_number": "+447700900002"}, headers=_headers(user)).status_code == 200
    assert client.patch("/api/v1/auth/me", json={"name": "Other"}, headers=_headers(user)).status_code == 200
    assert client.patch("/api/v1/auth/me", json={"phone_number": ""}, headers=_headers(_user(db, "p2b@test.com"))).status_code == 200


def test_a_provider_account_changes_its_number_only_from_the_session_that_returned(client, db):
    user = _user(db, "p3@test.com", password=None, oauth_provider="google", oauth_id="g-p3")
    body = {"phone_number": "+447700900003"}
    res = client.patch("/api/v1/auth/me", json=body, headers=_headers(user))
    assert (res.status_code, plain(res)) == (400, {"detail": "Sign in with Google again within the last 5 minutes to change your phone number"})
    _, fresh = _provider_session(db, user)
    assert client.patch("/api/v1/auth/me", json=body, headers=fresh).status_code == 200


def test_a_wrong_password_on_a_phone_change_counts_towards_the_lock(client, db):
    user = _user(db, "p4@test.com")
    for _ in range(5):
        client.patch("/api/v1/auth/me", json={"phone_number": "+447700900004", "current_password": "wrong-password"}, headers=_headers(user))
    assert client.patch("/api/v1/auth/me", json={"phone_number": "+447700900004", "current_password": PASSWORD}, headers=_headers(user)).status_code == 429


# ── ending your own session clears your cookies ─────────────────────────────

def test_ending_the_current_session_clears_both_cookie_copies(client, db):
    _user(db, "d1@test.com")
    res = _login(client, "d1@test.com")
    sid = jwt.decode(res.json()["access_token"], derive_key("access"), algorithms=[settings.algorithm])["sid"]
    ended = client.delete(f"/api/v1/auth/sessions/{sid}", headers=_bearer(res.json()["access_token"]))
    assert ended.status_code == 204
    cleared = sorted(h.split("Path=")[1].split(";")[0] for h in ended.headers.get_list("set-cookie") if h.startswith("refresh_token=") and "Max-Age=0" in h)
    assert cleared == ["/api/v1/auth", "/api/v1/auth/logout", "/api/v1/auth/refresh"]


def test_ending_another_session_leaves_this_browsers_cookies_alone(client, db):
    _user(db, "d2@test.com")
    mine = _login(client, "d2@test.com")
    client.cookies.clear()
    other = _login(client, "d2@test.com")
    other_sid = jwt.decode(other.json()["access_token"], derive_key("access"), algorithms=[settings.algorithm])["sid"]
    ended = client.delete(f"/api/v1/auth/sessions/{other_sid}", headers=_bearer(mine.json()["access_token"]))
    assert ended.status_code == 204
    assert not [h for h in ended.headers.get_list("set-cookie") if h.startswith("refresh_token=")]


# ── checking an invitation without using it ─────────────────────────────────

def test_an_invitation_can_be_checked_without_being_used(client, db):
    token = _create_invite(db, "c1@test.com", "viewer")
    first = client.post("/api/v1/auth/invite/check", json={"token": token})
    assert (first.status_code, first.json()) == (200, {"status": "valid"})
    # checking is not using: it is still valid and the account was not made
    assert client.post("/api/v1/auth/invite/check", json={"token": token}).json() == {"status": "valid"}
    assert db.query(User).filter(User.email == "c1@test.com").first() is None
    client.post("/api/v1/auth/accept-invite", json={"token": token, "name": "C", "password": PASSWORD})
    assert client.post("/api/v1/auth/invite/check", json={"token": token}).json() == {"status": "used"}


def test_a_used_link_stays_used_after_the_account_is_deleted(client, db):
    token = _create_invite(db, "c2@test.com", "viewer")
    client.post("/api/v1/auth/accept-invite", json={"token": token, "name": "C", "password": PASSWORD})
    db.delete(db.query(User).filter(User.email == "c2@test.com").one())
    db.flush()
    assert client.post("/api/v1/auth/invite/check", json={"token": token}).json() == {"status": "used"}


def test_expired_and_garbage_links_answer_expired_and_nothing_about_the_account(client, db):
    from app.models.invitation import Invitation
    old = _create_invite(db, "c3@test.com", "admin")
    db.query(Invitation).filter(Invitation.email == "c3@test.com").update({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    db.flush()
    wrong_type = create_access_token({"sub": "c3@test.com"})
    for token in (old, wrong_type, "not-a-token", ""):
        res = client.post("/api/v1/auth/invite/check", json={"token": token})
        assert (res.status_code, res.json()) == (200, {"status": "expired"})
    assert "c3@test.com" not in client.post("/api/v1/auth/invite/check", json={"token": old}).text


def test_the_check_takes_the_token_in_the_body_only_and_is_rate_limited(client, db):
    token = _create_invite(db, "c4@test.com", "viewer")
    assert client.get(f"/api/v1/auth/invite/check?token={token}").status_code in (404, 405)
    assert client.post(f"/api/v1/auth/invite/check?token={token}").status_code == 422
    codes = [client.post("/api/v1/auth/invite/check", json={"token": token}).status_code for _ in range(32)]
    assert 429 in codes


# ── migrations ──────────────────────────────────────────────────────────────

_MIGRATIONS = REPO / "backend" / "migrations"
_CHANGING = re.compile(r"^\s*(ALTER\s+TABLE|CREATE\s+(UNIQUE\s+)?INDEX|CREATE\s+TABLE)\b", re.I | re.M)


@pytest.mark.skipif(not _MIGRATIONS.is_dir(), reason="backend/migrations is not present in this environment")
@pytest.mark.parametrize("name", [
    "013_ticket_delete_rules.sql", "016_user_sessions.sql", "017_alert_rule_delete_rule.sql", "019_webhook_disabled_reason.sql",
    "022_session_details.sql", "023_used_invites.sql", "024_email_changes.sql", "025_session_rotation.sql",
])
def test_these_migrations_are_conditional_and_have_a_lock_timeout(name):
    sql = (_MIGRATIONS / name).read_text()
    assert re.search(r"^SET lock_timeout = '\d+s';", sql, re.M)
    # every statement that takes a lock sits inside a DO block or a function body, behind a catalogue check
    outside = re.sub(r"\$\$.*?\$\$", "", re.sub(r"--[^\n]*", "", sql), flags=re.S)
    assert not _CHANGING.search(outside), name


# ── the image ───────────────────────────────────────────────────────────────

_DOCKERFILE = REPO / "backend" / "Dockerfile"


@pytest.mark.skipif(not _DOCKERFILE.is_file(), reason="backend/Dockerfile is not present in this environment")
def test_the_image_runs_as_an_unprivileged_user_and_installs_production_requirements_only():
    docker = _DOCKERFILE.read_text()
    assert re.search(r"^USER phaemos$", docker, re.M)
    assert "useradd" in docker and "--uid 10001" in docker
    assert "ARG REQUIREMENTS=requirements.lock" in docker and "--require-hashes" in docker
    # the folders the API writes to belong to that user
    for path in ("/var/lib/phaemos/firmware", "/var/lib/phaemos/model", "/app/firmware_uploads", "/app/ml"):
        assert path in docker
    assert "chown -R phaemos:phaemos" in docker
    prod = (REPO / "backend" / "requirements.txt").read_text()
    for name in ("pytest", "matplotlib"):
        assert not re.search(rf"^{name}\b", prod, re.M)
    dev = (REPO / "backend" / "requirements-dev.txt").read_text()
    assert "-r requirements.txt" in dev and "pytest==" in dev


@pytest.mark.skipif(not (REPO / "infra" / "docker-compose.yml").is_file(), reason="infra is not present in this environment")
def test_development_keeps_the_test_packages_and_root_and_production_does_neither():
    dev = (REPO / "infra" / "docker-compose.yml").read_text()
    assert "REQUIREMENTS: requirements-dev.txt" in dev and "user: '0:0'" in dev
    prod = (REPO / "infra" / "docker-compose.prod.yml").read_text()
    assert "requirements-dev" not in prod and "user: '0:0'" not in prod


# ── linking a provider to a password account ────────────────────────────────

def _request_with_cookies(**cookies):
    header = "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()
    return Request({"type": "http", "headers": [(b"cookie", header)], "client": ("127.0.0.1", 1), "method": "GET", "path": "/"})


def _link_cookie(user, sid, provider="google", **override):
    claims = {"sub": str(user.id), "ver": user.token_version or 0, "sid": sid, "prov": provider}
    claims.update(override)
    return _encode(claims, "link", timedelta(minutes=10))


def test_starting_a_link_needs_the_password_and_a_code_when_two_step_is_on(client, db, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "google-client")
    user = _user(db, "k1@test.com")
    none = client.post("/api/v1/auth/link/google", headers=_headers(user))
    assert (none.status_code, plain(none)) == (400, {"detail": "Enter your current password to link Google"})
    assert client.post("/api/v1/auth/link/google", json={"password": "wrong-password"}, headers=_headers(user)).status_code == 400
    ok = client.post("/api/v1/auth/link/google", json={"password": PASSWORD}, headers=_headers(user))
    assert ok.status_code == 200
    assert ok.json()["authorize_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "state=" in ok.json()["authorize_url"]
    # the state cookie and the signed link cookie are set, so the callback can check both
    names = {h.split("=")[0] for h in ok.headers.get_list("set-cookie")}
    assert {"oauth_state", "oauth_link"} <= names
    secret = pyotp.random_base32()
    guarded = _user(db, "k1b@test.com", totp_secret=secret, totp_enabled=True)
    only_password = client.post("/api/v1/auth/link/google", json={"password": PASSWORD}, headers=_headers(guarded))
    assert plain(only_password) == {"detail": "Enter a current two-step code to link Google"}
    both = client.post("/api/v1/auth/link/google", json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()}, headers=_headers(guarded))
    assert both.status_code == 200


def test_the_start_refuses_what_cannot_be_linked(client, db, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "google-client")
    monkeypatch.setattr(settings, "github_client_id", "")
    user = _user(db, "k2@test.com")
    body = {"password": PASSWORD}
    assert client.post("/api/v1/auth/link/microsoft", json=body, headers=_headers(user)).status_code == 400
    assert client.post("/api/v1/auth/link/github", json=body, headers=_headers(user)).status_code == 501
    provider_only = _user(db, "k2b@test.com", password=None, oauth_provider="google", oauth_id="g-k2b")
    assert client.post("/api/v1/auth/link/google", json=body, headers=_headers(provider_only)).status_code == 400
    linked = _user(db, "k2c@test.com", oauth_provider="google", oauth_id="g-k2c")
    assert client.post("/api/v1/auth/link/google", json=body, headers=_headers(linked)).status_code == 409
    assert client.post("/api/v1/auth/link/google", json=body).status_code == 401


def test_a_verified_provider_address_equal_to_the_accounts_links_it(db):
    user = _user(db, "k3@test.com")
    row = UserSession(user_id=user.id, current_jti="j", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    db.add(row)
    db.flush()
    linked = _link_provider(db, _link_cookie(user, str(row.id)), "K3@Test.com", "google", "g-k3")
    assert linked.id == user.id and (linked.oauth_provider, linked.oauth_id) == ("google", "g-k3")
    # and the account still has its password
    assert linked.password_hash


def _refuses(db, token, email="k4@test.com", provider="google", provider_id="g-new", status=400):
    with pytest.raises(HTTPException) as refused:
        _link_provider(db, token, email, provider, provider_id)
    assert refused.value.status_code == status
    return refused.value.detail


def test_the_takeover_cases_are_refused(db):
    victim = _user(db, "k4@test.com")
    row = UserSession(user_id=victim.id, current_jti="j", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    db.add(row)
    db.flush()
    good = _link_cookie(victim, str(row.id))
    # an attacker's provider account at another address cannot be attached to the victim's account
    assert "not the address of this account" in _refuses(db, good, email="attacker@test.com")
    # a link cookie that was not made by this server or has expired
    assert "expired" in _refuses(db, "forged")
    stale = _encode({"sub": str(victim.id), "ver": 0, "sid": str(row.id), "prov": "google"}, "link", timedelta(seconds=-5))
    assert "expired" in _refuses(db, stale)
    # a cookie for another provider than the one that came back
    assert "different provider" in _refuses(db, _link_cookie(victim, str(row.id), provider="github"))
    # a signed-out session or one that was never this account's
    row.revoked_at = datetime.now(timezone.utc)
    db.flush()
    _refuses(db, good, status=401)
    # a provider identity already attached to another account
    other = _user(db, "k4b@test.com", password=None, oauth_provider="google", oauth_id="g-taken")
    row.revoked_at = None
    db.flush()
    assert "already linked to another account" in _refuses(db, good, provider_id="g-taken", status=409)
    assert other.oauth_id == "g-taken"
    db.refresh(victim)
    assert victim.oauth_provider is None
    # an account that has signed out everywhere since asking (its session version moved on)
    victim.token_version = 1
    db.flush()
    _refuses(db, good, status=401)


def test_a_link_cookie_for_a_provider_only_account_or_a_linked_one_is_refused(db):
    provider_only = _user(db, "k5@test.com", password=None, oauth_provider="google", oauth_id="g-k5")
    assert "already linked" in _refuses(db, _link_cookie(provider_only, None), email="k5@test.com", status=409)


def test_the_callback_links_when_the_cookie_is_there_and_signs_in_when_it_is_not(db):
    user = _user(db, "k6@test.com")
    row = UserSession(user_id=user.id, current_jti="j", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    db.add(row)
    db.flush()
    request = _request_with_cookies(oauth_link=_link_cookie(user, str(row.id)))
    response = _oauth_complete(db, request, "k6@test.com", "K6", "google", "g-k6")
    assert response.status_code in (302, 307) and "linked=google" in response.headers["location"]
    # a link signs nobody in: no refresh cookie is set
    assert not [h for h in response.headers.getlist("set-cookie") if h.startswith("refresh_token=")]
    db.refresh(user)
    assert user.oauth_provider == "google"
    # without the cookie the ordinary sign-in runs and the account now signs in by its provider identity
    plain = _oauth_complete(db, _request_with_cookies(), "k6@test.com", "K6", "google", "g-k6")
    assert "step=oauth" in plain.headers["location"]


def test_without_the_link_cookie_an_address_match_still_does_not_link_a_password_account(db):
    from app.routes.auth import _oauth_upsert
    _user(db, "k7@test.com")
    with pytest.raises(HTTPException) as refused:
        _oauth_upsert(db, "k7@test.com", "K7", "google", "g-k7")
    assert refused.value.status_code == 409


# ── a refused link goes back to the profile page with a fixed code ──────────

def _run(coro):
    import asyncio
    return asyncio.run(coro)


def _refusing(exc):
    async def run():
        raise exc
    return run


@pytest.mark.parametrize("exc,code", [
    (LinkRefused(400, "The address at Google is not the address of this account", "address_mismatch"), "address_mismatch"),
    (LinkRefused(409, "That provider account is already linked to another account", "identity_in_use"), "identity_in_use"),
    (LinkRefused(400, "The link request expired. Start again from your profile", "expired"), "expired"),
    (LinkRefused(400, "Your Google account email is not verified", "provider_unverified"), "provider_unverified"),
    (HTTPException(401, "Session is no longer valid"), "expired"),
    (HTTPException(400, "Sign-in expired or was not started here. Try again."), "failed"),
    (HTTPException(409, "A provider is already linked to this account"), "failed"),
    (RuntimeError("the provider's server fell over, for someone@example.com"), "failed"),
])
def test_a_refused_link_redirects_to_the_profile_with_a_short_code_and_nothing_else(exc, code):
    request = _request_with_cookies(oauth_link="signed-cookie-value")
    response = _run(_callback(request, "code-123", None, _refusing(exc)))
    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.endswith(f"/profile?link_error={code}")
    # no detail, address, identity or token ever reaches the address
    for secret in ("@", "someone", "signed-cookie-value", "code-123", "Google", "g-"):
        assert secret not in location
    cleared = [h for h in response.headers.getlist("set-cookie") if "Max-Age=0" in h]
    assert {h.split("=")[0] for h in cleared} == {"oauth_link", "oauth_state"}


def test_declining_at_the_provider_is_cancelled_and_any_other_provider_error_is_failed():
    request = _request_with_cookies(oauth_link="x")
    declined = _run(_callback(request, None, "access_denied", _refusing(AssertionError("never runs"))))
    assert declined.headers["location"].endswith("/profile?link_error=cancelled")
    other = _run(_callback(request, None, "server_error", _refusing(AssertionError("never runs"))))
    assert other.headers["location"].endswith("/profile?link_error=failed")
    nothing = _run(_callback(request, None, None, _refusing(AssertionError("never runs"))))
    assert nothing.headers["location"].endswith("/profile?link_error=failed")


def test_the_sign_in_callback_keeps_its_own_errors():
    plain = _request_with_cookies()
    with pytest.raises(LinkRefused):
        _run(_callback(plain, "code", None, _refusing(LinkRefused(400, "Your Google account email is not verified", "provider_unverified"))))
    with pytest.raises(HTTPException) as missing:
        _run(_callback(plain, None, "access_denied", _refusing(AssertionError("never runs"))))
    assert missing.value.status_code == 422
    with pytest.raises(RuntimeError):
        _run(_callback(plain, "code", None, _refusing(RuntimeError("boom"))))


def test_a_successful_callback_is_returned_untouched():
    async def fine():
        return "the real response"
    assert _run(_callback(_request_with_cookies(oauth_link="x"), "code", None, fine)) == "the real response"


def test_the_callback_route_redirects_when_the_person_declines_while_linking(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "google-client")
    client.cookies.set("oauth_link", "signed", path="/api/v1/auth")
    res = client.get("/api/v1/auth/google/callback?error=access_denied&state=s", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"].endswith("/profile?link_error=cancelled")
    client.cookies.clear()
    # a plain sign-in callback with an error is still the API's own 422
    assert client.get("/api/v1/auth/google/callback?error=access_denied", follow_redirects=False).status_code == 422


# ── what counts as a change of the phone number ─────────────────────────────

@pytest.mark.parametrize("stored,sent", [
    ("+447700900000", "+447700900000"),
    # the same number written another way
    ("+447700900000", "+44 7700 900000"),
    ("+447700900000", "+44-7700-900000"),
    ("+44 7700 900000", "+447700900000"),
    ("447700900000", "+447700900000"),
    # no number stored and nothing or an empty value sent
    (None, ""),
    ("", ""),
    ("", "   "),
])
def test_sending_the_same_number_in_another_format_needs_no_proof(client, db, stored, sent):
    user = _user(db, f"ph{abs(hash((stored, sent)))}@test.com", phone_number=stored)
    res = client.patch("/api/v1/auth/me", json={"phone_number": sent, "name": "Same Person"}, headers=_headers(user))
    assert res.status_code == 200, res.text


def test_no_phone_number_sent_needs_no_proof(client, db):
    user = _user(db, "ph-none@test.com", phone_number="+447700900000")
    assert client.patch("/api/v1/auth/me", json={"name": "Only A Name"}, headers=_headers(user)).status_code == 200
    assert client.patch("/api/v1/auth/me", json={}, headers=_headers(user)).status_code == 200


@pytest.mark.parametrize("stored,sent", [
    ("+447700900000", "+447700900001"),
    ("+447700900000", ""),
    (None, "+447700900000"),
    ("", "+447700900000"),
    ("447700900000", "+447700900009"),
])
def test_a_different_number_or_clearing_it_needs_the_password(client, db, stored, sent):
    user = _user(db, f"phc{abs(hash((stored, sent)))}@test.com", phone_number=stored)
    res = client.patch("/api/v1/auth/me", json={"phone_number": sent}, headers=_headers(user))
    assert (res.status_code, plain(res)) == (400, {"detail": "Enter your current password to change your phone number"})
    ok = client.patch("/api/v1/auth/me", json={"phone_number": sent, "current_password": PASSWORD}, headers=_headers(user))
    assert ok.status_code == 200


# ── the dashboard may read Date across origins ──────────────────────────────

def test_the_date_header_is_exposed_to_the_dashboard_origin(client):
    res = client.get("/", headers={"Origin": "http://localhost:3000"})
    exposed = [h.strip().lower() for h in res.headers["access-control-expose-headers"].split(",")]
    assert "date" in exposed and "x-total-count" in exposed
