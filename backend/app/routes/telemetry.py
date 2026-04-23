from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import uuid

from app.db import get_db
from app.models.device import Device
from app.models.telemetry import Telemetry
from app.schemas.telemetry import TelemetryIngest, TelemetryResponse
from app.services.ml_service import score_reading
from app.services.alert_service import evaluate_rules

router = APIRouter()


def get_device_by_api_key(api_key: str, db: Session) -> Device:
    device = db.query(Device).filter(Device.api_key == api_key).first()
    if not device:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return device


@router.post("", response_model=TelemetryResponse, status_code=201)
def ingest_telemetry(
    payload: TelemetryIngest,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
):
    device = get_device_by_api_key(x_api_key, db)

    reading = {
        "temperature": payload.temperature,
        "humidity":    payload.humidity,
        "vibration_x": payload.vibration_x,
        "vibration_y": payload.vibration_y,
        "vibration_z": payload.vibration_z,
        "light_level": payload.light_level,
    }

    anomaly_score, is_anomaly = score_reading(reading)

    row = Telemetry(
        device_id     = device.id,
        anomaly_score = anomaly_score,
        is_anomaly    = is_anomaly,
        **reading,
    )
    db.add(row)

    device.last_seen = datetime.now(timezone.utc)
    device.status    = "online"

    db.commit()
    db.refresh(row)

    evaluate_rules(device, reading, db)

    return row


@router.get("/{device_id}", response_model=list[TelemetryResponse])
def get_telemetry(
    device_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return (
        db.query(Telemetry)
        .filter(Telemetry.device_id == device_id)
        .order_by(Telemetry.recorded_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/{device_id}/latest", response_model=TelemetryResponse)
def get_latest(device_id: uuid.UUID, db: Session = Depends(get_db)):
    row = (
        db.query(Telemetry)
        .filter(Telemetry.device_id == device_id)
        .order_by(Telemetry.recorded_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No telemetry found for device")
    return row
