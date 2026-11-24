"""
Device keys: stored as a keyed hash and never read back, found by a public id, the same answer and cost for an unknown and a
wrong key, upgraded from clear storage and rotated only by an admin or the owner.
"""

import secrets
import uuid

import pytest
from passlib.context import CryptContext
from sqlalchemy import text

from app.models.device import Device
from app.models.user import User
from app.services import device_keys
from tests._shape import plain

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_PASSWORD = "Passw0rd!x"


def _user(db, email, role):
    user = User(name=email, email=email, password_hash=_pwd_ctx.hash(_PASSWORD), role=role)
    db.add(user)
    db.flush()
    return user


def _bearer(user):
    from app.routes.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'role': user.role})}"}


def _post(client, device, key=None, **fields):
    return client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), "temperature": 22.0, **fields},
        headers={"X-API-Key": key if key is not None else device.api_key},
    )


# -- storage ----------------------------------------------------------------------------------

def test_a_new_machine_shows_its_key_once_and_the_database_never_holds_it(client, db, auth_headers):
    res = client.post("/api/v1/devices", json={"name": "Press", "location": "Hall", "type": "esp32"}, headers=auth_headers)
    assert res.status_code == 201
    key = res.json()["api_key"]
    assert len(key) == 43
    row = db.execute(
        text("SELECT api_key, key_id, key_hash, to_jsonb(d)::text AS whole FROM devices d WHERE id = CAST(:i AS uuid)"),
        {"i": res.json()["id"]},
    ).one()
    # nothing stored is the key: the clear column is empty and the whole row does not contain it
    assert row.api_key is None
    assert row.key_id == key[:8]
    assert row.key_hash == device_keys.hash_key(key) and key not in row.whole
    # the key works for ingest
    machine = db.get(Device, uuid.UUID(res.json()["id"]))
    assert _post(client, machine, key=key).status_code == 201


def test_no_read_route_returns_a_key(client, db, auth_headers, device):
    # the list and the single read carry no key at all. Only registration and rotation return one, once
    listing = client.get("/api/v1/devices", headers=auth_headers)
    assert listing.status_code == 200
    assert all("api_key" not in item for item in listing.json())
    assert "api_key" not in client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()
    assert device.api_key not in listing.text


def test_a_loaded_machine_cannot_give_its_key_back(db, device):
    key = device.api_key
    db.expire_all()
    db.flush()
    fresh = db.get(Device, device.id)
    # the instance that made the key still has it in memory. A row read from the database has only the id and the hash
    assert fresh.key_hash == device_keys.hash_key(key)
    stored = db.execute(text("SELECT api_key FROM devices WHERE id = CAST(:i AS uuid)"), {"i": str(device.id)}).scalar()
    assert stored is None


def test_the_hash_is_keyed_to_the_server_secret_through_the_shared_key_helper(monkeypatch):
    from app.config import settings
    from app.services import keys

    first = device_keys.hash_key("k" * 43)
    assert keys.derive_key("device_key") in (keys.verification_keys("device_key"))
    monkeypatch.setattr(settings, "secret_key", "another server secret key that is long enough for tests")
    assert device_keys.hash_key("k" * 43) != first


def test_a_rotated_server_key_keeps_every_machine_working_and_moves_it_to_the_new_key(client, db, device, monkeypatch):
    from app.config import settings

    old_hash = device.key_hash
    monkeypatch.setattr(settings, "secret_key_previous", settings.secret_key)
    monkeypatch.setattr(settings, "secret_key", "the key after the rotation, long enough for the tests to run")
    # the stored hash was made under the previous key. The machine still posts and is re-hashed under the new one
    assert _post(client, device).status_code == 201
    assert device.key_hash != old_hash and device.key_hash == device_keys.hash_key(device.api_key)
    # once the previous key is dropped the machine, now hashed under the new key, keeps working
    monkeypatch.setattr(settings, "secret_key_previous", "")
    assert _post(client, device).status_code == 201


def test_a_machine_not_yet_moved_is_locked_out_only_when_the_previous_key_is_dropped(client, db, device, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "secret_key", "the key after the rotation, long enough for the tests to run")
    monkeypatch.setattr(settings, "secret_key_previous", "")
    assert _post(client, device).status_code == 401


def test_a_wrong_key_costs_the_same_while_a_previous_key_is_set(client, db, device, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "secret_key_previous", "an earlier key that is long enough for the tests too")
    calls = []
    real = device_keys.hash_key
    monkeypatch.setattr(device_keys, "hash_key", lambda key, previous=False: calls.append(previous) or real(key, previous))
    _post(client, device, key=device.api_key[:8] + "x" * 35)
    known = list(calls)
    calls.clear()
    _post(client, device, key="zzzzzzzz" + "y" * 35)
    assert known == calls == [False, True]


# -- the check --------------------------------------------------------------------------------

