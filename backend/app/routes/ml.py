from datetime import datetime, timezone, timedelta
from uuid import UUID

import joblib
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db, SessionLocal
from app.models.telemetry import Telemetry
from app.models.user import User
from app.schemas.telemetry import TelemetryIngest, TelemetryResponse
from app.routes.auth import get_current_user, require_admin
from app.services import audit_service
from app.services.ml_service import reload_model, train, MODEL_PATH, SENSOR_COLS

router = APIRouter()

# 1-hour cooldown enforced in memory so rapid re-submissions do not thrash training.
_last_retrain: datetime | None = None
_COOLDOWN = timedelta(hours=1)

# number of most-recent telemetry rows to train on.
_RETRAIN_ROWS = 10_000


def _do_retrain(user_id: str) -> None:
    """Background task - runs after the 202 response is sent."""
    db = SessionLocal()
    try:
        rows = (
            db.query(Telemetry)
            .order_by(Telemetry.recorded_at.desc())
            .limit(_RETRAIN_ROWS)
            .all()
        )

        if not rows:
            audit_service.log_action(
                db, user_id, "retrain", "ml_model", "model",
                "Retrain skipped - no telemetry rows in database",
            )
            return

        # each node type is modelled on its own sensors, plus a general model for the rest
        readings = [
            {"node_type": r.node_type, **{col: getattr(r, col) for col in SENSOR_COLS}}
            for r in rows
        ]
        bundle, summary = train(readings)
        joblib.dump(bundle, MODEL_PATH)
        reload_model()

        audit_service.log_action(db, user_id, "retrain", "ml_model", "model", summary)
    except Exception as exc:  # noqa: BLE001
        audit_service.log_action(
            db, user_id, "retrain_error", "ml_model", "model",
            f"Retrain failed: {exc}",
        )
    finally:
        db.close()


@router.post("/retrain", status_code=202)
def retrain(
    background_tasks: BackgroundTasks,
    admin=Depends(require_admin),
):
    global _last_retrain
    now = datetime.now(timezone.utc)

    if _last_retrain and (now - _last_retrain) < _COOLDOWN:
        remaining = int((_last_retrain + _COOLDOWN - now).total_seconds() // 60)
        raise HTTPException(
            status_code=429,
            detail=f"Retrain cooldown active. Try again in {remaining} minutes.",
        )

    _last_retrain = now
    background_tasks.add_task(_do_retrain, str(admin.id))
    return {"detail": "Retrain started. Model will be updated in the background."}


# no response_model here because the return shape is simple and defined inline as a plain dict
@router.post("/score")
def score(
    payload: TelemetryIngest,
    current_user: User = Depends(get_current_user),
):
    from app.services.ml_service import score_reading
    reading = payload.model_dump(exclude={"device_id"})
    anomaly_score, is_anomaly = score_reading(reading)
    return {"anomaly_score": anomaly_score, "is_anomaly": is_anomaly}


# `limit` is an optional query parameter with a default of 100 to prevent unbounded result sets
@router.get("/anomalies/{device_id}", response_model=list[TelemetryResponse])
def anomaly_history(
    device_id: UUID,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(Telemetry)
        .filter(Telemetry.device_id == device_id, Telemetry.is_anomaly)
        .order_by(Telemetry.recorded_at.desc())
        .limit(limit)
        .all()
    )
