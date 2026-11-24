"""
Who may create an account, plus the command that makes the first admin.

A self-made account is a viewer and a viewer reads every machine, so outside development
registration is closed unless REGISTRATION_OPEN says otherwise.
"""

import pytest
from fastapi import HTTPException
from passlib.context import CryptContext
from sqlalchemy import text

from app.config import settings
from app.models.user import User
from app.routes.auth import _create_invite, _microsoft_user, _oauth_upsert, verify_password
from app.scripts.create_admin import AdminNotCreated, create_admin
from tests._shape import plain

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_NEW = {"name": "Newcomer", "email": "newcomer@example.com", "password": "Passw0rd!x"}


@pytest.fixture
def closed(monkeypatch):
    monkeypatch.setattr(settings, "registration_open", False)


def _existing(db, email="existing@example.com"):
    user = User(name="Existing", email=email, password_hash=_pwd_ctx.hash("Passw0rd!x"), role="technician")
    db.add(user)
    db.flush()
    return user


# ── the setting ─────────────────────────────────────────────────────────────

def test_unset_follows_the_environment(monkeypatch):
    monkeypatch.setattr(settings, "registration_open", None)
    monkeypatch.setattr(settings, "environment", "development")
    assert settings.registration_is_open is True
    for name in ("production", "prod", "staging", ""):
        monkeypatch.setattr(settings, "environment", name)
        assert settings.registration_is_open is False


def test_an_explicit_value_wins_either_way(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "registration_open", True)
    assert settings.registration_is_open is True
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "registration_open", False)
    assert settings.registration_is_open is False


# ── POST /auth/register ─────────────────────────────────────────────────────

def test_register_works_when_open(client):
    res = client.post("/api/v1/auth/register", json=_NEW)
    assert res.status_code == 201
    assert res.json()["role"] == "viewer"


def test_register_is_refused_when_closed(client, db, closed):
    res = client.post("/api/v1/auth/register", json=_NEW)
    assert res.status_code == 403
    assert plain(res) == {"detail": "Registration is closed. Ask an administrator for an invitation."}
    assert db.query(User).filter(User.email == _NEW["email"]).first() is None


def test_closed_registration_does_not_stop_an_existing_account_signing_in(client, db, closed):
    _existing(db)
    res = client.post("/api/v1/auth/login", json={"email": "existing@example.com", "password": "Passw0rd!x"})
    assert res.status_code == 200


def test_an_invited_person_still_joins_when_closed(client, db, closed):
    token = _create_invite(db, "invited@example.com", "technician")
    res = client.post("/api/v1/auth/accept-invite", json={"token": token, "name": "Invited", "password": "Passw0rd!x"})
    assert res.status_code == 201
    assert res.json()["role"] == "technician"


# ── OAuth ───────────────────────────────────────────────────────────────────

def test_first_oauth_sign_in_is_refused_when_closed(db, closed):
    with pytest.raises(HTTPException) as refused:
        _oauth_upsert(db, "stranger@example.com", "Stranger", "google", "g-1")
    assert refused.value.status_code == 403
    assert db.query(User).filter(User.email == "stranger@example.com").first() is None


def test_oauth_sign_in_with_an_existing_account_still_works_when_closed(db, closed):
    # found by the provider and its own identifier
    user = _existing(db)
    user.oauth_provider, user.oauth_id, user.password_hash = "github", "gh-1", None
    db.flush()
    signed_in = _oauth_upsert(db, user.email, "Existing", "github", "gh-1")
    assert signed_in.id == user.id
    assert signed_in.role == "technician"


def test_first_oauth_sign_in_creates_a_viewer_when_open(db):
    user = _oauth_upsert(db, "open@example.com", "Open", "google", "g-2")
    assert user.role == "viewer"


def test_microsoft_first_sign_in_is_refused_when_closed(db, closed):
    with pytest.raises(HTTPException) as refused:
        _microsoft_user(db, "ms-closed", "ms@example.com", "Ms")
    assert refused.value.status_code == 403
    assert db.query(User).filter(User.email == "ms@example.com").first() is None


def test_microsoft_identity_made_earlier_signs_in_when_closed(db, monkeypatch):
    created = _microsoft_user(db, "ms-earlier", "earlier@example.com", "Earlier")
    monkeypatch.setattr(settings, "registration_open", False)
    assert _microsoft_user(db, "ms-earlier", "earlier@example.com", "Earlier").id == created.id


def test_microsoft_closed_site_does_not_say_whether_an_address_has_an_account(db, closed):
    _existing(db, "clash@example.com")
    for address in ("clash@example.com", "nobody@example.com"):
        with pytest.raises(HTTPException) as refused:
            _microsoft_user(db, "ms-clash", address, "Clash")
        assert refused.value.status_code == 403


def test_microsoft_email_clash_answers_409_when_open(db):
    _existing(db, "clash@example.com")
    with pytest.raises(HTTPException) as refused:
        _microsoft_user(db, "ms-clash", "clash@example.com", "Clash")
    assert refused.value.status_code == 409


# ── python -m app.scripts.create_admin ──────────────────────────────────────

def test_create_admin_makes_an_admin_with_a_hashed_password(db):
    user = create_admin(db, "first@example.com", "Passw0rd!x")
    assert user.role == "admin"
    assert user.password_hash != "Passw0rd!x"
    assert verify_password("Passw0rd!x", user.password_hash)


def test_create_admin_works_when_registration_is_closed(db, closed):
    assert create_admin(db, "first@example.com", "Passw0rd!x").role == "admin"


def test_create_admin_refuses_an_email_that_already_has_an_account(db):
    _existing(db, "taken@example.com")
    with pytest.raises(AdminNotCreated) as refused:
        create_admin(db, "taken@example.com", "Passw0rd!x")
    assert "already exists" in str(refused.value)
    assert db.query(User).filter(User.email == "taken@example.com").one().role == "technician"


@pytest.mark.parametrize("password", ["short1A", "alllowercase1", "NoDigitsHere", "A1" + "x" * 80])
def test_create_admin_applies_the_same_password_rules_as_the_api(db, password):
    with pytest.raises(AdminNotCreated) as refused:
        create_admin(db, "weak@example.com", password)
    # the refusal says what is wrong and never repeats the password
    assert password not in str(refused.value)
    assert db.query(User).filter(User.email == "weak@example.com").first() is None


def test_create_admin_refuses_a_bad_email(db):
    with pytest.raises(AdminNotCreated):
        create_admin(db, "not-an-email", "Passw0rd!x")


def test_create_admin_writes_an_audit_entry_without_a_request(db):
    user = create_admin(db, "audited@example.com", "Passw0rd!x")
    row = db.execute(
        text("SELECT user_id, detail FROM audit_log WHERE action = 'admin_created' AND resource_id = :id"),
        {"id": str(user.id)},
    ).one()
    assert row.user_id == "system"
    assert "Passw0rd" not in (row.detail or "")
