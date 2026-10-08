from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import matplotlib
import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_fscore_support

# force the non-interactive Agg backend so matplotlib does not try to open a
# display window when running on headless CI or server environments.
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# the backend package sits one level up, so the evaluation scores readings exactly as the API does
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services import ml_service

ANOMALY_SCORE_THRESHOLD = ml_service.ANOMALY_THRESHOLD


def load_model(model_path: str) -> Any:
    """Load a saved bundle of models (or a single model from an earlier version)."""
    return joblib.load(model_path)


def score_rows(model: Any, rows: list[dict]) -> np.ndarray:
    """Score each reading on the 0-1 scale the dashboard shows."""
    ml_service._model = model
    try:
        return np.array([ml_service.score_reading(r)[0] for r in rows])
    finally:
        ml_service._model = None


def evaluate_precision_recall(scores: np.ndarray, y_true: Any) -> dict:
    y_pred = (scores >= ANOMALY_SCORE_THRESHOLD).astype(int)
    y_true = np.asarray(y_true)
    precision, recall, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    return {
        "precision": float(precision),
        "recall":    float(recall),
        "f1":        float(f1),
        # support is None for a binary average, so the labelled anomalies are counted directly
        "support":   int(y_true.sum()),
    }


def plot_anomaly_distribution(scores: list, output_path: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(scores, bins=40, color="#3B82F6", alpha=0.75, edgecolor="white", linewidth=0.3)
    ax.axvline(
        ANOMALY_SCORE_THRESHOLD,
        color="#EF4444",
        linewidth=1.5,
        linestyle="--",
        label=f"Threshold ({ANOMALY_SCORE_THRESHOLD})",
    )
    ax.set_xlabel("Anomaly Score")
    ax.set_ylabel("Count")
    ax.set_title("Anomaly Score Distribution")
    ax.legend()
    fig.tight_layout()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120)
    plt.close(fig)


def generate_report(model_path: str, data_path: str, output_path: str) -> None:
    Path(output_path).mkdir(parents=True, exist_ok=True)

    model = load_model(model_path)

    df = pd.read_csv(data_path)
    if "is_anomaly" not in df.columns:
        raise ValueError("data_path CSV must include an 'is_anomaly' column for ground-truth labels")

    cols = [c for c in ["node_type", *ml_service.SENSOR_COLS] if c in df.columns]
    rows = df[cols].astype(object).where(df[cols].notna(), None).to_dict("records")
    y_true = df["is_anomaly"].astype(int).to_numpy()

    scores = score_rows(model, rows)
    metrics = evaluate_precision_recall(scores, y_true)
    scores = scores.tolist()

    n_anomalies = int(y_true.sum())
    plot_path = str(Path(output_path) / "anomaly_distribution.png")
    plot_anomaly_distribution(scores, plot_path)

    report = {
        "precision":    metrics["precision"],
        "recall":       metrics["recall"],
        "f1":           metrics["f1"],
        "n_samples":    len(df),
        "n_anomalies":  n_anomalies,
        "threshold":    ANOMALY_SCORE_THRESHOLD,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    report_path = Path(output_path) / "report.json"
    report_path.write_text(json.dumps(report, indent=2))
