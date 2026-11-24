"""
The shared API conventions: one error shape with a code, the request id, paging, patching, the default limit, counters that
fall back to memory, moved routes with deprecated aliases and service accounts.
"""

import logging
import uuid

import pytest
from fastapi import Depends, FastAPI, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app import errors
from app.config import settings
from app.deps import Page, set_total
from app.errors import CODES, ApiError, Code
from app.models.api_token import ApiToken
from app.models.user import User
from app.patching import apply_patch
from app.routes.moved import SUNSET
from app.services import counters, token_access
from tests.test_access_tokens import PASSWORD, _bearer, _make, _session, _user

PAYLOAD = {"name": "Jane", "email": "jane@example.com", "subject": "Hi", "message": "Hello there", "turnstile_token": "x"}


# ── one shape for every error ───────────────────────────────────────────────

def test_every_error_is_code_detail_and_request_id(client, db):
    missing = client.get("/api/v1/nothing-here")
    assert missing.status_code == 404
    assert set(missing.json()) == {"code", "detail", "request_id"} and missing.json()["code"] == "not_found"
    assert missing.json()["request_id"] == missing.headers["X-Request-ID"]
    # an HTTPException not yet moved over still has the shape, with a code from its status
    user = _user(db, "shape1@test.com", "viewer")
    refused = client.get("/api/v1/auth/users", headers=_session(user))
    assert refused.status_code == 403 and set(refused.json()) == {"code", "detail", "request_id"}
    # a moved one has its own code
    unknown = client.get(f"/api/v1/tokens/{uuid.uuid4()}/x", headers=_session(user))
    assert unknown.status_code == 404
    gone = client.delete("/api/v1/tokens/000000000000", headers=_session(user))
    assert (gone.status_code, gone.json()["code"]) == (404, "token_not_found")


def test_validation_has_a_sentence_and_an_errors_list(client, db):
    user = _user(db, "shape2@test.com", "viewer")
    res = client.post("/api/v1/auth/tokens", json={"name": "", "scope": "root", "password": PASSWORD}, headers=_session(user))
    body = res.json()
    assert res.status_code == 422 and body["code"] == "validation_failed" and isinstance(body["detail"], str)
    assert {"loc", "msg", "type"} == set(body["errors"][0]) and body["request_id"]
    # the rejected input is never echoed
    assert "root" not in str(body["errors"]) or "input" not in body["errors"][0]


def test_the_request_id_is_taken_only_when_it_is_safe(client):
    kept = client.get("/", headers={"X-Request-ID": "abc-123_DEF.456"})
    assert kept.headers["X-Request-ID"] == "abc-123_DEF.456"
    for bad in ("short", "x" * 65, "has space in it", "semi;colon;value", "<script>alert(1)</script>"):
        made = client.get("/", headers={"X-Request-ID": bad}).headers["X-Request-ID"]
        assert made != bad and len(made) == 32 and made.isalnum()


def test_codes_are_unique_snake_case_and_a_plain_http_exception_gets_a_generic_one():
    assert len(CODES) == len([n for n, v in vars(Code).items() if n.isupper()])
    assert all(c == c.lower() and " " not in c for c in CODES)
    assert errors.code_for_status(404) == "not_found" and errors.code_for_status(418) == "error_418"


