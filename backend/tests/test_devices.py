import secrets
import pytest
from passlib.context import CryptContext

from app.models.device import Device
from app.models.user import User

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _token_for(user, role):
    from app.routes.auth import create_access_token
    token = create_access_token({"sub": str(user.id), "role": role})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def technician(db):
    u = User(
        name="Tech",
        email="tech@test.com",
        password_hash=_pwd_ctx.hash("Tech1234!"),
        role="technician",
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def viewer(db):
    u = User(
        name="Viewer",
        email="viewer@test.com",
        password_hash=_pwd_ctx.hash("View1234!"),
        role="viewer",
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def owned_device(db, technician):
    d = Device(
        name="Owned ESP32",
        location="Lab",
        type="esp32",
        api_key=secrets.token_urlsafe(32),
        owner_id=technician.id,
    )
    db.add(d)
    db.flush()
    return d


@pytest.fixture
def unowned_device(db):
    d = Device(
        name="Shared ESP32",
        location="Corridor",
        type="esp32",
        api_key=secrets.token_urlsafe(32),
    )
    db.add(d)
    db.flush()
    return d


@pytest.fixture
def other_technician_device(db):
    other = User(
        name="Other Tech",
        email="other@test.com",
        password_hash=_pwd_ctx.hash("Other1234!"),
        role="technician",
    )
    db.add(other)
    db.flush()
    d = Device(
        name="Other Tech ESP32",
        location="Office",
        type="esp32",
        api_key=secrets.token_urlsafe(32),
        owner_id=other.id,
    )
    db.add(d)
    db.flush()
    return d


def test_admin_sees_all_devices(
    client, admin_user, owned_device, unowned_device, other_technician_device
):
    resp = client.get("/api/v1/devices", headers=_token_for(admin_user, "admin"))
    assert resp.status_code == 200
    ids = {d["id"] for d in resp.json()}
    assert str(owned_device.id) in ids
    assert str(unowned_device.id) in ids
    assert str(other_technician_device.id) in ids


def test_viewer_sees_all_devices(
    client, viewer, owned_device, unowned_device, other_technician_device
):
    resp = client.get("/api/v1/devices", headers=_token_for(viewer, "viewer"))
    assert resp.status_code == 200
    ids = {d["id"] for d in resp.json()}
    assert str(owned_device.id) in ids
    assert str(unowned_device.id) in ids
    assert str(other_technician_device.id) in ids


def test_technician_sees_own_and_unowned(
    client, technician, owned_device, unowned_device, other_technician_device
):
    resp = client.get(
        "/api/v1/devices", headers=_token_for(technician, "technician")
    )
    assert resp.status_code == 200
    ids = {d["id"] for d in resp.json()}
    # own device and unowned (shared) device are visible
    assert str(owned_device.id) in ids
    assert str(unowned_device.id) in ids
    # another technician's device is not visible
    assert str(other_technician_device.id) not in ids


def test_list_devices_requires_auth(client, unowned_device):
    resp = client.get("/api/v1/devices")
    # FastAPI's HTTPBearer returns 403 when the Authorization header is absent
    assert resp.status_code == 403


def test_owner_id_returned_in_response(client, admin_user, owned_device, technician):
    resp = client.get("/api/v1/devices", headers=_token_for(admin_user, "admin"))
    assert resp.status_code == 200
    device_data = next(
        d for d in resp.json() if d["id"] == str(owned_device.id)
    )
    assert device_data["owner_id"] == str(technician.id)


def test_register_device_requires_admin(client, technician, admin_user):
    payload = {"name": "New Device", "type": "esp32", "location": "Lab"}
    # unauthenticated
    assert client.post("/api/v1/devices", json=payload).status_code == 403
    # technician
    assert client.post(
        "/api/v1/devices", json=payload, headers=_token_for(technician, "technician")
    ).status_code == 403
    # admin
    assert client.post(
        "/api/v1/devices", json=payload, headers=_token_for(admin_user, "admin")
    ).status_code == 201


def test_get_device_requires_auth(client, unowned_device):
    resp = client.get(f"/api/v1/devices/{unowned_device.id}")
    assert resp.status_code == 403


def test_technician_cannot_get_others_device(
    client, technician, other_technician_device
):
    resp = client.get(
        f"/api/v1/devices/{other_technician_device.id}",
        headers=_token_for(technician, "technician"),
    )
    assert resp.status_code == 403


def test_technician_can_patch_own_device(client, technician, owned_device):
    resp = client.patch(
        f"/api/v1/devices/{owned_device.id}",
        json={"location": "Updated Lab"},
        headers=_token_for(technician, "technician"),
    )
    assert resp.status_code == 200
    assert resp.json()["location"] == "Updated Lab"


def test_technician_cannot_patch_others_device(
    client, technician, other_technician_device
):
    resp = client.patch(
        f"/api/v1/devices/{other_technician_device.id}",
        json={"location": "Hacked"},
        headers=_token_for(technician, "technician"),
    )
    assert resp.status_code == 403
