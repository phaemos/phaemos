"""
The new health fields follow the machine access rule: admins and viewers read every machine, technicians read their
own and unowned machines and a refused machine answers like one that does not exist.
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from passlib.context import CryptContext

from app.models.alert import Alert
from app.models.device import Device
from app.models.device_health import DeviceHealth
from app.models.user import User
from tests._shape import plain

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
NOT_FOUND = {"detail": "Device not found"}


def _headers(user):
    from app.routes.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'role': user.role})}"}


def _user(db, email, role):
    u = User(name=email, email=email, password_hash=_pwd_ctx.hash("Passw0rd!x"), role=role)
    db.add(u)
    db.flush()
    return u


def _machine(db, name, owner=None, link_state="online"):
    d = Device(
        name=name, location="Lab", type="esp32", api_key=secrets.token_urlsafe(32),
        owner_id=owner.id if owner else None, link_state=link_state,
        last_seen=datetime.now(timezone.utc) - timedelta(seconds=3),
    )
    db.add(d)
    db.flush()
    db.add(DeviceHealth(device_id=d.id, boot_count=4, rssi=-70, faults={"bme280": "missing"}))
    db.flush()
    return d


@pytest.fixture
def admin(db):
    return _user(db, "hx-admin@test.com", "admin")


@pytest.fixture
def viewer(db):
    return _user(db, "hx-viewer@test.com", "viewer")


@pytest.fixture
def tech(db):
    return _user(db, "hx-tech@test.com", "technician")


@pytest.fixture
def other_tech(db):
    return _user(db, "hx-other@test.com", "technician")


@pytest.fixture
def stranger(db):
    return _user(db, "hx-stranger@test.com", "contractor")


@pytest.fixture
def mine(db, tech):
    return _machine(db, "mine", tech, "online")


@pytest.fixture
def theirs(db, other_tech):
    return _machine(db, "theirs", other_tech, "offline")


@pytest.fixture
def shared(db):
    return _machine(db, "shared", None, "late")


def test_health_is_returned_for_every_machine_an_admin_or_viewer_reads(client, admin, viewer, theirs):
    for user in (admin, viewer):
        res = client.get(f"/api/v1/devices/{theirs.id}", headers=_headers(user))
        assert res.status_code == 200
        body = res.json()
        assert body["link_state"] == "offline"
        assert body["health"]["boot_count"] == 4 and body["health"]["faults"] == {"bme280": "missing"}


def test_a_technician_reads_the_health_of_their_own_and_unowned_machines(client, tech, mine, shared):
    for device, state in ((mine, "online"), (shared, "late")):
        body = client.get(f"/api/v1/devices/{device.id}", headers=_headers(tech)).json()
        assert body["link_state"] == state and body["health"]["rssi"] == -70


def test_a_technician_cannot_read_another_technicians_health_and_it_looks_like_no_machine(client, tech, theirs):
    res = client.get(f"/api/v1/devices/{theirs.id}", headers=_headers(tech))
    assert (res.status_code, plain(res)) == (404, NOT_FOUND)
    missing = client.get("/api/v1/devices/00000000-0000-0000-0000-000000000000", headers=_headers(tech))
    assert (missing.status_code, plain(missing)) == (404, NOT_FOUND)


def test_the_device_list_carries_health_only_for_readable_machines(client, tech, mine, theirs, shared):
    listed = {d["id"]: d for d in client.get("/api/v1/devices", headers=_headers(tech)).json()}
    assert set(listed) == {str(mine.id), str(shared.id)}
    assert all(d["health"]["faults"] == {"bme280": "missing"} for d in listed.values())
    assert str(theirs.id) not in listed


def test_an_unknown_role_gets_no_health(client, stranger, mine, shared):
    assert client.get("/api/v1/devices", headers=_headers(stranger)).json() == []
    assert client.get(f"/api/v1/devices/{shared.id}", headers=_headers(stranger)).status_code == 404


def test_health_needs_a_sign_in(client, mine):
    assert client.get(f"/api/v1/devices/{mine.id}").status_code == 401
    assert client.get("/api/v1/devices").status_code == 401
    assert client.get("/api/v1/health/summary").status_code == 401


def test_the_summary_counts_link_states_within_what_the_caller_may_read(client, admin, viewer, tech, mine, theirs, shared):
    everything = {"online": 1, "late": 1, "offline": 1}
    assert client.get("/api/v1/health/summary", headers=_headers(admin)).json()["link_states"] == everything
    assert client.get("/api/v1/health/summary", headers=_headers(viewer)).json()["link_states"] == everything
    # the technician's own machine and the unowned one and not the other technician's offline machine
    assert client.get("/api/v1/health/summary", headers=_headers(tech)).json()["link_states"] == {"online": 1, "late": 1, "offline": 0}


def test_the_summary_keeps_its_existing_fields(client, admin, mine):
    body = client.get("/api/v1/health/summary", headers=_headers(admin)).json()
    for field in ("total_devices", "online", "offline", "active_alerts", "open_tickets", "health_score"):
        assert field in body


def test_the_summary_counts_zero_for_an_unknown_role(client, stranger, mine):
    assert client.get("/api/v1/health/summary", headers=_headers(stranger)).json()["link_states"] == {"online": 0, "late": 0, "offline": 0}


def test_monitoring_alerts_follow_the_machine_rule(client, db, admin, tech, mine, theirs):
    a_mine = Alert(device_id=mine.id, message="quiet", severity="warning", resolved=False, category="monitoring")
    a_theirs = Alert(device_id=theirs.id, message="quiet", severity="warning", resolved=False, category="monitoring")
    db.add_all([a_mine, a_theirs])
    db.flush()
    admin_ids = {a["id"] for a in client.get("/api/v1/alerts?category=monitoring", headers=_headers(admin)).json()}
    tech_ids = {a["id"] for a in client.get("/api/v1/alerts?category=monitoring", headers=_headers(tech)).json()}
    assert admin_ids == {str(a_mine.id), str(a_theirs.id)}
    assert tech_ids == {str(a_mine.id)}
    # the per-machine route returns the new fields too and is refused for the other technician's machine
    own = client.get("/api/v1/alerts", params={"device_id": str(mine.id)}, headers=_headers(tech)).json()
    assert own[0]["category"] == "monitoring" and "sensor_key" in own[0]
    assert client.get("/api/v1/alerts", params={"device_id": str(theirs.id)}, headers=_headers(tech)).status_code == 404


def test_a_device_key_cannot_read_health_and_health_does_not_change_who_may_ingest(client, mine):
    # ingest still takes the device key alone. The device routes still need a user
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(mine.id), "temperature": 20.0, "boot": 5, "up": 10},
        headers={"X-API-Key": mine.api_key},
    )
    assert res.status_code == 201
    assert client.get(f"/api/v1/devices/{mine.id}", headers={"X-API-Key": mine.api_key}).status_code == 401
