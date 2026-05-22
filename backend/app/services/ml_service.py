"""
ML Service - I load the trained Isolation Forest model and score
incoming telemetry readings. I return (anomaly_score, is_anomaly).

Before the model is trained (Phase 3), I score all readings as 0.0
so the system operates normally without ML active.
"""

import os
# I use joblib because it is the standard way to serialise scikit-learn models to and from disk
import joblib
# I import numpy because scikit-learn models expect a numpy array, not a plain Python list
import numpy as np

# I use os.path.dirname(__file__) so the path resolves correctly regardless of where the app is launched from
MODEL_PATH      = os.path.join(os.path.dirname(__file__), "../../ml/model.pkl")
# I classify a reading as anomalous when its normalised score reaches this threshold
ANOMALY_THRESHOLD = 0.7

# I start with None and populate on first use - lazy loading avoids disk I/O at import time
_model = None


def _load_model():
    # I need `global _model` to assign to the module-level variable; without it Python would create a local one
    global _model
    # I only load from disk if not already loaded AND the file exists (model may not be trained yet)
    if _model is None and os.path.exists(MODEL_PATH):
        _model = joblib.load(MODEL_PATH)


def score_reading(reading: dict) -> tuple[float, bool]:
    """
    Score a single telemetry reading.
    Returns (anomaly_score: float 0-1, is_anomaly: bool).
    """
    # I lazy-load the model on the first call rather than at import time, keeping startup fast
    _load_model()

    if _model is None:
        # I return a safe pass-through when the model has not been trained yet
        return 0.0, False

    # I build a 2-D array with shape (1, 6) - scikit-learn always expects samples x features
    features = np.array([[
        # I use `.get() or 0.0` to handle both missing keys and None values
        reading.get("temperature")   or 0.0,
        reading.get("humidity")      or 0.0,
        reading.get("vibration_x")   or 0.0,
        reading.get("vibration_y")   or 0.0,
        reading.get("vibration_z")   or 0.0,
        reading.get("light_level")   or 0.0,
    ]])

    # I call score_samples which returns a raw score - more negative means more anomalous
    raw_score  = _model.score_samples(features)[0]

    # I normalise to 0-1: adding 0.5 shifts the range, subtracting from 1 flips it so higher = more anomalous
    # I clip to ensure the result stays within [0.0, 1.0] for extreme raw scores
    normalised = float(np.clip(1 - (raw_score + 0.5), 0.0, 1.0))
    is_anomaly = normalised >= ANOMALY_THRESHOLD

    # I round to 4 decimal places to keep API responses clean without losing meaningful precision
    return round(normalised, 4), is_anomaly
