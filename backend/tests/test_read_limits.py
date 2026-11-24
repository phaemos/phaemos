"""
Paging bounds on the device and telemetry lists, the owner rule on a machine and the slots taken by the heavy reads.
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from passlib.context import CryptContext

from app.models.telemetry import Telemetry
from app.models.user import User
from app.services import heavy_reads
from tests._shape import plain

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _user(db, role):
    u = User(name=role, email=f"{role}-{secrets.token_hex(3)}@test.com", password_hash=_pwd.hash("Passw0rd!x"), role=role)
    db.add(u)
    db.flush()
    return u


# -- the device list ---------------------------------------------------------------------------------

@pytest.mark.parametrize("query", ["skip=-1", "limit=0", "limit=-5", "limit=201", "limit=100000"])
def test_the_device_list_refuses_paging_that_is_out_of_bounds(client, auth_headers, query):
    assert client.get(f"/api/v1/devices?{query}", headers=auth_headers).status_code == 422


@pytest.mark.parametrize("query", ["skip=0&limit=1", "limit=200", "skip=5"])
def test_the_device_list_accepts_paging_inside_the_bounds(client, auth_headers, query):
    assert client.get(f"/api/v1/devices?{query}", headers=auth_headers).status_code == 200


# -- who may own a machine -----------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["viewer", "contractor"])
def test_a_machine_cannot_be_registered_with_an_owner_who_cannot_work_on_it(client, db, auth_headers, role):
    owner = _user(db, role)
    res = client.post("/api/v1/devices", json={"name": "Pump", "owner_id": str(owner.id)}, headers=auth_headers)
    assert (res.status_code, plain(res)) == (404, {"detail": "Owner not found"})


@pytest.mark.parametrize("role", ["admin", "technician"])
def test_an_admin_or_a_technician_can_own_a_machine(client, db, auth_headers, role):
    owner = _user(db, role)
    res = client.post("/api/v1/devices", json={"name": "Pump", "owner_id": str(owner.id)}, headers=auth_headers)
    assert res.status_code == 201 and res.json()["owner_id"] == str(owner.id)


@pytest.mark.parametrize("role", ["viewer", "contractor"])
def test_an_update_cannot_hand_a_machine_to_such_an_owner(client, db, auth_headers, device, role):
    owner = _user(db, role)
    res = client.patch(f"/api/v1/devices/{device.id}", json={"owner_id": str(owner.id)}, headers=auth_headers)
    assert (res.status_code, plain(res)) == (404, {"detail": "Owner not found"})
    db.refresh(device)
    assert device.owner_id is None


def test_an_update_can_hand_a_machine_to_a_technician(client, db, auth_headers, device):
    tech = _user(db, "technician")
    res = client.patch(f"/api/v1/devices/{device.id}", json={"owner_id": str(tech.id)}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["owner_id"] == str(tech.id)


# -- the telemetry list --------------------------------------------------------------------------------

@pytest.mark.parametrize("query", ["offset=-1", "limit=0", "limit=-1", "limit=5001"])
def test_the_telemetry_list_refuses_paging_that_is_out_of_bounds(client, device, auth_headers, query):
    assert client.get(f"/api/v1/telemetry/{device.id}?{query}", headers=auth_headers).status_code == 422


def test_the_telemetry_list_accepts_the_largest_page(client, device, auth_headers):
    assert client.get(f"/api/v1/telemetry/{device.id}?limit=5000&offset=0", headers=auth_headers).status_code == 200


def test_a_time_range_without_a_zone_is_read_as_utc_on_the_raw_read(client, db, device, auth_headers):
    now = datetime.now(timezone.utc)
    db.add(Telemetry(device_id=device.id, temperature=1.0, recorded_at=now - timedelta(minutes=30)))
    db.add(Telemetry(device_id=device.id, temperature=2.0, recorded_at=now - timedelta(hours=5)))
    db.flush()
    start = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    end = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    res = client.get(f"/api/v1/telemetry/{device.id}?from_ts={start}&to_ts={end}", headers=auth_headers)
    assert res.status_code == 200
    assert [r["temperature"] for r in res.json()] == [1.0]


# -- the heavy reads --------------------------------------------------------------------------------------

def _export_url(device):
    start = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"/api/v1/telemetry/export?device_id={device.id}&from_ts={start}"


def _bucket_url(device):
    start = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"/api/v1/telemetry/{device.id}?bucket=60&from_ts={start}"


def test_an_export_takes_a_slot_and_gives_it_back_when_the_stream_ends(client, db, device, auth_headers):
    heavy_reads.reset()
    db.add(Telemetry(device_id=device.id, temperature=1.0, recorded_at=datetime.now(timezone.utc)))
    db.flush()
    assert client.get(_export_url(device), headers=auth_headers).status_code == 200
    assert heavy_reads._running_total == 0 and not heavy_reads._running_by_user
    # the rate counted it
    assert sum(len(v) for k, v in heavy_reads._recent.items() if k[1] == "export") == 1


def test_an_export_over_the_rate_answers_429_before_the_stream_starts(client, device, auth_headers, monkeypatch):
    heavy_reads.reset()
    monkeypatch.setitem(heavy_reads.RATES, "export", 1)
    assert client.get(_export_url(device), headers=auth_headers).status_code == 200
    res = client.get(_export_url(device), headers=auth_headers)
    assert res.status_code == 429
    assert res.headers["Retry-After"] == "10"
    assert res.headers["content-type"].startswith("application/json")


def test_an_export_with_every_slot_taken_answers_429(client, admin_user, device, auth_headers):
    heavy_reads.reset()
    heavy_reads._running_by_user[str(admin_user.id)] = heavy_reads.MAX_AT_ONCE_PER_USER
    assert client.get(_export_url(device), headers=auth_headers).status_code == 429
    heavy_reads.reset()


def test_a_refused_export_does_not_leak_a_slot(client, device, auth_headers, monkeypatch):
    heavy_reads.reset()
    monkeypatch.setitem(heavy_reads.RATES, "export", 1)
    client.get(_export_url(device), headers=auth_headers)
    client.get(_export_url(device), headers=auth_headers)
    assert heavy_reads._running_total == 0


def test_a_bucketed_read_takes_a_slot_and_is_refused_when_none_is_free(client, admin_user, device, auth_headers):
    heavy_reads.reset()
    assert client.get(_bucket_url(device), headers=auth_headers).status_code == 200
    assert heavy_reads._running_total == 0
    heavy_reads._running_by_user[str(admin_user.id)] = heavy_reads.MAX_AT_ONCE_PER_USER
    assert client.get(_bucket_url(device), headers=auth_headers).status_code == 429
    heavy_reads.reset()


# -- the owner row is locked, lengths and the rule's machine ---------------------------------------------------

def test_the_owner_is_checked_with_a_row_lock(client, db, auth_headers, device):
    from sqlalchemy import event

    owner = _user(db, "technician")
    seen = []
    conn = db.get_bind()

    def record(conn_, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", record)
    try:
        client.patch(f"/api/v1/devices/{device.id}", json={"owner_id": str(owner.id)}, headers=auth_headers)
        client.post("/api/v1/devices", json={"name": "P", "owner_id": str(owner.id)}, headers=auth_headers)
    finally:
        event.remove(conn, "before_cursor_execute", record)
    locked = [q for q in seen if "FROM users" in q and "FOR UPDATE" in q]
    assert len(locked) == 2


def test_a_firmware_version_over_50_characters_is_a_422_and_not_a_500_and_status_is_not_writable(client, device, auth_headers):
    assert client.patch(f"/api/v1/devices/{device.id}", json={"firmware_version": "v" * 51}, headers=auth_headers).status_code == 422
    assert client.patch(f"/api/v1/devices/{device.id}", json={"firmware_version": "v" * 50}, headers=auth_headers).status_code == 200
    # status belongs to the system and is ignored on a device update, so a long one cannot reach the column
    ignored = client.patch(f"/api/v1/devices/{device.id}", json={"status": "s" * 21}, headers=auth_headers)
    assert ignored.status_code == 200 and ignored.json()["status"] != "s" * 21


def test_a_rule_for_an_unknown_machine_is_a_404(client, auth_headers):
    import uuid
    body = {"device_id": str(uuid.uuid4()), "metric": "temperature", "condition": "gt", "threshold": 1.0, "severity": "warning"}
    res = client.post("/api/v1/alert-rules", json=body, headers=auth_headers)
    assert (res.status_code, plain(res)) == (404, {"detail": "Device not found"})


def test_a_rule_for_a_real_machine_is_still_created(client, device, auth_headers):
    body = {"device_id": str(device.id), "metric": "temperature", "condition": "gt", "threshold": 1.0, "severity": "warning"}
    assert client.post("/api/v1/alert-rules", json=body, headers=auth_headers).status_code == 201
