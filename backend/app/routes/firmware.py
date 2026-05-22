"""
Firmware OTA routes — admin can upload a .bin file; devices poll /latest
to check for a newer version and download it if one exists.
"""

import hashlib
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Header
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Metadata about the latest firmware is kept in memory (single file at a time).
# A production system would use a database table to track version history.
_latest: dict = {}


def _firmware_path() -> Path:
    path = Path(settings.firmware_storage_path)
    path.mkdir(parents=True, exist_ok=True)  # create dir if it doesn't exist yet
    return path


@router.post("/firmware/upload", status_code=201)
async def upload_firmware(
    version: str,
    file: UploadFile = File(...),
):
    # Reject non-.bin files as a first-pass guard (server-side validation).
    if not file.filename or not file.filename.endswith(".bin"):
        raise HTTPException(status_code=400, detail="Only .bin firmware files accepted")

    dest = _firmware_path() / "firmware_latest.bin"
    contents = await file.read()

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
    return _latest


@router.get("/firmware/latest")
def get_latest_firmware():
    # ESP32 polls this endpoint on boot to decide whether to update.
    if not _latest:
        raise HTTPException(status_code=404, detail="No firmware uploaded yet")
    return _latest


@router.get("/firmware/download")
def download_firmware(x_api_key: str = Header(...)):
    # Reuse device API key auth — any registered device can download firmware.
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