def test_an_unhandled_failure_is_a_json_500_with_a_request_id_and_nothing_else():
    app = FastAPI()
    errors.install(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret detail that must not reach the client")

    res = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert res.status_code == 500 and res.json()["code"] == "internal_error"
    assert "secret" not in res.text


# ── limits ──────────────────────────────────────────────────────────────────

def test_a_429_carries_retry_after_and_the_rate_limit_headers_in_the_one_shape(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    statuses = [client.post("/api/v1/contact", json=PAYLOAD).status_code for _ in range(4)]
    assert statuses[:3] == [204] * 3 and statuses[3] == 429
    res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 429 and res.json()["code"] == "rate_limited"
    assert int(res.headers["Retry-After"]) >= 1 and res.headers["X-RateLimit-Limit"] == "3" and res.headers["X-RateLimit-Remaining"] == "0"
    assert res.headers["X-RateLimit-Reset"].isdigit()


def test_the_default_limit_counts_a_public_route_by_address_and_leaves_device_keys_alone(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_anonymous", "2/minute")
    # GET / has no limit of its own, so the default counts it
    codes = [client.get("/").status_code for _ in range(3)]
    assert codes[:2] == [200, 200] and codes[2] == 429
    # a device key route is never counted in the default class, so the ingest allowance is the only limit it has
    bad = [client.post("/api/v1/telemetry", json={"device_id": "x", "temperature": 1}, headers={"X-API-Key": "nope"}).status_code for _ in range(5)]
    assert set(bad) == {401}


def test_the_default_limit_for_a_signed_in_account_is_counted_by_account(client, db, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_signed_in", "3/minute")
    one, two = _user(db, "lim-a@test.com", "viewer"), _user(db, "lim-b@test.com", "viewer")
    codes = [client.get("/api/v1/devices", headers=_session(one)).status_code for _ in range(4)]
    assert codes[:3] == [200] * 3 and codes[3] == 429
    # another account at the same address has its own share
    assert client.get("/api/v1/devices", headers=_session(two)).status_code == 200


def test_counters_fall_back_to_memory_with_one_warning_when_redis_fails(monkeypatch, caplog):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1")
    store = counters.Counters("test:")
    with caplog.at_level(logging.WARNING):
        values = [store.incr("k", 60) for _ in range(3)]
    assert values == [1, 2, 3]
    assert caplog.text.count("fell back to memory") == 1


# ── paging and patching ─────────────────────────────────────────────────────

def _paged_app():
    app = FastAPI()
    errors.install(app)

    @app.get("/things")
    def things(response: Response, page: Page = Depends(Page)):
        set_total(response, 1000)
        return {"limit": page.limit, "offset": page.offset}

    @app.get("/big")
    def big(page: Page = Depends(Page.up_to(500, default=100))):
        return {"limit": page.limit}

    return TestClient(app)


def test_page_defaults_caps_and_accepts_skip_as_an_alias():
    c = _paged_app()
    assert c.get("/things").json() == {"limit": 50, "offset": 0}
    assert c.get("/things?limit=200&offset=5").json() == {"limit": 200, "offset": 5}
    assert c.get("/things?skip=7").json()["offset"] == 7
    assert c.get("/things").headers["X-Total-Count"] == "1000"
    for bad in ("limit=201", "limit=0", "offset=-1", "offset=100001"):
        assert c.get(f"/things?{bad}").status_code == 422, bad
    assert c.get("/big").json() == {"limit": 100} and c.get("/big?limit=500").status_code == 200 and c.get("/big?limit=501").status_code == 422


class _Row:
    def __init__(self):
        self.name, self.owner_id, self.note = "a", "o", "n"


class _Body(BaseModel):
    name: str | None = None
    owner_id: str | None = None
    note: str | None = None


def test_apply_patch_keeps_what_is_left_out_and_clears_only_what_is_named():
    row = _Row()
    assert apply_patch(row, _Body(name="b"), clearable={"owner_id"}) == ["name"] and (row.name, row.owner_id) == ("b", "o")
    assert apply_patch(row, _Body(owner_id=None), clearable={"owner_id"}) == ["owner_id"] and row.owner_id is None
    with pytest.raises(ApiError) as refused:
        apply_patch(row, _Body(name=None), clearable={"owner_id"})
    assert refused.value.status_code == 422 and refused.value.code == "validation_failed"
    assert row.name == "b"
    assert apply_patch(row, {"note": "n"}) == []


# ── moved routes ────────────────────────────────────────────────────────────

def test_an_old_path_is_a_deprecated_alias_with_the_same_answer(client, db):
    admin = _user(db, "mv1@test.com", "admin")
    old = client.get("/api/v1/auth/users", headers=_session(admin))
    new = client.get("/api/v1/users", headers=_session(admin))
    assert old.status_code == new.status_code == 200 and old.json() == new.json()
    assert old.headers["Deprecation"] == "true" and old.headers["Sunset"] == SUNSET
    assert old.headers["Link"] == '</api/v1/users>; rel="successor-version"'
    assert "Deprecation" not in new.headers and new.headers["X-Total-Count"] == old.headers["X-Total-Count"]
    # both are refused the same way to a person who is not an admin and to an API token
    viewer = _user(db, "mv2@test.com", "viewer")
    for path in ("/api/v1/auth/users", "/api/v1/users", "/api/v1/auth/invitations", "/api/v1/invitations"):
        assert client.get(path, headers=_session(viewer)).status_code == 403, path
    token = _make(client, admin, "admin")["token"]
    for path in ("/api/v1/auth/users", "/api/v1/users", "/api/v1/auth/invitations", "/api/v1/invitations"):
        res = client.get(path, headers=_bearer(token))
        assert (res.status_code, res.json()["code"]) == (403, "session_required"), path


def test_the_fleet_summary_has_a_new_path_and_the_old_one_is_deprecated(client, db):
    user = _user(db, "mv3@test.com", "viewer")
    new = client.get("/api/v1/fleet/summary", headers=_session(user))
    old = client.get("/api/v1/health/summary", headers=_session(user))
    assert new.status_code == old.status_code == 200 and new.json() == old.json() and old.headers["Deprecation"] == "true"
    assert client.get("/livez").json() == {"status": "ok"}


def test_an_invitation_answer_has_an_id_and_the_new_path_works(client, db):
    admin = _user(db, "mv4@test.com", "admin")
    res = client.post("/api/v1/invitations", json={"email": "newbie@test.com", "role": "viewer"}, headers=_session(admin))
    assert res.status_code == 201 and uuid.UUID(res.json()["id"]) and res.json()["message"] == res.json()["detail"]
    listed = client.get("/api/v1/invitations", headers=_session(admin)).json()
    assert [r["email"] for r in listed] == ["newbie@test.com"]
    assert client.request("DELETE", f"/api/v1/invitations/{res.json()['id']}", json={"password": PASSWORD}, headers=_session(admin)).status_code == 204


# ── API tokens: self-revoke and service accounts ────────────────────────────

def test_a_token_may_revoke_itself_and_nothing_else(client, db):
    user = _user(db, "sr1@test.com", "technician")
    one, two = _make(client, user, "read"), _make(client, user, "read", name="other")
    assert client.delete(f"/api/v1/tokens/{two['id']}", headers=_bearer(one["token"])).status_code == 403
    assert client.delete("/api/v1/tokens/current", headers=_bearer(one["token"])).status_code == 204
    assert client.get("/api/v1/auth/whoami", headers=_bearer(one["token"])).status_code == 401
    assert client.get("/api/v1/auth/whoami", headers=_bearer(two["token"])).status_code == 200
    # a session has no token to revoke
    refused = client.delete("/api/v1/tokens/current", headers=_session(user))
    assert (refused.status_code, refused.json()["code"]) == (400, "no_token_in_use")


def _service(client, admin, role="viewer", name="ci bot"):
    res = client.post("/api/v1/service-accounts", json={"name": name, "role": role, "password": PASSWORD}, headers=_session(admin))
    assert res.status_code == 201, res.text
    return res.json()


def test_only_an_admin_with_proof_makes_a_service_account(client, db):
    admin = _user(db, "sv1@test.com", "admin")
    tech = _user(db, "sv2@test.com", "technician")
    assert client.post("/api/v1/service-accounts", json={"name": "x", "password": PASSWORD}, headers=_session(tech)).status_code == 403
    assert client.post("/api/v1/service-accounts", json={"name": "x"}, headers=_session(admin)).status_code == 400
    made = _service(client, admin, "technician")
    assert made["is_service"] is True and made["role"] == "technician" and made["email"].endswith("@service.example.com")
    token = _make(client, admin, "admin")["token"]
    refused = client.post("/api/v1/service-accounts", json={"name": "x", "password": PASSWORD}, headers=_bearer(token))
    assert (refused.status_code, refused.json()["code"]) == (403, "session_required")


def test_a_service_account_cannot_sign_in_by_any_route(client, db):
    admin = _user(db, "sv3@test.com", "admin")
    made = _service(client, admin)
    email = made["email"]
    account = db.get(User, uuid.UUID(made["id"]))
    assert account.password_hash is None and not account.totp_enabled and account.oauth_provider is None
    # the sign-in route answers for it exactly as for an address that has no account
    known = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}, headers={"X-Real-IP": "10.1.1.1"})
    unknown = client.post("/api/v1/auth/login", json={"email": "svc-nobody@service.example.com", "password": PASSWORD}, headers={"X-Real-IP": "10.1.1.2"})
    assert (known.status_code, known.json()["code"], known.json()["detail"]) == (unknown.status_code, unknown.json()["code"], unknown.json()["detail"])
    assert known.status_code == 401
    # a password set by hand still does not let it in
    from app.routes.auth import hash_password
    account.password_hash = hash_password(PASSWORD)
    db.flush()
    again = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}, headers={"X-Real-IP": "10.1.1.3"})
    assert (again.status_code, again.json()["code"]) == (401, "invalid_credentials")
    # a session token minted for it (by someone holding the signing key) is refused
    assert client.get("/api/v1/auth/me", headers=_session(account)).status_code == 401
    # a session cannot be started for it by any helper
    from app.routes.auth import _start_session
    with pytest.raises(ApiError):
        _start_session(db, account)
    # no reset link, whether an admin asks or a link is forged
    reset = client.post(f"/api/v1/users/{account.id}/reset-link", json={"password": PASSWORD}, headers=_session(admin))
    assert (reset.status_code, reset.json()["code"]) == (409, "service_account_refused")
    from datetime import timedelta
    from app.routes.admin_users import _password_marker
    from app.routes.auth import _encode
    link = _encode({"sub": str(account.id), "ver": 0, "pw": _password_marker(account)}, "reset", timedelta(hours=1))
    forged = client.post("/api/v1/auth/reset-password", json={"token": link, "password": "Brand-New-Passw0rd"})
    assert (forged.status_code, forged.json()["code"]) == (400, "reset_link_invalid")


