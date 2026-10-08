"""
train.py - Train the anomaly models on exported telemetry data.

Usage:
    python train.py --csv telemetry_export.csv

The CSV is an export of the telemetry table: a node_type column plus any of the sensor columns.
Training goes through the same app.services.ml_service.train as the API's retrain endpoint, so a
model built here scores live readings exactly as one built by the backend does: a general model
plus one per node type with enough readings.

Outputs model.pkl to the ml/ directory.
"""

import argparse
import sys
from pathlib import Path

import joblib
import pandas as pd

# the backend package sits one level up, so the shared training code can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.ml_service import SENSOR_COLS, train

MODEL_OUTPUT = Path(__file__).parent / "model.pkl"


def main(csv_path: str) -> None:
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} rows from {csv_path}")
    cols = [c for c in ["node_type", *SENSOR_COLS] if c in df.columns]
    # missing readings stay None so each node type is modelled only on the sensors it reports
    rows = df[cols].astype(object).where(df[cols].notna(), None).to_dict("records")
    bundle, summary = train(rows)
    joblib.dump(bundle, MODEL_OUTPUT)
    print(summary)
    print(f"Model saved to {MODEL_OUTPUT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Path to telemetry CSV export")
    args = parser.parse_args()
    main(args.csv)
