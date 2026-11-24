"""
Firmware routes: both device-facing calls need the key of a real machine, are rate limited.
The latest version's details survive a restart because they are stored beside the file.
"""

import json

import pytest

from app.config import settings
from app.routes import firmware
from tests._shape import plain


@pytest.fixture(autouse=True)
def firmware_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "firmware_storage_path", str(tmp_path))
    return tmp_path


def _upload(client, admin_headers, version="1.2.3", body=b"firmware-bytes"):
    return client.post(
        f"/api/v1/firmware/upload?version={version}",
        files={"file": ("fw.bin", body, "application/octet-stream")},
        # a firmware upload needs the admin's fresh proof, as two extra form fields
        data={"password": "Admin1234!"},
        headers=admin_headers,
    )


@pytest.mark.parametrize("path", ["/api/v1/firmware/latest", "/api/v1/firmware/download"])
class TestDeviceKey:
    def test_a_missing_key_is_refused(self, client, device, path):
        assert client.get(path).status_code == 422

    def test_an_empty_key_is_refused(self, client, device, path):
        assert client.get(path, headers={"X-API-Key": ""}).status_code == 401

    def test_an_unknown_key_is_refused(self, client, device, path):
        res = client.get(path, headers={"X-API-Key": "not-a-real-key"})
        assert (res.status_code, plain(res)) == (401, {"detail": "Invalid API key"})

    def test_a_user_token_is_not_a_device_key(self, client, device, auth_headers, path):
        token = auth_headers["Authorization"].split(" ", 1)[1]
        assert client.get(path, headers={"X-API-Key": token}).status_code == 401


def test_latest_is_404_before_any_upload(client, device):
    assert client.get("/api/v1/firmware/latest", headers={"X-API-Key": device.api_key}).status_code == 404


def test_latest_returns_what_was_uploaded(client, device, auth_headers):
    sent = _upload(client, auth_headers)
    assert sent.status_code == 201
    res = client.get("/api/v1/firmware/latest", headers={"X-API-Key": device.api_key})
    assert res.status_code == 200
    body = res.json()
    assert (body["version"], body["filename"], body["size"]) == ("1.2.3", "fw.bin", len(b"firmware-bytes"))
    assert body == sent.json()


def test_the_details_are_stored_beside_the_file(client, auth_headers, firmware_dir):
    sent = _upload(client, auth_headers)
    stored = json.loads((firmware_dir / "firmware_latest.json").read_text())
    assert stored == sent.json()


def test_the_details_survive_a_restart(client, device, firmware_dir):
    # a restart empties the process and leaves the volume, so only the files on disk remain
    (firmware_dir / "firmware_latest.bin").write_bytes(b"old-image")
    meta = {"version": "0.9.0", "filename": "old.bin", "size": 9, "checksum": "abc"}
    (firmware_dir / "firmware_latest.json").write_text(json.dumps(meta))
    assert firmware._read_meta() == meta
    res = client.get("/api/v1/firmware/latest", headers={"X-API-Key": device.api_key})
    assert (res.status_code, res.json()) == (200, meta)


def test_a_damaged_details_file_answers_404_not_500(client, device, firmware_dir):
    (firmware_dir / "firmware_latest.json").write_text("{not json")
    assert client.get("/api/v1/firmware/latest", headers={"X-API-Key": device.api_key}).status_code == 404


def test_download_is_404_without_a_file(client, device):
    assert client.get("/api/v1/firmware/download", headers={"X-API-Key": device.api_key}).status_code == 404


def test_download_returns_the_image_for_a_valid_key(client, device, auth_headers):
    _upload(client, auth_headers, body=b"image-bytes")
    res = client.get("/api/v1/firmware/download", headers={"X-API-Key": device.api_key})
    assert res.status_code == 200
    assert res.content == b"image-bytes"


def test_a_second_upload_replaces_the_details(client, device, auth_headers):
    _upload(client, auth_headers, version="1.0.0")
    _upload(client, auth_headers, version="1.1.0")
    res = client.get("/api/v1/firmware/latest", headers={"X-API-Key": device.api_key})
    assert res.json()["version"] == "1.1.0"


def test_both_calls_are_rate_limited(client, device):
    headers = {"X-API-Key": device.api_key}
    assert 429 in [client.get("/api/v1/firmware/download", headers=headers).status_code for _ in range(12)]
    client.app.state.limiter.reset()
    assert 429 in [client.get("/api/v1/firmware/latest", headers=headers).status_code for _ in range(32)]