def test_an_admin_makes_tokens_for_a_service_account_and_they_work_as_that_account(client, db):
    admin = _user(db, "sv4@test.com", "admin")
    service = _service(client, admin, "technician")
    made = client.post("/api/v1/tokens", json={"name": "ci", "scope": "operate", "account_id": service["id"], "password": PASSWORD}, headers=_session(admin))
    assert made.status_code == 201 and made.json()["account_id"] == service["id"]
    who = client.get("/api/v1/auth/whoami", headers=_bearer(made.json()["token"])).json()
    assert who["id"] == service["id"] and who["role"] == "technician" and who["is_service"] is True
    row = db.get(ApiToken, made.json()["id"])
    assert str(row.user_id) == service["id"] and row.created_by == admin.id
    # an admin token for a service account that is not an admin is refused and an admin sees and revokes its tokens
    no = client.post("/api/v1/tokens", json={"name": "x", "scope": "admin", "account_id": service["id"], "password": PASSWORD}, headers=_session(admin))
    assert (no.status_code, no.json()["code"]) == (403, "token_scope_forbidden")
    listed = client.get(f"/api/v1/tokens?account_id={service['id']}", headers=_session(admin)).json()
    assert [t["id"] for t in listed] == [made.json()["id"]] and listed[0]["created_by"] == str(admin.id)
    # the admin's own list does not show it
    assert client.get("/api/v1/tokens", headers=_session(admin)).json() == []
    assert client.delete(f"/api/v1/tokens/{made.json()['id']}", headers=_session(admin)).status_code == 204
    assert client.get("/api/v1/auth/whoami", headers=_bearer(made.json()["token"])).status_code == 401


