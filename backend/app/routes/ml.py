from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.telemetry import Telemetry
from app.schemas.telemetry import TelemetryIngest, TelemetryResponse
from app.services.ml_service import score_reading

router = APIRouter()


@router.post("/score")
def score(payload: TelemetryIngest):
    reading = {
        "temperature": payload.temperature,
        "humidity":    payload.humidity,
        "vibration_x": payload.vibration_x,
        "vibration_y": payload.vibration_y,
        "vibration_z": payload.vibration_z,
        "light_level": payload.light_level,
    }
    anomaly_score, is_anomaly = score_reading(reading)
    return {"anomaly_score": anomaly_score, "is_anomaly": is_anomaly}


@router.get("/anomalies/{device_id}", response_model=list[TelemetryResponse])
def anomaly_history(device_id: UUID, limit: int = 100, db: Session = Depends(get_db)):
    return (
        db.query(Telemetry)
        .filter(Telemetry.device_id == device_id, Telemetry.is_anomaly)
        .order_by(Telemetry.recorded_at.desc())
        .limit(limit)
        .all()
    )
