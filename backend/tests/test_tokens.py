import base64
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

from app.config import settings
from app.routes.auth import (
    _create_invite, _encode, create_access_token, create_refresh_token, decode_token,
)

_CLAIMS = {"sub": "0b7c5a52-6f0e-4a8e-9a39-2f3f3c1d9e11", "role": "admin", "ver": 3}


def _segments(token):
    return token.split(".")


def _b64(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(segment: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


# ── creating and verifying ────────────────────────────────────────────────────

def test_access_token_round_trips():
    payload = decode_token(create_access_token(_CLAIMS))
    assert payload["sub"] == _CLAIMS["sub"]
    assert payload["role"] == "admin"
    assert payload["ver"] == 3
    assert payload["type"] == "access"


def test_token_format_is_a_compact_hs256_jwt():
    token = create_access_token(_CLAIMS)
    header, body, signature = _segments(token)
    assert _unb64(header) == {"alg": "HS256", "typ": "JWT"}
    claims = _unb64(body)
    # expiry is stored as whole seconds since the epoch, as before.
    assert isinstance(claims["exp"], int)
    assert signature


def test_access_token_lifetime_matches_the_setting():
    before = datetime.now(timezone.utc)
    payload = decode_token(create_access_token(_CLAIMS))
    expected = before + timedelta(minutes=settings.access_token_expire_minutes)
    assert abs(payload["exp"] - expected.timestamp()) < 5


def test_session_version_defaults_to_zero():
    payload = decode_token(create_access_token({"sub": _CLAIMS["sub"], "role": "viewer"}))
    assert payload["ver"] == 0


def test_a_token_is_accepted_only_for_its_own_type():
    refresh = create_refresh_token(_CLAIMS)
    assert decode_token(refresh, "refresh")["type"] == "refresh"
    with pytest.raises(HTTPException) as exc:
        decode_token(refresh)
    assert exc.value.status_code == 401


# ── expiry ────────────────────────────────────────────────────────────────────

def test_expired_token_is_refused():
    token = _encode(_CLAIMS, "access", timedelta(seconds=-1))
    with pytest.raises(HTTPException) as exc:
        decode_token(token)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Could not validate token"


def test_expired_token_is_refused_by_a_protected_route(client):
    token = _encode(_CLAIMS, "access", timedelta(seconds=-1))
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


def test_expired_invite_is_refused(client, db):
    from app.models.invitation import Invitation
    token = _create_invite(db, "late@example.com", "viewer")
    db.query(Invitation).filter(Invitation.email == "late@example.com").update({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    db.flush()
    res = client.post("/api/v1/auth/accept-invite", json={"token": token, "name": "Late", "password": "Secret123!"})
    assert res.status_code == 400


def test_valid_invite_is_accepted_with_the_role_it_carries(client, db):
    token = _create_invite(db, "new@example.com", "technician")
    res = client.post("/api/v1/auth/accept-invite", json={"token": token, "name": "New", "password": "Secret123!"})
    assert res.status_code == 201
    assert res.json()["role"] == "technician"


def test_the_invite_read_route_is_gone(client, db):
    # it put the token in the path, which reaches proxy access logs. The token is only ever posted
    token = _create_invite(db, "gone@example.com", "viewer")
    assert client.get(f"/api/v1/auth/accept-invite/{token}").status_code in (404, 405)


# ── tampering ─────────────────────────────────────────────────────────────────

def test_changed_payload_is_refused():
    header, body, signature = _segments(create_access_token({**_CLAIMS, "role": "viewer"}))
    claims = _unb64(body)
    claims["role"] = "admin"
    with pytest.raises(HTTPException) as exc:
        decode_token(".".join([header, _b64(claims), signature]))
    assert exc.value.status_code == 401


def test_changed_signature_is_refused():
    header, body, signature = _segments(create_access_token(_CLAIMS))
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(HTTPException):
        decode_token(".".join([header, body, flipped]))


def test_token_signed_with_another_key_is_refused():
    token = jwt.encode(
        {**_CLAIMS, "type": "access", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "a-different-secret-key-of-enough-length", algorithm="HS256",
    )
    with pytest.raises(HTTPException):
        decode_token(token)


def test_unsigned_token_is_refused():
    claims = {**_CLAIMS, "type": "access",
              "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())}
    token = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}."
    with pytest.raises(HTTPException):
        decode_token(token)


def test_token_with_another_algorithm_is_refused():
    token = jwt.encode(
        {**_CLAIMS, "type": "access", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.secret_key, algorithm="HS512",
    )
    with pytest.raises(HTTPException):
        decode_token(token)


@pytest.mark.parametrize("token", ["", "not-a-token", "a.b", "a.b.c"])
def test_malformed_token_is_refused(token):
    with pytest.raises(HTTPException) as exc:
        decode_token(token)
    assert exc.value.status_code == 401


def test_tampered_token_is_refused_by_a_protected_route(client):
    header, body, signature = _segments(create_access_token(_CLAIMS))
    claims = _unb64(body)
    claims["ver"] = 0
    tampered = ".".join([header, _b64(claims), signature])
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert res.status_code == 401


def test_a_changed_or_invented_invite_is_refused(client, db):
    # an invitation is 256 random bits looked up by its hash, so changing one character or making one up, finds nothing
    real = _create_invite(db, "someone@example.com", "viewer")
    tampered = ("A" if real[0] != "A" else "B") + real[1:]
    res = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": tampered, "name": "Someone", "password": "Secret123!"},
    )
    assert res.status_code == 400
