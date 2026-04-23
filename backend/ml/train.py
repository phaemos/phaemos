"""
train.py - Train an Isolation Forest on exported telemetry data.

Usage:
    python train.py --csv telemetry_export.csv

The script expects a CSV with these columns (from the telemetry table):
    temperature, humidity, vibration_x, vibration_y, vibration_z, light_level

Outputs model.pkl to the ml/ directory.
"""

import argparse
import joblib
import pandas as pd
from pathlib import Path
from sklearn.ensemble import IsolationForest
from preprocess import build_features

MODEL_OUTPUT = Path(__file__).parent / "model.pkl"

FEATURE_COLS = [
    "temperature",
    "humidity",
    "vibration_x",
    "vibration_y",
    "vibration_z",
    "light_level",
]


def train(csv_path: str) -> None:
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} rows from {csv_path}")

    df = build_features(df)

    feature_cols = [c for c in df.columns if c in FEATURE_COLS or c.startswith("roll_")]
    X = df[feature_cols].dropna()

    print(f"Training on {len(X)} rows with features: {feature_cols}")

    model = IsolationForest(
        n_estimators=200,
        contamination=0.05,   # assume ~5% of training data may be anomalous
        random_state=42,
    )
    model.fit(X)

    joblib.dump(model, MODEL_OUTPUT)
    print(f"Model saved to {MODEL_OUTPUT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Path to telemetry CSV export")
    args = parser.parse_args()
    train(args.csv)
