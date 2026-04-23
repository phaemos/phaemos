"""
ML Service - loads the trained Isolation Forest model and scores
incoming telemetry readings. Returns (anomaly_score, is_anomaly).

Before the model is trained (Phase 3), all readings are scored 0.0
so the system operates normally without ML active.
"""

import os
import joblib
import numpy as np

MODEL_PATH      = os.path.join(os.path.dirname(__file__), "../../ml/model.pkl")
ANOMALY_THRESHOLD = 0.7

_model = None


def _load_model():
    global _model
    if _model is None and os.path.exists(MODEL_PATH):
        _model = joblib.load(MODEL_PATH)


def score_reading(reading: dict) -> tuple[float, bool]:
    """
    Score a single telemetry reading.
    Returns (anomaly_score: float 0-1, is_anomaly: bool).
    """
    _load_model()

    if _model is None:
        # Model not yet trained - pass everything through as normal
        return 0.0, False

    features = np.array([[
        reading.get("temperature")   or 0.0,
        reading.get("humidity")      or 0.0,
        reading.get("vibration_x")   or 0.0,
        reading.get("vibration_y")   or 0.0,
        reading.get("vibration_z")   or 0.0,
        reading.get("light_level")   or 0.0,
    ]])

    # Isolation Forest: predict returns 1 (normal) or -1 (anomaly)
    # score_samples returns raw anomaly score (more negative = more anomalous)
    raw_score  = _model.score_samples(features)[0]

    # Normalise to 0-1 range (approximate)
    # score_samples typically ranges from about -0.5 to 0.5
    normalised = float(np.clip(1 - (raw_score + 0.5), 0.0, 1.0))
    is_anomaly = normalised >= ANOMALY_THRESHOLD

    return round(normalised, 4), is_anomaly
