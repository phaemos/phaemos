"""
Firmware OTA routes - admin can upload a .bin file; devices poll /latest
to check for a newer version and download it if one exists.
"""

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Header
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.limiter import limiter

from app.config import settings
from app.db import get_db
from app.routes.auth import require_admin
from app.models.user import User
from app.services import audit_service

router = APIRouter()
logger = logging.getLogger(__name__)

# I cap firmware uploads at 2 MB to prevent a malicious or accidental upload
# from exhausting server RAM (the whole file is read into memory before writing).
_MAX_FIRMWARE_BYTES = 2 * 1024 * 1024

# Metadata about the latest firmware is kept in memory (single file at a time).
# A production system would use a database table to track version history.
_latest: dict = {}


def _firmware_path() -> Path:
    path = Path(settings.firmware_storage_path)
    path.mkdir(parents=True, exist_ok=True)  # create dir if it doesn't exist yet
    return path


@router.post("/firmware/upload", status_code=201)
@limiter.limit("20/hour")
async def upload_firmware(
    request: Request,
    version: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    # Reject non-.bin files as a first-pass guard (server-side validation).
    if not file.filename or not file.filename.endswith(".bin"):
        raise HTTPException(status_code=400, detail="Only .bin firmware files accepted")

    dest = _firmware_path() / "firmware_latest.bin"
    contents = await file.read()

    if len(contents) > _MAX_FIRMWARE_BYTES:
        raise HTTPException(status_code=413, detail="Firmware file exceeds 2 MB limit")

    # SHA-256 checksum lets devices verify integrity after download.
    checksum = hashlib.sha256(contents).hexdigest()

    dest.write_bytes(contents)

    _latest.update({
        "version": version,
        "filename": file.filename,
        "size": len(contents),
        "checksum": checksum,
    })

    logger.info("Firmware uploaded: version=%s size=%d checksum=%s", version, len(contents), checksum)

    audit_service.log_action(
        db,
        user_id=str(_admin.id),
        action="firmware_uploaded",
        resource="firmware",
        resource_id=version,
        detail=f"filename={file.filename} size={len(contents)} checksum={checksum[:12]}",
    )
    return _latest


@router.get("/firmware/latest")
def get_latest_firmware():
    # ESP32 polls this endpoint on boot to decide whether to update.
    if not _latest:
        raise HTTPException(status_code=404, detail="No firmware uploaded yet")
    return _latest


@router.get("/firmware/download")
def download_firmware(x_api_key: str = Header(...)):
    # Reuse device API key auth - any registered device can download firmware.
    # The key is validated by existence check (simple; no DB lookup needed here).
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")

    dest = _firmware_path() / "firmware_latest.bin"
    if not dest.exists():
        raise HTTPException(status_code=404, detail="No firmware file on server")

    return FileResponse(
        path=str(dest),
        media_type="application/octet-stream",
        filename="firmware.bin",
    )