def test_an_unknown_key_and_a_wrong_key_get_the_same_answer_and_the_same_work(client, db, device, monkeypatch):
    calls = []
    real = device_keys.hash_key
    monkeypatch.setattr(device_keys, "hash_key", lambda key, previous=False: calls.append(key) or real(key, previous))
    wrong = device.api_key[:8] + "x" * 35          # a known key id with the wrong rest
    unknown = "zzzzzzzz" + "y" * 35                  # an id nobody has
    a = _post(client, device, key=wrong)
    n_wrong = len(calls)
    calls.clear()
    b = _post(client, device, key=unknown)
    n_unknown = len(calls)
    assert a.status_code == b.status_code == 401
    assert plain(a) == plain(b) == {"detail": "Invalid API key"}
    # the same number of hashes in both: a key id that exists cannot be told from one that does not by the time taken
    assert n_wrong == n_unknown == 1


@pytest.mark.parametrize("presented", ["", "short", "x" * 500])
def test_odd_keys_are_refused_the_same_way(client, device, presented):
    res = client.post(
        "/api/v1/telemetry", json={"device_id": str(device.id), "temperature": 1.0}, headers={"X-API-Key": presented},
    )
    assert res.status_code in (401, 422)
    if res.status_code == 401:
        assert plain(res) == {"detail": "Invalid API key"}


def test_the_comparison_is_constant_time(monkeypatch):
    seen = []
    real = device_keys.hmac.compare_digest
    monkeypatch.setattr(device_keys.hmac, "compare_digest", lambda a, b: seen.append(1) or real(a, b))
    class _Db:
        def query(self, *_):
            class Q:
                def filter(self, *_):
                    return self
                def first(self):
                    return None
            return Q()
    assert device_keys.find_device(_Db(), "unknown-key-1234") is None
    assert seen, "an unknown key is still compared, against a stand-in"


# -- upgrading keys held in clear -------------------------------------------------------------

def _legacy_device(db, key):
    db.execute(
        text("INSERT INTO devices (id, name, api_key, key_id) VALUES (CAST(:i AS uuid), 'Old', :k, :kid)"),
        {"i": "00000000-0000-4000-8000-0000000000aa", "k": key, "kid": key[:8]},
    )
    return db.get(Device, uuid.UUID("00000000-0000-4000-8000-0000000000aa"))


def test_the_start_up_upgrade_hashes_old_keys_and_is_safe_to_run_twice(db):
    key = secrets.token_urlsafe(32)
    _legacy_device(db, key)
    assert device_keys.upgrade_legacy_keys(db) == 1
    row = db.execute(text("SELECT api_key, key_hash FROM devices WHERE name = 'Old'")).one()
    assert row.api_key is None and row.key_hash == device_keys.hash_key(key)
    assert device_keys.upgrade_legacy_keys(db) == 0


def test_an_old_machine_that_posts_before_the_upgrade_is_hashed_on_the_spot(client, db):
    key = secrets.token_urlsafe(32)
    old = _legacy_device(db, key)
    res = client.post("/api/v1/telemetry", json={"device_id": str(old.id), "temperature": 20.0}, headers={"X-API-Key": key})
    assert res.status_code == 201
    row = db.execute(text("SELECT api_key, key_hash FROM devices WHERE name = 'Old'")).one()
    assert row.api_key is None and row.key_hash == device_keys.hash_key(key)
    wrong = client.post("/api/v1/telemetry", json={"device_id": str(old.id), "temperature": 20.0}, headers={"X-API-Key": key[:8] + "q" * 35})
    assert wrong.status_code == 401


# -- rotation ---------------------------------------------------------------------------------

def test_rotation_returns_a_new_key_once_and_the_old_one_stops(client, db, auth_headers, device):
    old = device.api_key
    res = client.post(f"/api/v1/devices/{device.id}/rotate-key", json={"password": "Admin1234!"}, headers=auth_headers)
    assert res.status_code == 200
    new = res.json()["api_key"]
    assert new != old and len(new) == 43
    assert _post(client, device, key=old).status_code == 401
    assert _post(client, device, key=new).status_code == 201
    assert "api_key" not in client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()


def test_a_technician_cannot_rotate_the_key_of_a_machine_nobody_owns(client, db):
    tech = _user(db, "rot-tech@example.com", "technician")
    shared = Device(name="Shared", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32))
    db.add(shared)
    db.flush()
    res = client.post(f"/api/v1/devices/{shared.id}/rotate-key", json={"password": _PASSWORD}, headers=_bearer(tech))
    assert res.status_code == 403
    # the real node still works
    assert _post(client, shared).status_code == 201


def test_a_technician_can_rotate_their_own_machine_and_an_admin_any(client, db):
    tech = _user(db, "own-tech@example.com", "technician")
    admin = _user(db, "own-admin@example.com", "admin")
    mine = Device(name="Mine", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32), owner_id=tech.id)
    other = Device(name="Other", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32))
    db.add_all([mine, other])
    db.flush()
    assert client.post(f"/api/v1/devices/{mine.id}/rotate-key", json={"password": _PASSWORD}, headers=_bearer(tech)).status_code == 200
    assert client.post(f"/api/v1/devices/{other.id}/rotate-key", json={"password": _PASSWORD}, headers=_bearer(admin)).status_code == 200