def test_tokens_for_a_service_account_are_an_admin_matter_and_never_reach_a_person(client, db):
    admin = _user(db, "sv5@test.com", "admin")
    tech = _user(db, "sv6@test.com", "technician")
    service = _service(client, admin)
    body = {"name": "x", "scope": "read", "password": PASSWORD}
    # a non-admin cannot make or list tokens for a service account
    assert client.post("/api/v1/tokens", json={**body, "account_id": service["id"]}, headers=_session(tech)).status_code == 403
    assert client.get(f"/api/v1/tokens?account_id={service['id']}", headers=_session(tech)).status_code == 403
    # not even an admin can make a token for another person's account this way: it answers as if there were no such account
    res = client.post("/api/v1/tokens", json={**body, "account_id": str(tech.id)}, headers=_session(admin))
    assert (res.status_code, res.json()["code"]) == (404, "user_not_found")
    # a technician cannot revoke a service account's token and the answer is the one for a token that is not there
    made = client.post("/api/v1/tokens", json={**body, "account_id": service["id"]}, headers=_session(admin)).json()
    assert client.delete(f"/api/v1/tokens/{made['id']}", headers=_session(tech)).status_code == 404


def test_deactivating_or_removing_a_service_account_ends_its_tokens_and_the_audit_names_the_admin(client, db):
    from sqlalchemy import text
    admin = _user(db, "sv7@test.com", "admin")
    service = _service(client, admin)
    made = client.post("/api/v1/tokens", json={"name": "ci", "scope": "read", "account_id": service["id"], "password": PASSWORD}, headers=_session(admin)).json()
    assert client.get("/api/v1/auth/whoami", headers=_bearer(made["token"])).status_code == 200
    assert client.post(f"/api/v1/users/{service['id']}/deactivate", json={"password": PASSWORD}, headers=_session(admin)).status_code == 204
    assert client.get("/api/v1/auth/whoami", headers=_bearer(made["token"])).status_code == 401
    rows = db.execute(text("SELECT user_id, detail FROM audit_log WHERE action IN ('service_account_created', 'token_created') AND (resource_id = :id OR resource_id = :tid)"),
                      {"id": service["id"], "tid": made["id"]}).all()
    assert rows and all(r.user_id == str(admin.id) for r in rows)
    assert any(f"account={service['id']}" in (r.detail or "") for r in rows)


