from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import matplotlib
import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_fscore_support

# I force the non-interactive Agg backend so matplotlib does not try to open a
# display window when running on headless CI or server environments.
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ANOMALY_SCORE_THRESHOLD = float(os.getenv("ANOMALY_SCORE_THRESHOLD", "0.7"))

FEATURE_COLS = [
    "temperature",
    "humidity",
    "vibration_x",
    "vibration_y",
    "vibration_z",
    "light_level",
]


def load_model(model_path: str) -> Any:
    model = joblib.load(model_path)
    if not hasattr(model, "predict"):
        raise ValueError(f"Loaded object from {model_path} has no predict() method")
    return model


def evaluate_precision_recall(model: Any, X_test: Any, y_true: Any) -> dict:
    raw = model.predict(X_test)
    # I remap IsolationForest's convention (-1=anomaly, 1=normal) to binary (1=anomaly, 0=normal)
    # so standard sklearn metrics work without caller-side remapping.
    y_pred = np.where(raw == -1, 1, 0)
    y_true_arr = np.asarray(y_true)
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true_arr, y_pred, average="binary", zero_division=0
    )
    return {
        "precision": float(precision),
        "recall":    float(recall),
        "f1":        float(f1),
        "support":   int(support),
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

    feature_cols = [c for c in FEATURE_COLS if c in df.columns]
    X = df[feature_cols].fillna(0).to_numpy()
    y_true = df["is_anomaly"].astype(int).to_numpy()

    metrics = evaluate_precision_recall(model, X, y_true)

    # I use decision_function scores for the distribution plot when available because
    # they are continuous, making the histogram more informative than binary predict().
    if hasattr(model, "decision_function"):
        scores = model.decision_function(X).tolist()
    else:
        scores = model.predict(X).tolist()

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
