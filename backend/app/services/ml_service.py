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
from sklearn.ensemble import IsolationForest

# use os.path.dirname(__file__) so the path resolves correctly regardless of where the app is launched from
MODEL_PATH      = os.path.join(os.path.dirname(__file__), "../../ml/model.pkl")
# classify a reading as anomalous when its normalised score reaches this threshold
ANOMALY_THRESHOLD = 0.7
# the general model's features, used for readings that do not say which node sent them.
FEATURE_COLS = ["temperature", "humidity", "vibration_x", "vibration_y", "vibration_z", "light_level"]
# every numeric sensor column a node can send. Each node type is modelled on the ones it really reports,
# since a field a node never has would otherwise read as a constant 0 and skew its normal envelope.
SENSOR_COLS = [
    "temperature", "humidity", "pressure", "vibration_x", "vibration_y", "vibration_z",
    "gyro_x", "gyro_y", "gyro_z", "bus_voltage", "current_ma", "power_mw", "ir_temperature",
    "distance_mm", "gas_level", "shaft_angle", "shaft_rpm", "sound_level", "light_level",
    "contact_temp", "moisture_level", "fft_peak_hz", "vib_magnitude",
]
# a node type needs this many readings before it gets a model of its own
MIN_ROWS_PER_NODE = 50
# a column belongs to a node type when at least this share of its readings carry it
FIELD_PRESENCE = 0.9

# start with None and populate on first use - lazy loading avoids disk I/O at import time
_model = None


def _load_model():
    # `global _model` is needed to assign to the module-level variable; without it Python would create a local one
    global _model
    # only load from disk if not already loaded AND the file exists (model may not be trained yet)
    if _model is None and os.path.exists(MODEL_PATH):
        _model = joblib.load(MODEL_PATH)


def _matrix(rows: list[dict], cols: list[str]) -> np.ndarray:
    return np.array([[float(r.get(c) or 0.0) for c in cols] for r in rows])


def calibrate(model, raw_scores: np.ndarray) -> None:
    """Store how healthy readings scored in training, so later scores can be read against them."""
    # decision values are the model's own scale: below 0 lies outside what it learned as normal
    decisions = raw_scores - model.offset_
    model.phaemos_typical_decision = float(max(np.median(decisions), 1e-6))


def normalise(model, raw_scores: np.ndarray) -> np.ndarray:
    """
    Map raw Isolation Forest scores onto 0-1, higher meaning more anomalous.

    A typical training reading maps to 0 and the model's own decision boundary maps to
    ANOMALY_THRESHOLD, so "anomalous" means exactly what the trained model learned rather than
    a fixed shift. score_samples is roughly -0.4 to -0.7 for normal data, which a fixed
    `1 - (raw + 0.5)` turned into 0.9 or more for every reading.
    """
    typical = getattr(model, "phaemos_typical_decision", None)
    decisions = raw_scores - model.offset_
    if typical is None:
        # a model saved before calibration: the boundary still maps to the threshold
        typical = 0.1
    return np.clip(ANOMALY_THRESHOLD * (typical - decisions) / typical, 0.0, 1.0)


def _fit(rows: list[dict], cols: list[str]) -> tuple[IsolationForest, np.ndarray]:
    model = IsolationForest(n_estimators=200, contamination=0.05, random_state=42)
    X = _matrix(rows, cols)
    model.fit(X)
    raw = model.score_samples(X)
    calibrate(model, raw)
    model.phaemos_features = cols
    return model, normalise(model, raw)


def train(rows: list[dict]) -> tuple[dict, str]:
    """
    Train the general model plus one per node type with enough readings.
    Returns the bundle to save and a one-line summary for the audit log.
    """
    bundle: dict = {}
    bundle["default"], scores = _fit(rows, FEATURE_COLS)
    parts = [f"general on {len(rows)} rows ({100 * (scores >= ANOMALY_THRESHOLD).mean():.1f}% flagged)"]
    by_node: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("node_type"):
            by_node.setdefault(r["node_type"], []).append(r)
    for node, node_rows in sorted(by_node.items()):
        if len(node_rows) < MIN_ROWS_PER_NODE:
            continue
        cols = [c for c in SENSOR_COLS if sum(r.get(c) is not None for r in node_rows) >= FIELD_PRESENCE * len(node_rows)]
        if not cols:
            continue
        bundle[node], scores = _fit(node_rows, cols)
        parts.append(f"{node} on {len(node_rows)} rows and {len(cols)} sensors ({100 * (scores >= ANOMALY_THRESHOLD).mean():.1f}% flagged)")
    return bundle, "Retrained " + "; ".join(parts) + "."


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

    if isinstance(_model, dict):
        model = _model.get(reading.get("node_type") or "") or _model["default"]
    else:
        # a single model saved by an earlier version
        model = _model
    cols = getattr(model, "phaemos_features", FEATURE_COLS)
    normalised = float(normalise(model, model.score_samples(_matrix([reading], cols)))[0])
    is_anomaly = normalised >= ANOMALY_THRESHOLD

    # round to 4 decimal places to keep API responses clean without losing meaningful precision
    return round(normalised, 4), is_anomaly


def reload_model() -> None:
    """Force a fresh load of model.pkl from disk. Called after retraining."""
    global _model
    # reset to None first so _load_model re-reads the file even if one was already loaded.
    _model = None
    _load_model()
