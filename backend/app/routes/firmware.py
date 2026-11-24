"""
Firmware OTA routes - admin can upload a .bin file; devices poll /latest
to check for a newer version and download it if one exists.
"""

import hashlib
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile, File, Header
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.limiter import limiter

from app.config import settings
from app.db import get_db
from app.routes.auth import fresh_proof, require_admin
from app.errors import ApiError, Code
from app.schemas.misc_responses import FirmwareMeta
from app.services.device_keys import device_for_key
from app.services import ingest_limit
from app.models.user import User
from app.services import audit_service

router = APIRouter()
logger = logging.getLogger(__name__)

# cap firmware uploads at 2 MB to prevent a malicious or accidental upload
# from exhausting server RAM (the whole file is read into memory before writing).
_MAX_FIRMWARE_BYTES = 2 * 1024 * 1024
_VERSION = re.compile(r"[0-9]{1,5}(\.[0-9]{1,5}){0,3}")

# the latest version's metadata is stored beside the file so it survives a restart
_META_FILE = "firmware_latest.json"


def _firmware_path() -> Path:
    path = Path(settings.firmware_storage_path)
    path.mkdir(parents=True, exist_ok=True)  # create dir if it doesn't exist yet
    return path


def _read_meta() -> dict:
    try:
        return json.loads((_firmware_path() / _META_FILE).read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _write_meta(meta: dict) -> None:
    # written to a temporary name and renamed, so a crash never leaves half a file behind
    target = _firmware_path() / _META_FILE
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta))
    tmp.replace(target)


@router.post("/firmware/upload", status_code=201, response_model=FirmwareMeta)
@limiter.limit("20/hour")
async def upload_firmware(
    request: Request,
    version: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
    _proof: None = Depends(fresh_proof("upload firmware")),
):
    # the version is compared as dotted numbers by the node, so it is dotted numbers: up to four parts of digits
    if not _VERSION.fullmatch(version):
        raise ApiError(422, Code.VALIDATION_FAILED, "version must be dotted numbers such as 2.5.0 (up to four parts)")
    # reject non-.bin files as a first-pass guard (server-side validation).
    if not file.filename or not file.filename.endswith(".bin"):
        raise ApiError(422, Code.FIRMWARE_FILE_INVALID, "Only .bin firmware files accepted")

    dest = _firmware_path() / "firmware_latest.bin"
    contents = await file.read()

    if len(contents) > _MAX_FIRMWARE_BYTES:
        raise ApiError(413, Code.FIRMWARE_TOO_LARGE, "Firmware file exceeds 2 MB limit")

    # SHA-256 checksum lets devices verify integrity after download.
    checksum = hashlib.sha256(contents).hexdigest()

    dest.write_bytes(contents)

    meta = {
        "version": version,
        "filename": file.filename,
        "size": len(contents),
        "checksum": checksum,
    }
    _write_meta(meta)

    logger.info("Firmware uploaded: version=%s size=%d checksum=%s", version, len(contents), checksum)

    audit_service.log_action(
        db,
        user_id=str(_admin.id),
        action="firmware_uploaded",
        resource="firmware",
        resource_id=version,
        detail=f"filename={file.filename} size={len(contents)} checksum={checksum[:12]}",
    )
    return meta


# a hub checks for firmware about once a minute at the most and downloads an image rarely. The allowance is per device and not per
# address, so a site of hubs behind one address after a power cut do not share it
LATEST_PER_MINUTE = 6
DOWNLOAD_PER_MINUTE = 3


@router.get("/firmware/latest", response_model=FirmwareMeta)
def get_latest_firmware(
    request: Request,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
):
    # ESP32 polls this endpoint on boot to decide whether to update. Only a registered
    # machine may ask, with the same key check as telemetry ingest.
    device = device_for_key(db, x_api_key)
    ingest_limit.check_named(device.id, "firmware check", LATEST_PER_MINUTE)
    meta = _read_meta()
    if not meta:
        raise ApiError(404, Code.FIRMWARE_NOT_FOUND, "No firmware uploaded yet")
    return meta


@router.get("/firmware/download")
def download_firmware(
    request: Request,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
):
    # the key must belong to a registered machine: the firmware image is not public.
    device = device_for_key(db, x_api_key)
    ingest_limit.check_named(device.id, "firmware download", DOWNLOAD_PER_MINUTE)

    dest = _firmware_path() / "firmware_latest.bin"
    if not dest.exists():
        raise ApiError(404, Code.FIRMWARE_NOT_FOUND, "No firmware file on server")

    return FileResponse(
        path=str(dest),
        media_type="application/octet-stream",
        filename="firmware.bin",
    )