# ── every 429, whoever raised it ────────────────────────────────────────────

def _check_429(res, where):
    assert res.status_code == 429, (where, res.status_code)
    assert res.json()["code"] in {"rate_limited", "token_account_rate_limited"}, where
    assert int(res.headers["Retry-After"]) >= 1, where
    assert res.headers["X-RateLimit-Remaining"] == "0" and res.headers["X-RateLimit-Reset"].isdigit(), where
    assert res.headers["X-RateLimit-Limit"].isdigit(), where


def test_a_429_from_each_kind_of_limit_has_retry_after_and_the_three_rate_limit_headers(client, db, monkeypatch):
    # the default class for no credential
    monkeypatch.setattr(settings, "rate_limit_anonymous", "1/minute")
    client.get("/")
    _check_429(client.get("/"), "anonymous default")
    # the default class for an account
    monkeypatch.setattr(settings, "rate_limit_signed_in", "1/minute")
    user = _user(db, "l429@test.com", "viewer")
    client.get("/api/v1/devices", headers=_session(user))
    _check_429(client.get("/api/v1/devices", headers=_session(user)), "signed-in default")
    # a route's own slowapi limit on a GET (30 a minute)
    monkeypatch.setattr(settings, "rate_limit_signed_in", "10000/minute")
    other = _user(db, "l429b@test.com", "viewer")
    last = None
    for _ in range(31):
        last = client.get("/api/v1/auth/sessions", headers=_session(other))
    _check_429(last, "slowapi own limit on a GET")
    # a limit raised by hand (the account ceiling of an API token)
    token = _make(client, other, "read")["token"]
    monkeypatch.setattr(token_access, "ACCOUNT_REQUESTS_PER_MINUTE", 1)
    client.get("/api/v1/auth/whoami", headers=_bearer(token))
    _check_429(client.get("/api/v1/auth/whoami", headers=_bearer(token)), "hand-raised")


def test_the_status_page_and_the_root_name_the_release_and_not_the_environment(client):
    status = client.get("/status").json()
    assert status["status"] in {"operational", "degraded"} and status["version"] == settings.release_version
    assert set(status) == {"status", "api", "database", "redis", "model", "version", "updated_at"} and status["updated_at"].endswith("Z")
    root = client.get("/").json()
    assert root == {"status": "ok", "service": "PHAEMOS API", "version": settings.release_version, "api_version": "v1"}
    assert "development" not in str(status).lower() and "development" not in str(root).lower()


# ── a trailing slash is a 404, never a redirect ─────────────────────────────

def test_a_trailing_slash_is_a_404_in_the_standard_shape_and_never_a_redirect(client, db):
    user = _user(db, "slash1@test.com", "viewer")
    for method, path in (("POST", "/api/v1/telemetry/"), ("GET", "/api/v1/devices/"), ("GET", "/api/v1/tokens/"), ("GET", "/status/")):
        res = client.request(method, path, headers=_session(user), follow_redirects=False, json={} if method == "POST" else None)
        assert res.status_code == 404, (method, path, res.status_code)
        assert "location" not in res.headers
        assert set(res.json()) == {"code", "detail", "request_id"} and res.json()["code"] == "not_found"
    # the spelling the clients use still works
    assert client.get("/api/v1/devices", headers=_session(user)).status_code == 200


