"""
ML Service - I load the trained Isolation Forest model and score
incoming telemetry readings. I return (anomaly_score, is_anomaly).

Before the model is trained (Phase 3), I score all readings as 0.0
so the system operates normally without ML active.
"""

import os
# use joblib because it is the standard way to serialise scikit-learn models to and from disk
import joblib
# import numpy because scikit-learn models expect a numpy array, not a plain Python list
import numpy as np

# use os.path.dirname(__file__) so the path resolves correctly regardless of where the app is launched from
MODEL_PATH      = os.path.join(os.path.dirname(__file__), "../../ml/model.pkl")
# classify a reading as anomalous when its normalised score reaches this threshold
ANOMALY_THRESHOLD = 0.7
# keep FEATURE_COLS here so both scoring and retraining use the identical feature vector.
FEATURE_COLS = ["temperature", "humidity", "vibration_x", "vibration_y", "vibration_z", "light_level"]

# start with None and populate on first use - lazy loading avoids disk I/O at import time
_model = None


def _load_model():
    # `global _model` is needed to assign to the module-level variable; without it Python would create a local one
    global _model
    # only load from disk if not already loaded AND the file exists (model may not be trained yet)
    if _model is None and os.path.exists(MODEL_PATH):
        _model = joblib.load(MODEL_PATH)


def score_reading(reading: dict) -> tuple[float, bool]:
    """
    Score a single telemetry reading.
    Returns (anomaly_score: float 0-1, is_anomaly: bool).
    """
    # Lazy-load the model on the first call rather than at import time, keeping startup fast
    _load_model()

    if _model is None:
        # return a safe pass-through when the model has not been trained yet
        return 0.0, False

    # build a 2-D array with shape (1, n_features) - scikit-learn always expects samples x features.
    # use FEATURE_COLS so this vector stays identical to what retraining produces.
    features = np.array([[reading.get(col) or 0.0 for col in FEATURE_COLS]])

    # call score_samples which returns a raw score - more negative means more anomalous
    raw_score  = _model.score_samples(features)[0]

    # normalise to 0-1: adding 0.5 shifts the range, subtracting from 1 flips it so higher = more anomalous
    # Clip to ensure the result stays within [0.0, 1.0] for extreme raw scores
    normalised = float(np.clip(1 - (raw_score + 0.5), 0.0, 1.0))
    is_anomaly = normalised >= ANOMALY_THRESHOLD

    # round to 4 decimal places to keep API responses clean without losing meaningful precision
    return round(normalised, 4), is_anomaly


def reload_model() -> None:
    """Force a fresh load of model.pkl from disk. Called after retraining."""
    global _model
    # reset to None first so _load_model re-reads the file even if one was already loaded.
    _model = None
    _load_model()
