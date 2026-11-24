"""
Account deletion and export, the admin user list, outbound webhook addresses, the names and totals the
dashboard pages need and the provider list.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from passlib.context import CryptContext
from sqlalchemy import text

from app.config import settings
from app.models.alert import Alert
from app.models.device import Device
from app.models.ticket import Ticket
from app.models.user import User
from app.models.webhook import Webhook
from app.services import audit_service, url_safety
from tests._shape import plain

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD = "Passw0rd!x"
NOT_FOUND = {"detail": "Device not found"}


def _headers(user):
    from app.routes.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'role': user.role})}"}


def _user(db, email, role="technician", name=None, password=PASSWORD, **extra):
    u = User(
        name=name if name is not None else email.split("@")[0],
        email=email, role=role,
        password_hash=_pwd_ctx.hash(password) if password else None,
        **extra,
    )
    db.add(u)
    db.flush()
    return u


def _device(db, name="Node", owner=None, **extra):
    d = Device(name=name, location="Lab", type="esp32", api_key=secrets.token_urlsafe(32),
               owner_id=owner.id if owner else None, **extra)
    db.add(d)
    db.flush()
    return d


def _ticket(db, device=None, alert=None, created_by=None, assigned_to=None, **extra):
    t = Ticket(
        device_id=device.id if device else None, alert_id=alert.id if alert else None,
        created_by=created_by.id if created_by else None, assigned_to=assigned_to.id if assigned_to else None,
        title=extra.pop("title", "Check it"), description=extra.pop("description", "Details"),
        status=extra.pop("status", "open"), priority=extra.pop("priority", "low"),
    )
    db.add(t)
    db.flush()
    return t


def _alert(db, device, **extra):
    a = Alert(device_id=device.id, message="hot", severity="warning", resolved=False, **extra)
    db.add(a)
    db.flush()
    return a


def _provider_session(db, user, minutes_ago=0):
    """A session that came back from the provider this long ago and the headers of an access token for it."""
    from app.models.user_session import UserSession
    from app.routes.auth import _identity, create_access_token
    session = UserSession(
        user_id=user.id, current_jti="j", expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        provider_signin_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(session)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(_identity(user, str(session.id)))}"}


def _delete(client, user, **body):
    return client.request("DELETE", "/api/v1/auth/me", json=body or None, headers=_headers(user))


@pytest.fixture
def admin(db):
    return _user(db, "ar-admin@test.com", "admin", "Ada Admin")


@pytest.fixture
def tech(db):
    return _user(db, "ar-tech@test.com", "technician", "Tess Tech")


@pytest.fixture
def other_tech(db):
    return _user(db, "ar-other@test.com", "technician", "Otto Other")


@pytest.fixture
def viewer(db):
    return _user(db, "ar-viewer@test.com", "viewer", "Vera Viewer")


# ── deleting an account ─────────────────────────────────────────────────────

def test_the_delete_rules_on_the_ticket_model_match_the_migrations():
    for column in ("device_id", "alert_id", "assigned_to", "created_by"):
        (key,) = Ticket.__table__.c[column].foreign_keys
        assert key.ondelete == "SET NULL", column


def test_the_database_itself_clears_both_user_columns(db, tech, other_tech):
    # a delete that skips the route, on a table made by create_all
    ticket = _ticket(db, created_by=tech, assigned_to=tech)
    db.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(tech.id)})
    db.expire_all()
    ticket = db.query(Ticket).filter(Ticket.id == ticket.id).one()
    assert ticket.created_by is None and ticket.assigned_to is None


def test_deleting_the_device_or_alert_a_ticket_names_keeps_the_ticket(db):
    device = _device(db)
    alert = _alert(db, device)
    ticket = _ticket(db, device=device, alert=alert)
    db.execute(text("DELETE FROM devices WHERE id = :id"), {"id": str(device.id)})
    db.expire_all()
    ticket = db.query(Ticket).filter(Ticket.id == ticket.id).one()
    assert ticket.device_id is None


def test_delete_needs_the_current_password(client, db, tech):
    assert _delete(client, tech).status_code == 400
    wrong = _delete(client, tech, password="wrong-password")
    assert (wrong.status_code, plain(wrong)) == (400, {"detail": "Enter your current password to delete your account"})
    assert db.query(User).filter(User.id == tech.id).first() is not None
    assert _delete(client, tech, password=PASSWORD).status_code == 204
    assert db.query(User).filter(User.id == tech.id).first() is None


def test_a_typed_word_does_not_replace_the_password(client, db, tech):
    assert _delete(client, tech, confirm="DELETE").status_code == 400
    assert db.query(User).filter(User.id == tech.id).first() is not None


def test_provider_account_without_two_step_needs_a_recent_provider_sign_in(client, db):
    user = _user(db, "ar-provider@test.com", password=None, oauth_provider="github", oauth_id="1")
    expected = {"detail": "Sign in with GitHub again within the last 5 minutes to delete your account"}
    # a typed word, a password and nothing at all are all refused
    for body in ({}, {"confirm": "DELETE"}, {"password": PASSWORD}):
        res = _delete(client, user, **body)
        assert (res.status_code, plain(res)) == (400, expected)
    # a sign-in from longer ago than 5 minutes does not count. The time is on the session that made the return
    old = _provider_session(db, user, minutes_ago=6)
    assert client.request("DELETE", "/api/v1/auth/me", headers=old).status_code == 400
    fresh = _provider_session(db, user, minutes_ago=2)
    assert client.request("DELETE", "/api/v1/auth/me", headers=fresh).status_code == 204


def test_provider_account_with_two_step_needs_a_fresh_code(client, db):
    secret = pyotp.random_base32()
    user = _user(db, "ar-2fa@test.com", password=None, oauth_provider="google", oauth_id="2",
                 totp_secret=secret, totp_enabled=True)
    # the typed word is not enough once two-step is on
    assert _delete(client, user, confirm="DELETE").status_code == 400
    assert _delete(client, user, code="000000").status_code == 400
    assert db.query(User).filter(User.id == user.id).first() is not None
    assert _delete(client, user, code=pyotp.TOTP(secret).now()).status_code == 204


def test_delete_clears_created_by_and_assigned_to_and_keeps_the_tickets(client, db, tech, admin):
    mine = _ticket(db, created_by=tech, title="Raised by me")
    given = _ticket(db, created_by=admin, assigned_to=tech, title="Given to me")
    both = _ticket(db, created_by=tech, assigned_to=tech, title="Both")
    assert _delete(client, tech, password=PASSWORD).status_code == 204
    db.expire_all()
    for ticket in (mine, given, both):
        row = db.query(Ticket).filter(Ticket.id == ticket.id).one()
        assert row.created_by != tech.id and row.assigned_to != tech.id
        assert row.title
    assert db.query(Ticket).filter(Ticket.id == given.id).one().created_by == admin.id


def test_delete_is_refused_while_the_user_owns_machines(client, db, admin, tech, other_tech):
    machine = _device(db, "Press", owner=tech)
    ticket = _ticket(db, device=machine, assigned_to=tech)
    res = _delete(client, tech, password=PASSWORD)
    assert (res.status_code, plain(res)) == (409, {"detail": "Hand your machines to another person first"})
    assert db.query(User).filter(User.id == tech.id).first() is not None
    assert db.query(Device).filter(Device.id == machine.id).one().owner_id == tech.id
    # an admin hands the machine over and the delete goes through
    handed = client.patch(f"/api/v1/devices/{machine.id}", json={"owner_id": str(other_tech.id)}, headers=_headers(admin))
    assert handed.status_code == 200
    assert _delete(client, tech, password=PASSWORD).status_code == 204
    db.expire_all()
    assert db.query(Device).filter(Device.id == machine.id).one().owner_id == other_tech.id
    assert db.query(Ticket).filter(Ticket.id == ticket.id).one().assigned_to is None


def test_user_who_created_tickets_has_tickets_assigned_and_owns_machines(client, db, admin, tech, other_tech):
    # the three things at once: refused first, then deleted once the machine is handed on
    machine = _device(db, owner=tech)
    _ticket(db, created_by=tech)
    _ticket(db, assigned_to=tech)
    assert _delete(client, tech, password=PASSWORD).status_code == 409
    client.patch(f"/api/v1/devices/{machine.id}", json={"owner_id": None}, headers=_headers(admin))
    assert _delete(client, tech, password=PASSWORD).status_code == 204


def test_the_last_admin_cannot_be_deleted(client, db, admin):
    res = _delete(client, admin, password=PASSWORD)
    assert res.status_code == 409
    assert "last admin" in res.json()["detail"]
    assert db.query(User).filter(User.id == admin.id).first() is not None


def test_an_admin_can_be_deleted_when_another_exists(client, db, admin):
    _user(db, "ar-admin2@test.com", "admin")
    assert _delete(client, admin, password=PASSWORD).status_code == 204


def test_delete_still_needs_a_sign_in(client):
    assert client.request("DELETE", "/api/v1/auth/me", json={"password": PASSWORD}).status_code == 401


def test_profile_read_says_whether_the_account_has_a_password(client, db, tech):
    provider = _user(db, "ar-p2@test.com", password=None, oauth_provider="github", oauth_id="9")
    assert client.get("/api/v1/auth/me", headers=_headers(tech)).json()["has_password"] is True
    assert client.get("/api/v1/auth/me", headers=_headers(provider)).json()["has_password"] is False


# ── the export ──────────────────────────────────────────────────────────────

def test_export_holds_everything_the_service_keeps_about_the_person(client, db, admin, tech, other_tech):
    tech.phone_number = "+447700900000"
    tech.last_login = datetime(2026, 11, 20, 9, 30, tzinfo=timezone.utc)
    tech.oauth_provider = "github"
    tech.totp_secret = "JBSWY3DPEHPK3PXP"
    tech.totp_enabled = True
    tech.permissions = {"note": "saved"}
    machine = _device(db, "Lathe", owner=tech, firmware_version="1.2.3")
    raised = _ticket(db, device=machine, created_by=tech, title="Raised", description="I wrote this")
    given = _ticket(db, created_by=admin, assigned_to=tech, title="Given", description="Assigned text")
    _ticket(db, created_by=other_tech, title="Someone else's")
    audit_service.log_action(db, str(tech.id), "ticket_created", "ticket", str(raised.id), "title='Raised'")
    audit_service.log_action(db, str(other_tech.id), "ticket_created", "ticket", "x", "not mine")

    res = client.get("/api/v1/auth/me/export", headers=_headers(tech))
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    body = res.json()

    profile = body["profile"]
    assert profile["email"] == tech.email and profile["phone_number"] == "+447700900000"
    assert profile["last_login"].startswith("2026-11-20T09:30")
    assert profile["sign_in_provider"] == "github"
    assert profile["two_step_enabled"] is True
    assert profile["permissions"] == {"note": "saved"}
    assert profile["role"] == "technician" and profile["created_at"]

    assert [t["title"] for t in body["tickets"]] == ["Raised"]
    assert body["tickets"][0]["description"] == "I wrote this"
    assert [t["title"] for t in body["tickets_assigned"]] == ["Given"]
    assert body["tickets_assigned"][0]["description"] == "Assigned text"
    assert body["tickets_assigned"][0]["id"] == str(given.id)

    assert [d["name"] for d in body["devices"]] == ["Lathe"]
    assert body["devices"][0]["firmware_version"] == "1.2.3"

    assert [e["action"] for e in body["audit_log"]] == ["ticket_created"]
    assert body["audit_log"][0]["resource_id"] == str(raised.id)
    assert "not mine" not in res.text


def test_export_never_holds_a_secret(client, db, tech):
    tech.totp_secret = "JBSWY3DPEHPK3PXP"
    tech.totp_enabled = True
    res = client.get("/api/v1/auth/me/export", headers=_headers(tech))
    assert "JBSWY3DPEHPK3PXP" not in res.text
    assert tech.password_hash not in res.text
    assert "token_version" not in res.text and "password_hash" not in res.text


def test_export_for_a_person_with_nothing_else_is_complete_and_empty(client, viewer):
    body = client.get("/api/v1/auth/me/export", headers=_headers(viewer)).json()
    assert body["tickets"] == body["tickets_assigned"] == body["devices"] == body["audit_log"] == []
    assert body["profile"]["two_step_enabled"] is False


# ── the admin user list ─────────────────────────────────────────────────────

def test_user_list_leaves_out_phone_numbers_and_permissions(client, db, admin, tech):
    tech.phone_number = "+447700900001"
    tech.permissions = {"x": 1}
    res = client.get("/api/v1/auth/users", headers=_headers(admin))
    assert res.status_code == 200
    assert "+447700900001" not in res.text
    for row in res.json():
        assert "phone_number" not in row and "permissions" not in row
        assert {"id", "name", "email", "role"} <= set(row)


def test_user_list_stays_admin_only_and_the_profile_keeps_the_phone(client, tech, viewer):
    assert client.get("/api/v1/auth/users", headers=_headers(tech)).status_code == 403
    assert client.get("/api/v1/auth/users", headers=_headers(viewer)).status_code == 403
    tech.phone_number = "+447700900002"
    assert client.get("/api/v1/auth/me", headers=_headers(tech)).json()["phone_number"] == "+447700900002"


# ── Google sign-in and the permissions field ────────────────────────────────

def test_google_sign_in_does_not_ask_for_offline_access(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-id")
    res = client.get("/api/v1/auth/google", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert "access_type" not in res.headers["location"]
    assert "offline" not in res.headers["location"]


def test_the_permissions_route_is_gone_and_no_reply_returns_the_field(client, db, admin, tech):
    res = client.patch(f"/api/v1/auth/users/{tech.id}/permissions", json={"a": 1}, headers=_headers(admin))
    assert res.status_code in (404, 405)
    for path in ("/api/v1/auth/me", "/api/v1/auth/users"):
        assert "permissions" not in client.get(path, headers=_headers(admin)).text
    # the column is still there
    assert hasattr(User, "permissions")


# ── what the audit writer prints ────────────────────────────────────────────

def test_a_failed_audit_write_prints_the_error_type_only(capsys):
    class Broken:
        def execute(self, *args, **kwargs):
            raise RuntimeError("duplicate key value (alice@example.com, +447700900000)")

        def rollback(self):
            pass

    audit_service.log_action(Broken(), "u", "act", "res", "id", "detail")
    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert "alice@example.com" not in err and "+447700900000" not in err


# ── webhook addresses ───────────────────────────────────────────────────────

def _resolves_to(monkeypatch, *addresses):
    def fake(host, port, *args, **kwargs):
        return [(2, 1, 6, "", (a, port or 443)) for a in addresses]
    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", fake)


@pytest.mark.parametrize("url", [
    "https://10.0.0.5/hook",
    "https://127.0.0.1/hook",
    "https://localhost/hook",
    "https://169.254.169.254/latest/meta-data",
    "https://192.168.1.10/hook",
    "https://172.16.0.1/hook",
    "https://100.64.0.1/hook",
    "https://0.0.0.0/hook",
    "https://[::1]/hook",
    "https://[fe80::1]/hook",
    "https://[fc00::1]/hook",
    "https://[::ffff:10.0.0.1]/hook",
    "https://224.0.0.1/hook",
])
def test_private_and_reserved_literal_addresses_are_refused(url, monkeypatch):
    _resolves_to(monkeypatch, "127.0.0.1")
    with pytest.raises(url_safety.UnsafeUrl):
        url_safety.check_outbound_url(url)


def test_a_public_address_is_accepted(monkeypatch):
    _resolves_to(monkeypatch, "8.8.8.8")
    url_safety.check_outbound_url("https://hooks.example.org/path")
    url_safety.check_outbound_url("https://8.8.8.8/path")
    url_safety.check_outbound_url("https://[2001:4860:4860::8888]/path")


def test_a_name_that_resolves_inside_the_network_is_refused(monkeypatch):
    _resolves_to(monkeypatch, "10.1.2.3")
    with pytest.raises(url_safety.UnsafeUrl) as refused:
        url_safety.check_outbound_url("https://internal.example.org/hook")
    assert "private" in str(refused.value)


def test_every_address_a_name_returns_is_checked(monkeypatch):
    _resolves_to(monkeypatch, "8.8.8.8", "192.168.0.9")
    with pytest.raises(url_safety.UnsafeUrl):
        url_safety.check_outbound_url("https://mixed.example.org/hook")


def test_a_name_that_does_not_resolve_is_refused(monkeypatch):
    import socket

    def fail(*args, **kwargs):
        raise socket.gaierror("no such host")
    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", fail)
    with pytest.raises(url_safety.UnsafeUrl):
        url_safety.check_outbound_url("https://nowhere.example.org/hook")


def test_http_is_refused_outside_development_and_allowed_in_it(monkeypatch):
    _resolves_to(monkeypatch, "8.8.8.8")
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(url_safety.UnsafeUrl) as refused:
        url_safety.check_outbound_url("http://hooks.example.org/path")
    assert "https" in str(refused.value)
    monkeypatch.setattr(settings, "environment", "development")
    url_safety.check_outbound_url("http://hooks.example.org/path")
    # development allows http but never a private address
    with pytest.raises(url_safety.UnsafeUrl):
        url_safety.check_outbound_url("http://127.0.0.1/path")


@pytest.mark.parametrize("url", ["ftp://hooks.example.org/x", "file:///etc/passwd", "https:///nohost"])
def test_other_schemes_and_empty_hosts_are_refused(url, monkeypatch):
    _resolves_to(monkeypatch, "8.8.8.8")
    with pytest.raises(url_safety.UnsafeUrl):
        url_safety.check_outbound_url(url)


def test_webhook_create_and_update_refuse_unsafe_addresses(client, db, admin, monkeypatch):
    _resolves_to(monkeypatch, "8.8.8.8")
    created = client.post("/api/v1/webhooks", json={"password": PASSWORD, "name": "ok", "url": "https://hooks.example.org/a"}, headers=_headers(admin))
    assert created.status_code == 201
    for bad in ("https://10.0.0.5/a", "https://127.0.0.1:8000/admin", "https://169.254.169.254/"):
        res = client.post("/api/v1/webhooks", json={"password": PASSWORD, "name": "bad", "url": bad}, headers=_headers(admin))
        assert res.status_code == 422, bad
        patched = client.patch(f"/api/v1/webhooks/{created.json()['id']}", json={"password": PASSWORD, "url": bad}, headers=_headers(admin))
        assert patched.status_code == 422, bad
    assert db.query(Webhook).filter(Webhook.name == "bad").count() == 0
    assert db.query(Webhook).filter(Webhook.id == created.json()["id"]).one().url == "https://hooks.example.org/a"
    # a change that leaves the address alone is not checked again
    assert client.patch(f"/api/v1/webhooks/{created.json()['id']}", json={"password": PASSWORD, "enabled": False}, headers=_headers(admin)).status_code == 200


def test_webhook_names_that_resolve_inside_are_refused(client, admin, monkeypatch):
    _resolves_to(monkeypatch, "10.0.0.7")
    res = client.post("/api/v1/webhooks", json={"password": PASSWORD, "name": "n", "url": "https://sneaky.example.org/a"}, headers=_headers(admin))
    assert res.status_code == 422


def test_webhook_test_refuses_an_address_saved_before_the_check(client, db, admin, monkeypatch):
    wh = Webhook(name="old", url="https://127.0.0.1/hook")
    db.add(wh)
    db.flush()
    called = []
    monkeypatch.setattr("app.routes.webhooks.webhook_service.test_webhook", lambda w: called.append(w) or __import__("app.services.webhook_service", fromlist=["Outcome"]).Outcome(True, 204))
    res = client.post(f"/api/v1/webhooks/{wh.id}/test", headers=_headers(admin))
    assert res.status_code == 422
    assert called == []


def test_webhook_routes_stay_admin_only(client, tech, viewer):
    body = {"name": "n", "url": "https://8.8.8.8/a"}
    for user in (tech, viewer):
        assert client.post("/api/v1/webhooks", json=body, headers=_headers(user)).status_code == 403


# ── owner names ─────────────────────────────────────────────────────────────

def test_machine_replies_carry_the_owner_name_for_every_role(client, db, admin, tech, other_tech, viewer):
    mine = _device(db, "Mine", owner=tech)
    shared = _device(db, "Shared")
    for user in (admin, tech, viewer):
        single = client.get(f"/api/v1/devices/{mine.id}", headers=_headers(user))
        assert single.status_code == 200
        assert single.json()["owner_name"] == "Tess Tech"
        assert single.json()["owner_id"] == str(tech.id)
        listed = {d["id"]: d for d in client.get("/api/v1/devices", headers=_headers(user)).json()}
        assert listed[str(mine.id)]["owner_name"] == "Tess Tech"
        assert listed[str(shared.id)]["owner_name"] is None
        # a name and nothing else about the person
        assert tech.email not in single.text
    assert client.get(f"/api/v1/devices/{mine.id}", headers=_headers(other_tech)).status_code == 404


def test_owner_name_follows_a_change_of_owner(client, db, admin, tech, other_tech):
    machine = _device(db, owner=tech)
    res = client.patch(f"/api/v1/devices/{machine.id}", json={"owner_id": str(other_tech.id)}, headers=_headers(admin))
    assert res.json()["owner_name"] == "Otto Other"
    cleared = client.patch(f"/api/v1/devices/{machine.id}", json={"owner_id": None}, headers=_headers(admin))
    assert cleared.json()["owner_name"] is None


def test_registering_a_machine_checks_the_owner_exists(client, admin, tech):
    body = {"name": "New", "type": "esp32", "location": "Lab"}
    bad = client.post("/api/v1/devices", json={**body, "owner_id": str(uuid.uuid4())}, headers=_headers(admin))
    assert (bad.status_code, plain(bad)) == (404, {"detail": "Owner not found"})
    ok = client.post("/api/v1/devices", json={**body, "owner_id": str(tech.id)}, headers=_headers(admin))
    assert ok.status_code == 201
    assert ok.json()["owner_name"] == "Tess Tech"
    assert client.post("/api/v1/devices", json=body, headers=_headers(admin)).status_code == 201


# ── totals and paging ───────────────────────────────────────────────────────

def test_device_total_counts_with_the_same_access_filter(client, db, admin, viewer, tech, other_tech):
    for n in range(3):
        _device(db, f"mine-{n}", owner=tech)
    _device(db, "shared")
    for n in range(2):
        _device(db, f"theirs-{n}", owner=other_tech)

    def total(user, query=""):
        res = client.get(f"/api/v1/devices{query}", headers=_headers(user))
        return int(res.headers["X-Total-Count"]), len(res.json())

    assert total(admin) == (6, 6)
    assert total(viewer) == (6, 6)
    assert total(tech) == (4, 4)
    # the total ignores the page and follows the filters
    assert total(tech, "?limit=2") == (4, 2)
    assert total(tech, "?skip=3&limit=2") == (4, 1)
    assert total(admin, "?search=theirs") == (2, 2)


def test_the_total_header_is_exposed_through_cors(client, admin):
    res = client.get("/api/v1/devices", headers={**_headers(admin), "Origin": "http://localhost:3000"})
    exposed = res.headers.get("access-control-expose-headers", "").lower()
    assert "x-total-count" in exposed


def test_alert_list_pages_and_counts(client, db, admin, tech):
    own = _device(db, "own", owner=tech)
    theirs = _device(db, "theirs", owner=_user(db, "ar-o2@test.com"))
    for _ in range(5):
        _alert(db, own)
    for _ in range(3):
        _alert(db, theirs)
    _alert(db, own).resolved = True
    db.flush()

    everything = client.get("/api/v1/alerts", headers=_headers(admin))
    assert (int(everything.headers["X-Total-Count"]), len(everything.json())) == (9, 9)
    page = client.get("/api/v1/alerts?limit=2&offset=1", headers=_headers(admin))
    assert (int(page.headers["X-Total-Count"]), len(page.json())) == (9, 2)
    mine_only = client.get("/api/v1/alerts?limit=2", headers=_headers(tech))
    assert (int(mine_only.headers["X-Total-Count"]), len(mine_only.json())) == (6, 2)
    open_only = client.get("/api/v1/alerts?resolved=false", headers=_headers(tech))
    assert int(open_only.headers["X-Total-Count"]) == 5


def test_alert_paging_has_a_default_and_a_maximum(client, db, admin):
    device = _device(db)
    for _ in range(105):
        _alert(db, device)
    default = client.get("/api/v1/alerts", headers=_headers(admin))
    assert len(default.json()) == 100
    assert int(default.headers["X-Total-Count"]) == 105
    assert len(client.get("/api/v1/alerts?limit=500", headers=_headers(admin)).json()) == 105
    assert client.get("/api/v1/alerts?limit=501", headers=_headers(admin)).status_code == 422
    assert client.get("/api/v1/alerts?limit=0", headers=_headers(admin)).status_code == 422
    assert client.get("/api/v1/alerts?offset=-1", headers=_headers(admin)).status_code == 422


def test_ticket_list_total_and_priority_filter(client, db, admin, tech, other_tech):
    own = _device(db, "own", owner=tech)
    theirs = _device(db, "theirs", owner=other_tech)
    _ticket(db, device=own, priority="high")
    _ticket(db, device=own, priority="low")
    _ticket(db, device=theirs, priority="high")
    _ticket(db, priority="high", status="closed")

    def total(user, query=""):
        res = client.get(f"/api/v1/tickets{query}", headers=_headers(user))
        return int(res.headers["X-Total-Count"]), len(res.json())

    assert total(admin) == (4, 4)
    # the closed ticket with no machine is not theirs, so a technician does not see it
    assert total(tech) == (2, 2)
    assert total(admin, "?priority=high") == (3, 3)
    assert total(tech, "?priority=high") == (1, 1)
    assert total(admin, "?priority=high&status=closed") == (1, 1)
    assert total(admin, "?limit=1") == (4, 1)


# ── ticket names, assignees and alert links ─────────────────────────────────

def test_ticket_replies_carry_both_names(client, db, admin, tech, viewer):
    ticket = _ticket(db, created_by=admin, assigned_to=tech)
    orphan = _ticket(db)
    for user in (admin, tech, viewer):
        got = client.get(f"/api/v1/tickets/{ticket.id}", headers=_headers(user)).json()
        assert (got["created_by_name"], got["assigned_to_name"]) == ("Ada Admin", "Tess Tech")
        listed = {t["id"]: t for t in client.get("/api/v1/tickets", headers=_headers(user)).json()}
        assert listed[str(ticket.id)]["assigned_to_name"] == "Tess Tech"
        if user is not tech:
            # a technician does not see a machine-less ticket that is not theirs
            assert listed[str(orphan.id)]["assigned_to_name"] is None
        assert tech.email not in str(got)


def test_created_ticket_reply_names_its_creator(client, db, tech):
    res = client.post("/api/v1/tickets", json={"title": "New"}, headers=_headers(tech))
    assert res.status_code == 201
    assert res.json()["created_by_name"] == "Tess Tech"


def test_the_assignee_list_is_for_admins_and_technicians_and_holds_only_id_and_name(client, db, admin, tech, other_tech, viewer):
    for user in (admin, tech):
        res = client.get("/api/v1/tickets/assignees", headers=_headers(user))
        assert res.status_code == 200
        rows = res.json()
        assert {r["id"] for r in rows} == {str(admin.id), str(tech.id), str(other_tech.id)}
        assert all(set(r) == {"id", "name"} for r in rows)
        assert "@" not in res.text and "phone" not in res.text
    assert client.get("/api/v1/tickets/assignees", headers=_headers(viewer)).status_code == 403
    assert client.get("/api/v1/tickets/assignees").status_code == 401


def test_a_technician_can_assign_within_the_team(client, db, tech, other_tech):
    # an unowned machine, so the person it goes to can open the ticket afterwards
    shared = _device(db, "Shared")
    ticket = _ticket(db, device=shared)
    res = client.patch(f"/api/v1/tickets/{ticket.id}", json={"assigned_to": str(other_tech.id)}, headers=_headers(tech))
    assert res.status_code == 200
    assert (res.json()["assigned_to"], res.json()["assigned_to_name"]) == (str(other_tech.id), "Otto Other")


def test_an_explicit_null_clears_the_assignee(client, db, admin, tech):
    ticket = _ticket(db, assigned_to=tech)
    res = client.patch(f"/api/v1/tickets/{ticket.id}", json={"assigned_to": None}, headers=_headers(admin))
    assert res.status_code == 200
    assert res.json()["assigned_to"] is None and res.json()["assigned_to_name"] is None


def test_an_omitted_assignee_is_left_alone_and_other_nulls_are_refused(client, db, admin, tech):
    ticket = _ticket(db, assigned_to=tech, title="Keep")
    ok = client.patch(f"/api/v1/tickets/{ticket.id}", json={"status": "in_progress"}, headers=_headers(admin))
    assert ok.status_code == 200 and ok.json()["assigned_to"] == str(tech.id)
    # a null on a field that must keep a value is a 422 (only the assignee and the description may be cleared)
    res = client.patch(f"/api/v1/tickets/{ticket.id}", json={"title": None}, headers=_headers(admin))
    assert res.status_code == 422 and res.json()["code"] == "validation_failed"
    assert client.get(f"/api/v1/tickets/{ticket.id}", headers=_headers(admin)).json()["title"] == "Keep"


def test_an_assignee_that_does_not_exist_is_a_404_not_a_database_error(client, db, admin):
    ticket = _ticket(db)
    res = client.patch(f"/api/v1/tickets/{ticket.id}", json={"assigned_to": str(uuid.uuid4())}, headers=_headers(admin))
    assert (res.status_code, plain(res)) == (404, {"detail": "Assignee not found"})


def test_a_ticket_made_from_an_alert_stores_it_and_can_be_found_by_it(client, db, admin, tech):
    device = _device(db, owner=tech)
    alert = _alert(db, device)
    other = _alert(db, device)
    made = client.post(
        "/api/v1/tickets",
        json={"title": "From alert", "device_id": str(device.id), "alert_id": str(alert.id)},
        headers=_headers(tech),
    )
    assert made.status_code == 201
    assert made.json()["alert_id"] == str(alert.id)
    client.post("/api/v1/tickets", json={"title": "Other", "device_id": str(device.id), "alert_id": str(other.id)}, headers=_headers(tech))
    client.post("/api/v1/tickets", json={"title": "None"}, headers=_headers(tech))

    found = client.get(f"/api/v1/tickets?alert_id={alert.id}", headers=_headers(tech))
    assert [t["title"] for t in found.json()] == ["From alert"]
    assert found.headers["X-Total-Count"] == "1"
    assert client.get(f"/api/v1/tickets?alert_id={uuid.uuid4()}", headers=_headers(admin)).json() == []


def test_the_alert_filter_respects_the_machine_rule(client, db, tech, other_tech):
    theirs = _device(db, owner=other_tech)
    alert = _alert(db, theirs)
    _ticket(db, device=theirs, alert=alert)
    assert client.get(f"/api/v1/tickets?alert_id={alert.id}", headers=_headers(tech)).json() == []


# ── providers ───────────────────────────────────────────────────────────────

def test_providers_lists_only_what_is_configured_by_name(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "google-id-123")
    monkeypatch.setattr(settings, "github_client_id", "")
    monkeypatch.setattr(settings, "microsoft_client_id", "ms-id-456")
    res = client.get("/api/v1/auth/providers")
    assert res.status_code == 200
    assert res.json() == {"providers": ["google", "microsoft"]}
    assert "123" not in res.text and "456" not in res.text


def test_providers_is_empty_when_none_are_configured(client, monkeypatch):
    for name in ("google_client_id", "github_client_id", "microsoft_client_id"):
        monkeypatch.setattr(settings, name, "")
    assert client.get("/api/v1/auth/providers").json() == {"providers": []}


def test_providers_is_rate_limited(client):
    codes = [client.get("/api/v1/auth/providers").status_code for _ in range(62)]
    assert codes[0] == 200
    assert 429 in codes