# ── a provider-only admin has no password and proves ownership by returning from the provider ─

def test_a_provider_only_admin_proves_it_on_the_new_admin_routes_and_for_an_api_token(client, db):
    from datetime import datetime, timedelta, timezone

    from app.models.user_session import UserSession
    from app.routes.auth import create_access_token

    boss = _user(db, "prov-admin@test.com", "admin")
    boss.password_hash, boss.oauth_provider, boss.oauth_id = None, "google", "g-prov-admin"
    db.flush()
    expires = datetime.now(timezone.utc) + timedelta(days=1)
    stale = UserSession(user_id=boss.id, current_jti="a", expires_at=expires)
    fresh = UserSession(user_id=boss.id, current_jti="b", expires_at=expires, provider_signin_at=datetime.now(timezone.utc))
    db.add_all([stale, fresh])
    db.flush()

    def headers(session):
        return {"Authorization": "Bearer " + create_access_token({"sub": str(boss.id), "role": "admin", "sid": str(session.id)})}

    service = {"name": "ci bot", "role": "viewer"}
    refused = client.post("/api/v1/service-accounts", json=service, headers=headers(stale))
    assert (refused.status_code, refused.json()["code"]) == (400, "provider_proof_required")
    made = client.post("/api/v1/service-accounts", json=service, headers=headers(fresh))
    assert made.status_code == 201
    # an API token for the provider-only admin
    token = {"name": "laptop", "scope": "admin"}
    assert client.post("/api/v1/tokens", json=token, headers=headers(stale)).status_code == 400
    assert client.post("/api/v1/tokens", json=token, headers=headers(fresh)).status_code == 201
    # an API token for the service account and a dangerous admin action on the account
    assert client.post("/api/v1/tokens", json={"name": "x", "scope": "read", "account_id": made.json()["id"]}, headers=headers(fresh)).status_code == 201
    assert client.post(f"/api/v1/users/{made.json()['id']}/deactivate", headers=headers(stale)).status_code == 400
    assert client.post(f"/api/v1/users/{made.json()['id']}/deactivate", headers=headers(fresh)).status_code == 204


# ── CORS: what a browser may send and read ──────────────────────────────────

