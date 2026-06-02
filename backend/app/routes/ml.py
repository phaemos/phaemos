from datetime import datetime, timezone, timedelta
from uuid import UUID

import joblib
import numpy as np
import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session

from app.db import get_db, SessionLocal
from app.models.telemetry import Telemetry
from app.models.user import User
from app.schemas.telemetry import TelemetryIngest, TelemetryResponse
from app.routes.auth import get_current_user, require_admin
from app.services import audit_service
from app.services.ml_service import reload_model, MODEL_PATH, ANOMALY_THRESHOLD, FEATURE_COLS

router = APIRouter()

# 1-hour cooldown enforced in memory so rapid re-submissions do not thrash training.
_last_retrain: datetime | None = None
_COOLDOWN = timedelta(hours=1)

# Number of most-recent telemetry rows to train on.
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

        # I build a DataFrame from the 6 features the live scorer uses so training
        # and inference operate on an identical feature vector.
        data = {col: [getattr(r, col) for r in rows] for col in FEATURE_COLS}
        df = pd.DataFrame(data).fillna(0.0)

        X = df.values
        n_samples = len(X)

        model = IsolationForest(
            n_estimators=200,
            contamination=0.05,
            random_state=42,
        )
        model.fit(X)

        joblib.dump(model, MODEL_PATH)
        reload_model()

        # I compute n_anomalies on training data as a rough quality indicator rather
        # than precision/recall, which requires labels we do not have.
        raw_scores = model.score_samples(X)
        normalised = np.clip(1 - (raw_scores + 0.5), 0.0, 1.0)
        n_anomalies = int((normalised >= ANOMALY_THRESHOLD).sum())

        audit_service.log_action(
            db, user_id, "retrain", "ml_model", "model",
            f"Retrained on {n_samples} rows. "
            f"Training anomalies detected: {n_anomalies} "
            f"({100 * n_anomalies / n_samples:.1f}%).",
        )
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


# No response_model here because the return shape is simple and defined inline as a plain dict
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
