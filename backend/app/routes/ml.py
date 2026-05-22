from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.telemetry import Telemetry
from app.schemas.telemetry import TelemetryIngest, TelemetryResponse
# score_reading is the ML service function that runs the Isolation Forest model on a single reading
from app.services.ml_service import score_reading

router = APIRouter()


# No response_model here because the return shape is simple and defined inline as a plain dict
@router.post("/score")
def score(payload: TelemetryIngest):
    # Build an explicit dict so the ML service receives only the sensor fields it expects
    reading = {
        "temperature": payload.temperature,
        "humidity":    payload.humidity,
        "vibration_x": payload.vibration_x,
        "vibration_y": payload.vibration_y,
        "vibration_z": payload.vibration_z,
        "light_level": payload.light_level,
    }
    # Tuple unpacking — score_reading returns two values and we capture each in its own variable
    anomaly_score, is_anomaly = score_reading(reading)
    # FastAPI automatically serialises a plain dict to a JSON response body
    return {"anomaly_score": anomaly_score, "is_anomaly": is_anomaly}


# `limit` is an optional query parameter with a default of 100 to prevent unbounded result sets
@router.get("/anomalies/{device_id}", response_model=list[TelemetryResponse])
def anomaly_history(device_id: UUID, limit: int = 100, db: Session = Depends(get_db)):
    return (
        db.query(Telemetry)
        # Passing `Telemetry.is_anomaly` as a filter condition works because SQLAlchemy treats a boolean
        # column directly as a WHERE is_anomaly = TRUE clause
        .filter(Telemetry.device_id == device_id, Telemetry.is_anomaly)
        .order_by(Telemetry.recorded_at.desc())
        # .limit() is translated to a SQL LIMIT clause, keeping query performance predictable
        .limit(limit)
        .all()
    )
