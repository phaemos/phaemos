"""
Sign-in sessions kept on the server, proof of ownership for sensitive changes, the paging caps and
the other fixes to the account work.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
import pytest
from fastapi import HTTPException
from passlib.context import CryptContext
from sqlalchemy import text

from app.config import settings
from app.services.keys import derive_key
from app.models.alert import Alert, AlertRule
from app.models.device import Device
from app.models.maintenance import MaintenanceWindow
from app.models.ticket import Ticket
from app.models.user import User
from app.models.user_session import UserSession
from app.routes.auth import _identity, _oauth_finish, _oauth_upsert, create_refresh_token
from tests._shape import plain

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD = "Passw0rd!x"


def _headers(user):
    from app.routes.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'role': user.role})}"}


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _user(db, email, role="technician", name=None, password=PASSWORD, **extra):
    u = User(name=name or email.split("@")[0], email=email, role=role,
             password_hash=_pwd_ctx.hash(password) if password else None, **extra)
    db.add(u)
    db.flush()
    return u


def _device(db, name="Node", owner=None):
    d = Device(name=name, location="Lab", type="esp32", api_key=secrets.token_urlsafe(32),
               owner_id=owner.id if owner else None)
    db.add(d)
    db.flush()
    return d


def _provider_session(db, user, minutes_ago=0):
    """A session that came back from the provider this long ago: (row, headers of an access token for it)."""
    from app.routes.auth import create_access_token
    row = UserSession(
        user_id=user.id, current_jti="j", expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        provider_signin_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(row)
    db.flush()
    return row, _bearer(create_access_token(_identity(user, str(row.id))))


def _login(client, email, password=PASSWORD):
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res


_REFRESH_PATHS = ("/api/v1/auth/refresh", "/api/v1/auth/logout")


def _refresh_cookie(res):
    # the refresh cookie is set once for each route that reads it, so it is picked by path
    return res.cookies.get("refresh_token", path="/api/v1/auth/refresh")


def _use_cookie(client, token):
    client.cookies.clear()
    if token:
        for path in _REFRESH_PATHS:
            client.cookies.set("refresh_token", token, path=path)


# ── sessions: refresh, rotation, logout ─────────────────────────────────────

def test_login_starts_a_server_side_session_named_in_both_tokens(client, db):
    user = _user(db, "s1@test.com")
    res = _login(client, "s1@test.com")
    claims = jwt.decode(res.json()["access_token"], derive_key("access"), algorithms=[settings.algorithm])
    refresh = jwt.decode(_refresh_cookie(res), derive_key("refresh"), algorithms=[settings.algorithm])
    assert claims["sid"] == refresh["sid"] and refresh["jti"]
    row = db.query(UserSession).filter(UserSession.id == uuid.UUID(claims["sid"])).one()
    assert row.user_id == user.id and row.revoked_at is None and row.current_jti == refresh["jti"]


def test_the_refresh_cookie_is_sent_to_the_refresh_and_logout_routes_only(client, db):
    _user(db, "s2@test.com")
    res = _login(client, "s2@test.com")
    paths = sorted(c.path for c in client.cookies.jar if c.name == "refresh_token")
    assert paths == sorted(_REFRESH_PATHS)
    headers = [h for h in res.headers.get_list("set-cookie") if h.startswith("refresh_token=")]
    # the wider copy an earlier version set is cleared in the same reply
    cleared = [h for h in headers if "Path=/api/v1/auth;" in h and "Max-Age=0" in h]
    assert len(cleared) == 1
    # both live copies carry the same value
    assert len({h.split(";")[0] for h in headers if "Max-Age=0" not in h}) == 1


def test_each_refresh_swaps_the_token_and_the_old_one_stops_working(client, db):
    _user(db, "s3@test.com")
    first = _refresh_cookie(_login(client, "s3@test.com"))
    second_res = client.post("/api/v1/auth/refresh")
    assert second_res.status_code == 200
    second = _refresh_cookie(second_res)
    assert second != first
    assert second_res.json()["access_token"]
    # the newest token works
    assert client.post("/api/v1/auth/refresh").status_code == 200


def test_presenting_a_rotated_token_is_treated_as_theft_and_ends_the_session(client, db, monkeypatch):
    # past the short grace. Inside it a replay is tolerated, which test_email_limits_and_account_linking covers
    monkeypatch.setattr(settings, "refresh_grace_seconds", 0)
    _user(db, "s4@test.com")
    stolen = _refresh_cookie(_login(client, "s4@test.com"))
    live = _refresh_cookie(client.post("/api/v1/auth/refresh"))
    # the thief replays the older token
    _use_cookie(client, stolen)
    assert client.post("/api/v1/auth/refresh").status_code == 401
    # which also stops the newer one, because the session is revoked
    _use_cookie(client, live)
    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert db.query(UserSession).filter(UserSession.revoked_at.is_not(None)).count() == 1


def test_logout_revokes_the_session_so_a_copied_refresh_token_stops_working(client, db):
    _user(db, "s5@test.com")
    copied = _refresh_cookie(_login(client, "s5@test.com"))
    assert client.post("/api/v1/auth/logout").status_code == 204
    _use_cookie(client, copied)
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_needs_only_the_cookie_not_an_access_token(client, db):
    _user(db, "s6@test.com")
    cookie = _refresh_cookie(_login(client, "s6@test.com"))
    # no Authorization header at all, as when the access token has expired
    _use_cookie(client, cookie)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert db.query(UserSession).filter(UserSession.revoked_at.is_not(None)).count() == 1


def test_logout_with_no_cookie_or_a_bad_one_still_answers_204(client):
    assert client.post("/api/v1/auth/logout").status_code == 204
    _use_cookie(client, "not-a-token")
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_logout_ends_one_session_and_leaves_the_others(client, db):
    _user(db, "s7@test.com")
    one = _refresh_cookie(_login(client, "s7@test.com"))
    client.cookies.clear()
    two = _refresh_cookie(_login(client, "s7@test.com"))
    _use_cookie(client, one)
    client.post("/api/v1/auth/logout")
    _use_cookie(client, two)
    assert client.post("/api/v1/auth/refresh").status_code == 200


def test_an_access_token_from_a_signed_out_session_stops_working_at_once(client, db):
    _user(db, "s8@test.com")
    res = _login(client, "s8@test.com")
    access = res.json()["access_token"]
    assert client.get("/api/v1/auth/me", headers=_bearer(access)).status_code == 200
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me", headers=_bearer(access)).status_code == 401


def test_a_refresh_token_without_a_session_is_refused(client, db):
    user = _user(db, "s9@test.com")
    _use_cookie(client, create_refresh_token(_identity(user)))
    assert client.post("/api/v1/auth/refresh").status_code == 401
    # one that names a session that does not exist
    _use_cookie(client, create_refresh_token({**_identity(user, str(uuid.uuid4())), "jti": "x"}))
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_an_expired_session_cannot_refresh(client, db):
    _user(db, "s10@test.com")
    res = _login(client, "s10@test.com")
    sid = jwt.decode(_refresh_cookie(res), derive_key("refresh"), algorithms=[settings.algorithm])["sid"]
    row = db.query(UserSession).filter(UserSession.id == uuid.UUID(sid)).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_a_password_change_revokes_every_session_row_and_starts_a_new_one(client, db):
    user = _user(db, "s11@test.com")
    old = _login(client, "s11@test.com")
    res = client.post(
        "/api/v1/auth/change-password",
        json={"old_password": PASSWORD, "new_password": "Changed123!"},
        headers=_bearer(old.json()["access_token"]),
    )
    assert res.status_code == 204
    rows = db.query(UserSession).filter(UserSession.user_id == user.id).all()
    assert len(rows) == 2
    assert sum(1 for r in rows if r.revoked_at is None) == 1
    # the cookie this browser got works
    assert client.post("/api/v1/auth/refresh").status_code == 200


def test_sessions_are_removed_with_the_account_by_the_database(db):
    user = _user(db, "s12@test.com")
    db.add(UserSession(user_id=user.id, current_jti="j", expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    db.flush()
    db.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(user.id)})
    assert db.query(UserSession).filter(UserSession.user_id == user.id).count() == 0


def test_the_socket_check_refuses_a_token_from_a_revoked_session(client, db):
    from app.routes.auth import decode_token, user_for_token
    _user(db, "s13@test.com")
    token = _login(client, "s13@test.com").json()["access_token"]
    client.post("/api/v1/auth/logout")
    with pytest.raises(HTTPException):
        user_for_token(db, decode_token(token, "access"))


# ── proof of ownership ──────────────────────────────────────────────────────

def test_changing_the_email_needs_the_current_password(client, db):
    user = _user(db, "p1@test.com")
    missing = client.patch("/api/v1/auth/me", json={"email": "new@test.com"}, headers=_headers(user))
    assert (missing.status_code, plain(missing)) == (400, {"detail": "Enter your current password to change your email"})
    wrong = client.patch("/api/v1/auth/me", json={"email": "new@test.com", "current_password": "wrong-password"}, headers=_headers(user))
    assert wrong.status_code == 400
    db.refresh(user)
    assert user.email == "p1@test.com" and user.failed_login_attempts == 1
    ok = client.patch("/api/v1/auth/me", json={"email": "new@test.com", "current_password": PASSWORD}, headers=_headers(user))
    assert ok.status_code == 200 and ok.json()["email"] == "new@test.com"
    # the proof fields are never stored or returned
    assert "current_password" not in ok.text


def test_other_profile_changes_need_no_proof(client, db):
    # a name change, with the number this account already has sent again, needs no proof
    user = _user(db, "p2@test.com", phone_number="+447700900000")
    res = client.patch("/api/v1/auth/me", json={"name": "New Name", "phone_number": "+447700900000"}, headers=_headers(user))
    assert res.status_code == 200 and res.json()["name"] == "New Name"
    same = client.patch("/api/v1/auth/me", json={"email": "p2@test.com"}, headers=_headers(user))
    assert same.status_code == 200


def test_a_provider_account_cannot_change_its_email_at_all(client, db):
    user = _user(db, "p3@test.com", password=None, oauth_provider="google", oauth_id="g-p3")
    _, fresh = _provider_session(db, user)
    res = client.patch("/api/v1/auth/me", json={"email": "elsewhere@test.com"}, headers=fresh)
    assert (res.status_code, plain(res)) == (403, {"detail": "Your email comes from Google and cannot be changed here"})
    db.refresh(user)
    assert user.email == "p3@test.com"


def test_wrong_passwords_on_a_sensitive_route_lock_the_account(client, db):
    user = _user(db, "p4@test.com")
    codes = [
        client.patch("/api/v1/auth/me", json={"email": "x@test.com", "current_password": "wrong-password"}, headers=_headers(user)).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [400] * 5 and codes[5] == 429


def test_takeover_by_changing_the_email_then_signing_in_with_a_provider_is_closed(client, db):
    # the attack sequence: a stolen token moves the victim's account to the attacker's address,
    # then the attacker signs in with a provider account on that address
    victim = _user(db, "victim@test.com")
    moved = client.patch("/api/v1/auth/me", json={"email": "attacker@test.com"}, headers=_headers(victim))
    assert moved.status_code == 400
    db.refresh(victim)
    assert victim.email == "victim@test.com"
    with pytest.raises(HTTPException) as refused:
        _oauth_upsert(db, "victim@test.com", "Attacker", "google", "attacker-google-id")
    assert refused.value.status_code == 409


def test_oauth_finds_the_account_by_provider_identity_first(db):
    user = _user(db, "o1@test.com", password=None, oauth_provider="github", oauth_id="gh-o1")
    # the address at the provider changed. The same identity still reaches the same account
    assert _oauth_upsert(db, "renamed@test.com", "Same", "github", "gh-o1").id == user.id
    assert db.query(User).filter(User.email == "renamed@test.com").first() is None


def test_oauth_links_by_email_only_to_an_account_with_no_password_and_no_provider(db):
    bare = _user(db, "o2@test.com", password=None)
    assert _oauth_upsert(db, "o2@test.com", "Bare", "google", "g-o2").id == bare.id
    assert bare.oauth_provider == "google" and bare.oauth_id == "g-o2"


@pytest.mark.parametrize("extra", [{"password": PASSWORD}, {"password": None, "oauth_provider": "github", "oauth_id": "gh-x"}])
def test_oauth_refuses_to_link_to_an_account_with_a_password_or_another_provider(db, extra):
    _user(db, "o3@test.com", **extra)
    with pytest.raises(HTTPException) as refused:
        _oauth_upsert(db, "o3@test.com", "Someone", "google", "g-o3")
    assert refused.value.status_code == 409
    assert "already uses this email" in refused.value.detail


def test_returning_from_a_provider_records_the_time_on_that_session_only(client, db):
    user = _user(db, "o4@test.com", password=None, oauth_provider="google", oauth_id="g-o4")
    _oauth_finish(db, user)
    own = db.query(UserSession).filter(UserSession.user_id == user.id).one()
    assert own.provider_signin_at is not None
    from app.routes.auth import create_access_token
    owner = _bearer(create_access_token(_identity(user, str(own.id))))
    assert client.get("/api/v1/auth/me", headers=owner).json()["provider_signin_recent"] is True
    own.provider_signin_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    db.flush()
    assert client.get("/api/v1/auth/me", headers=owner).json()["provider_signin_recent"] is False


def test_a_stolen_token_cannot_use_the_owners_provider_sign_in(client, db):
    # the attack sequence: the thief's token belongs to another session of the same account
    user = _user(db, "o5@test.com", password=None, oauth_provider="google", oauth_id="g-o5")
    thief_row = UserSession(user_id=user.id, current_jti="t", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    db.add(thief_row)
    db.flush()
    from app.routes.auth import create_access_token
    thief = _bearer(create_access_token(_identity(user, str(thief_row.id))))
    assert client.get("/api/v1/auth/me", headers=thief).json()["provider_signin_recent"] is False
    # the owner returns from Google on their own device
    _, owner = _provider_session(db, user)
    assert client.get("/api/v1/auth/me", headers=owner).json()["provider_signin_recent"] is True
    # the thief's token still sees nothing and every proof route still refuses it
    assert client.get("/api/v1/auth/me", headers=thief).json()["provider_signin_recent"] is False
    assert client.post("/api/v1/auth/2fa/enable", headers=thief).status_code == 400
    assert client.request("DELETE", "/api/v1/auth/me", headers=thief).status_code == 400
    db.refresh(user)
    assert user.totp_secret is None
    # the owner's own token passes
    assert client.post("/api/v1/auth/2fa/enable", headers=owner).status_code == 200


def test_two_step_enrolment_needs_the_password(client, db):
    user = _user(db, "t1@test.com")
    none = client.post("/api/v1/auth/2fa/enable", headers=_headers(user))
    assert (none.status_code, plain(none)) == (400, {"detail": "Enter your current password to turn on two-step sign-in"})
    assert client.post("/api/v1/auth/2fa/enable", headers=_headers(user), json={"password": "wrong-password"}).status_code == 400
    db.refresh(user)
    assert user.totp_secret is None
    ok = client.post("/api/v1/auth/2fa/enable", headers=_headers(user), json={"password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["secret"]


def test_two_step_enrolment_for_a_provider_account_needs_a_recent_provider_sign_in(client, db):
    user = _user(db, "t2@test.com", password=None, oauth_provider="github", oauth_id="gh-t2")
    res = client.post("/api/v1/auth/2fa/enable", headers=_headers(user))
    assert (res.status_code, plain(res)) == (400, {"detail": "Sign in with GitHub again within the last 5 minutes to turn on two-step sign-in"})
    _, fresh = _provider_session(db, user)
    assert client.post("/api/v1/auth/2fa/enable", headers=fresh).status_code == 200


def test_the_confirm_code_travels_in_the_body_and_the_query_form_is_gone(client, db):
    user = _user(db, "t3@test.com")
    secret = client.post("/api/v1/auth/2fa/enable", headers=_headers(user), json={"password": PASSWORD}).json()["secret"]
    code = pyotp.TOTP(secret).now()
    # the query string reaches proxy logs, so it is no longer read
    assert client.post(f"/api/v1/auth/2fa/confirm?code={code}", headers=_headers(user)).status_code == 400
    res = client.post("/api/v1/auth/2fa/confirm", headers=_headers(user), json={"code": code})
    assert res.status_code == 200
    # confirming ended the other sessions, so the old token is refused. The fresh one gets the 409
    assert client.post("/api/v1/auth/2fa/confirm", headers=_headers(user), json={"code": "000000"}).status_code == 401
    fresh = _bearer(res.json()["access_token"])
    assert client.post("/api/v1/auth/2fa/confirm", headers=fresh, json={"code": "000000"}).status_code == 409


def test_turning_two_step_off_needs_the_password_as_well_as_the_code(client, db):
    secret = pyotp.random_base32()
    user = _user(db, "t4@test.com", totp_secret=secret, totp_enabled=True)
    code = pyotp.TOTP(secret).now()
    no_password = client.post("/api/v1/auth/2fa/disable", headers=_headers(user), json={"code": code})
    assert (no_password.status_code, plain(no_password)) == (400, {"detail": "Enter your current password to turn off two-step sign-in"})
    db.refresh(user)
    assert user.totp_enabled is True
    ok = client.post("/api/v1/auth/2fa/disable", headers=_headers(user), json={"password": PASSWORD, "code": pyotp.TOTP(secret).at(datetime.now(timezone.utc) + timedelta(seconds=30))})
    assert ok.status_code == 200


def test_a_provider_account_turns_two_step_off_with_just_the_code(client, db):
    secret = pyotp.random_base32()
    user = _user(db, "t5@test.com", password=None, oauth_provider="google", oauth_id="g-t5", totp_secret=secret, totp_enabled=True)
    res = client.post("/api/v1/auth/2fa/disable", headers=_headers(user), json={"code": pyotp.TOTP(secret).now()})
    assert res.status_code == 200


# ── paging caps ─────────────────────────────────────────────────────────────

def test_lists_reject_negative_paging_and_cap_their_limits(client, db):
    admin = _user(db, "c1@test.com", "admin")
    device = _device(db)
    for path in (
        "/api/v1/auth/users?limit=201", "/api/v1/auth/users?skip=-1", "/api/v1/auth/users?limit=0",
        "/api/v1/audit-logs?limit=501", "/api/v1/audit-logs?skip=-1",
        f"/api/v1/ml/anomalies/{device.id}?limit=1001", f"/api/v1/ml/anomalies/{device.id}?limit=-1",
        "/api/v1/tickets?limit=201", "/api/v1/tickets?skip=-1",
        f"/api/v1/alerts?device_id={device.id}&limit=501", f"/api/v1/alerts?device_id={device.id}&offset=-1",
    ):
        assert client.get(path, headers=_headers(admin)).status_code == 422, path
    for path in ("/api/v1/auth/users?limit=200", "/api/v1/audit-logs?limit=500", "/api/v1/tickets?limit=200"):
        assert client.get(path, headers=_headers(admin)).status_code == 200, path


def test_alerts_for_one_machine_page_and_count(client, db):
    admin = _user(db, "c2@test.com", "admin")
    device = _device(db)
    for _ in range(7):
        db.add(Alert(device_id=device.id, message="hot", severity="warning", resolved=False))
    db.flush()
    res = client.get(f"/api/v1/alerts?device_id={device.id}&limit=3&offset=2", headers=_headers(admin))
    assert (len(res.json()), res.headers["X-Total-Count"]) == (3, "7")
    assert len(client.get(f"/api/v1/alerts?device_id={device.id}", headers=_headers(admin)).json()) == 7


# ── tickets whose machine was deleted ───────────────────────────────────────

def _ticket(db, device=None, alert=None, created_by=None, assigned_to=None, **extra):
    t = Ticket(device_id=device.id if device else None, alert_id=alert.id if alert else None,
               created_by=created_by.id if created_by else None, assigned_to=assigned_to.id if assigned_to else None,
               title="Check it", description="Details", status="open", priority="low", **extra)
    db.add(t)
    db.flush()
    return t


def test_a_ticket_that_lost_its_machine_is_not_opened_to_every_technician(client, db):
    admin = _user(db, "m1a@test.com", "admin")
    viewer = _user(db, "m1v@test.com", "viewer")
    owner = _user(db, "m1o@test.com")
    assignee = _user(db, "m1s@test.com")
    other = _user(db, "m1x@test.com")
    machine = _device(db, owner=owner)
    ticket = _ticket(db, device=machine, created_by=owner, assigned_to=assignee)
    # an admin deletes the machine and the key sets the ticket's machine to nothing
    db.execute(text("DELETE FROM devices WHERE id = :id"), {"id": str(machine.id)})
    db.expire_all()
    assert db.query(Ticket).filter(Ticket.id == ticket.id).one().device_id is None

    def sees(user):
        listed = {t["id"] for t in client.get("/api/v1/tickets", headers=_headers(user)).json()}
        single = client.get(f"/api/v1/tickets/{ticket.id}", headers=_headers(user)).status_code
        assert (str(ticket.id) in listed) == (single == 200)
        return single == 200

    assert [sees(u) for u in (admin, viewer, owner, assignee)] == [True, True, True, True]
    assert sees(other) is False
    assert client.patch(f"/api/v1/tickets/{ticket.id}", json={"status": "closed"}, headers=_headers(other)).status_code == 404
    assert client.patch(f"/api/v1/tickets/{ticket.id}", json={"status": "in_progress"}, headers=_headers(owner)).status_code == 200
    assert client.patch(f"/api/v1/tickets/{ticket.id}", json={"status": "closed"}, headers=_headers(viewer)).status_code == 403
    # the total count follows the same rule
    assert client.get("/api/v1/tickets", headers=_headers(other)).headers["X-Total-Count"] == "0"
    assert client.get("/api/v1/tickets", headers=_headers(owner)).headers["X-Total-Count"] == "1"


def test_a_ticket_made_from_an_alert_alone_takes_the_alert_machine(client, db):
    tech = _user(db, "m2@test.com")
    machine = _device(db, owner=tech)
    alert = Alert(device_id=machine.id, message="hot", severity="warning", resolved=False)
    db.add(alert)
    db.flush()
    res = client.post("/api/v1/tickets", json={"title": "From alert", "alert_id": str(alert.id)}, headers=_headers(tech))
    assert res.status_code == 201
    assert res.json()["device_id"] == str(machine.id)


def test_a_ticket_goes_only_to_someone_who_can_open_it(client, db):
    admin = _user(db, "m3a@test.com", "admin")
    owner = _user(db, "m3o@test.com")
    other = _user(db, "m3x@test.com")
    viewer = _user(db, "m3v@test.com", "viewer")
    ticket = _ticket(db, device=_device(db, owner=owner))
    for person in (other, viewer):
        res = client.patch(f"/api/v1/tickets/{ticket.id}", json={"assigned_to": str(person.id)}, headers=_headers(admin))
        assert (res.status_code, plain(res)) == (422, {"detail": "That person cannot be given this ticket"})
    assert client.patch(f"/api/v1/tickets/{ticket.id}", json={"assigned_to": str(owner.id)}, headers=_headers(admin)).status_code == 200


# ── alert rules with alerts and the other foreign keys ─────────────────────

def test_the_alert_rule_key_keeps_the_alert():
    (key,) = Alert.__table__.c.rule_id.foreign_keys
    assert key.ondelete == "SET NULL"


def test_a_rule_that_has_fired_can_be_deleted_and_its_alerts_stay(client, db):
    admin = _user(db, "r1@test.com", "admin")
    device = _device(db)
    rule = AlertRule(for_seconds=0, device_id=device.id, metric="temperature", condition="gt", threshold=1.0, severity="warning")
    db.add(rule)
    db.flush()
    alert = Alert(device_id=device.id, rule_id=rule.id, message="hot", severity="warning", resolved=False)
    db.add(alert)
    db.flush()
    assert client.delete(f"/api/v1/alert-rules/{rule.id}", headers=_headers(admin)).status_code == 204
    db.expire_all()
    assert db.query(Alert).filter(Alert.id == alert.id).one().rule_id is None


def test_every_foreign_key_in_the_models_has_a_delete_rule():
    from app.db import Base
    missing = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            for key in column.foreign_keys:
                if not key.ondelete:
                    missing.append(f"{table.name}.{column.name}")
    assert missing == []


# ── the export ──────────────────────────────────────────────────────────────

def test_export_adds_the_provider_identifier_lock_state_and_windows(client, db):
    user = _user(db, "x1@test.com", password=None, oauth_provider="github", oauth_id="gh-x1")
    user.failed_login_attempts = 3
    user.locked_until = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    db.add(MaintenanceWindow(label="Mine", start_at=now, end_at=now + timedelta(hours=1), created_by=user.id))
    db.add(MaintenanceWindow(label="Not mine", start_at=now, end_at=now + timedelta(hours=1)))
    db.flush()
    body = client.get("/api/v1/auth/me/export", headers=_headers(user)).json()
    assert body["profile"]["sign_in_provider_id"] == "gh-x1"
    assert body["profile"]["failed_sign_in_attempts"] == 3
    assert body["profile"]["locked_until"].startswith("2026-11-22T12:00")
    assert [w["label"] for w in body["maintenance_windows"]] == ["Mine"]


def test_export_withholds_the_text_of_a_ticket_on_a_machine_the_person_may_not_read(client, db):
    tech = _user(db, "x2@test.com")
    owner = _user(db, "x2o@test.com")
    hidden = _ticket(db, device=_device(db, "Theirs", owner=owner), assigned_to=tech, created_by=owner)
    visible = _ticket(db, device=_device(db, "Shared"), assigned_to=tech)
    body = client.get("/api/v1/auth/me/export", headers=_headers(tech)).json()
    by_id = {t["id"]: t for t in body["tickets_assigned"]}
    assert by_id[str(hidden.id)]["text_withheld"] is True
    assert "title" not in by_id[str(hidden.id)] and "description" not in by_id[str(hidden.id)]
    assert by_id[str(hidden.id)]["ticket_number"] is not None and by_id[str(hidden.id)]["status"] == "open"
    assert by_id[str(visible.id)]["description"] == "Details"


def test_export_holds_no_other_persons_account_id(client, db):
    tech = _user(db, "x3@test.com")
    other = _user(db, "x3o@test.com")
    _ticket(db, created_by=tech, assigned_to=other)
    res = client.get("/api/v1/auth/me/export", headers=_headers(tech))
    assert str(other.id) not in res.text
    assert res.json()["tickets"][0]["created_by_you"] is True


def test_a_failed_audit_read_fails_the_export_loudly(client, db, monkeypatch):
    user = _user(db, "x4@test.com")

    from sqlalchemy.orm import Session as OrmSession

    real = OrmSession.execute

    def broken(self, statement, *args, **kwargs):
        # only the audit read fails. it is patched on the session class, not one session, so the request's own
        # session fails the same way whichever session the app hands the route in a full test run
        if "audit_log" in str(statement):
            raise RuntimeError("audit table unreadable")
        return real(self, statement, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "execute", broken)
    res = client.get("/api/v1/auth/me/export", headers=_headers(user))
    assert res.status_code == 500
    assert "nothing was exported" in res.json()["detail"]
    assert "unreadable" not in res.text


# ── small fixes ─────────────────────────────────────────────────────────────

def test_deleting_an_account_does_not_restart_the_retention_clock(client, db):
    tech = _user(db, "d1@test.com")
    long_ago = datetime(2025, 1, 1, tzinfo=timezone.utc)
    ticket = _ticket(db, created_by=tech)
    db.execute(text("UPDATE tickets SET updated_at = :t WHERE id = :id"), {"t": long_ago, "id": str(ticket.id)})
    db.expire_all()
    res = client.request("DELETE", "/api/v1/auth/me", json={"password": PASSWORD}, headers=_headers(tech))
    assert res.status_code == 204
    db.expire_all()
    assert db.query(Ticket).filter(Ticket.id == ticket.id).one().updated_at == long_ago


def test_field_lengths_longer_than_the_columns_are_refused_not_a_500(client, db):
    admin = _user(db, "f1@test.com", "admin")
    tech = _user(db, "f1t@test.com")
    assert client.post("/api/v1/devices", json={"name": "n" * 101, "type": "esp32"}, headers=_headers(admin)).status_code == 422
    assert client.post("/api/v1/devices", json={"name": "ok", "location": "l" * 101}, headers=_headers(admin)).status_code == 422
    assert client.patch("/api/v1/auth/me", json={"name": "n" * 101}, headers=_headers(tech)).status_code == 422
    now = datetime.now(timezone.utc)
    window = {"label": "w" * 201, "start_at": now.isoformat(), "end_at": (now + timedelta(hours=1)).isoformat()}
    assert client.post("/api/v1/maintenance-windows", json=window, headers=_headers(admin)).status_code == 422
    assert client.post("/api/v1/auth/register", json={"name": "n" * 101, "email": "n@test.com", "password": PASSWORD}).status_code == 422


def test_the_demo_does_not_take_over_a_technicians_machine(client, db, monkeypatch):
    admin = _user(db, "demo@test.com", "admin")
    tech = _user(db, "demot@test.com")
    mine = _device(db, "Demo Node", owner=tech)
    class Quiet:
        running = True

        def get_job(self, *args):
            return None

        def add_job(self, *args, **kwargs):
            return None

    monkeypatch.setattr("app.routes.demo._scheduler", Quiet())
    res = client.post("/api/v1/demo/start", headers=_headers(admin))
    assert res.status_code in (200, 201, 202)
    assert db.query(Device).filter(Device.name == "Demo Node", Device.owner_id.is_(None)).count() == 1
    assert db.query(Device).filter(Device.id == mine.id).one().owner_id == tech.id


def test_the_status_route_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr("app.routes.health._check_db", lambda: "ok")
    monkeypatch.setattr("app.routes.health._check_redis", lambda: "ok")
    codes = [client.get("/status").status_code for _ in range(122)]
    assert codes[0] == 200 and 429 in codes