def test_a_preflight_allows_the_convention_request_headers_and_only_the_known_origins(client):
    from app.cors import EXPOSED_HEADERS
    origin = settings.credentialed_origin_list[0]
    pre = client.options("/api/v1/devices", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,idempotency-key,x-request-id,content-type",
    })
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == origin
    allowed = pre.headers["access-control-allow-headers"].lower()
    assert "idempotency-key" in allowed and "x-request-id" in allowed
    assert pre.headers["access-control-allow-credentials"] == "true"
    # an origin that is not listed gets no permission
    bad = client.options("/api/v1/devices", headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"})
    assert bad.status_code == 400 and "access-control-allow-origin" not in bad.headers
    # a real cross-origin answer exposes every header the conventions send
    real = client.get("/status", headers={"Origin": origin})
    exposed = {h.strip().lower() for h in real.headers["access-control-expose-headers"].split(",")}
    assert {h.lower() for h in EXPOSED_HEADERS} <= exposed
    assert {"x-total-count", "x-next-before", "x-request-id", "retry-after", "x-ratelimit-limit", "x-ratelimit-remaining",
            "x-ratelimit-reset", "deprecation", "sunset", "link", "idempotent-replayed"} <= exposed
    evil = client.get("/status", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in evil.headers


# ── the log: one well-formed line for each request, never a query string ────

def test_each_request_writes_one_line_with_the_id_and_no_query_string_or_header(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.request"):
        res = client.get("/api/v1/auth/providers?token=SECRET-TOKEN-VALUE&x=1", headers={"X-Request-ID": "trace-0123456789", "X-Other": "HEADER-VALUE"})
    lines = [r for r in caplog.records if r.name == "app.request"]
    assert len(lines) == 1
    text = lines[0].getMessage()
    assert text.startswith("GET /api/v1/auth/providers -> 200 in ") and text.endswith(" ms")
    assert "SECRET-TOKEN-VALUE" not in caplog.text and "?" not in text and "HEADER-VALUE" not in caplog.text
    # the id the line carries through the format is the one the answer returned
    from app.logging_config import AddRequestId
    assert res.headers["X-Request-ID"] == "trace-0123456789"
    record = logging.LogRecord("app.request", logging.INFO, __file__, 1, "x", (), None)
    from app import request_id
    token = request_id.request_id_var.set("trace-0123456789")
    try:
        AddRequestId().filter(record)
    finally:
        request_id.request_id_var.reset(token)
    assert record.request_id == "trace-0123456789"


def test_the_probes_and_the_socket_are_not_logged_as_requests(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.request"):
        client.get("/livez")
        client.get("/")
    assert [r for r in caplog.records if r.name == "app.request"] == []


def test_a_line_on_the_access_logger_is_formatted_without_error_and_loses_its_query_string():
    """uvicorn's access formatter takes exactly five arguments. The filter that cuts a token out of a socket address used to
    empty them and every such line failed with 'not enough values to unpack'."""
    from uvicorn.logging import AccessFormatter

    errors = []

    class Recording(logging.StreamHandler):
        def handleError(self, record):  # noqa: N802
            errors.append(record)

    import io

    sink = io.StringIO()
    handler = Recording(sink)
    handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    access = logging.getLogger("uvicorn.access")
    old_raise = logging.raiseExceptions
    logging.raiseExceptions = True
    access.addHandler(handler)
    previous = access.level
    access.setLevel(logging.INFO)
    try:
        access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/ws/telemetry/abc?token=SECRET-SOCKET-TOKEN", "1.1", 200)
        # a record that is not in the five argument shape is still cut and still formats
        logging.getLogger("uvicorn.error").info("WebSocket /ws/x?token=SECRET-SOCKET-TOKEN accepted")
    finally:
        access.removeHandler(handler)
        access.setLevel(previous)
        logging.raiseExceptions = old_raise
    assert errors == []
    assert "SECRET-SOCKET-TOKEN" not in sink.getvalue() and "GET /ws/telemetry/abc" in sink.getvalue()


def test_with_the_access_log_on_every_line_is_written_once_per_handler_whole_and_cut():
    """The development server runs with the access log on. Two handlers see the access record (uvicorn's own and one that
    formats it plainly) and neither may fail or show the query string."""
    import io

    from uvicorn.logging import AccessFormatter

    from app.logging_config import configure_logging

    configure_logging("development")
    errors, outputs = [], []

    class Recording(logging.StreamHandler):
        def handleError(self, record):  # noqa: N802
            errors.append(record)

    access = logging.getLogger("uvicorn.access")
    handlers = []
    for formatter in (AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False), logging.Formatter("%(message)s")):
        sink = io.StringIO()
        handler = Recording(sink)
        handler.setFormatter(formatter)
        access.addHandler(handler)
        handlers.append(handler)
        outputs.append(sink)
    old_raise, old_level = logging.raiseExceptions, access.level
    logging.raiseExceptions = True
    access.setLevel(logging.INFO)
    try:
        access.info('%s - "%s %s HTTP/%s" %d', "192.168.97.1:38052", "GET", "/api/v1/alerts?limit=5&token=SECRET-QUERY-TOKEN", "1.1", 200)
    finally:
        for handler in handlers:
            access.removeHandler(handler)
        access.setLevel(old_level)
        logging.raiseExceptions = old_raise
    assert errors == []
    for sink in outputs:
        written = sink.getvalue().strip().splitlines()
        assert len(written) == 1 and "SECRET-QUERY-TOKEN" not in written[0] and "/api/v1/alerts" in written[0] and "?" not in written[0]


def test_a_message_that_holds_a_question_mark_keeps_its_placeholders():
    from app.logging_config import StripQueryStrings

    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, "ready? %s then %s", ("a?b=c", "d"), None)
    StripQueryStrings().filter(record)
    assert record.getMessage() == "ready? a then d"
    bare = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, "GET /ws/x?token=SECRET accepted", (), None)
    StripQueryStrings().filter(bare)
    assert bare.getMessage() == "GET /ws/x accepted"
