"""
preprocess.py - Feature engineering for PHAEMOS ML pipeline.

Adds rolling statistics (mean + std over last 10 readings) and
a time-of-day feature to the raw telemetry dataframe.
"""

import pandas as pd


SENSOR_COLS = [
    "temperature",
    "humidity",
    "vibration_x",
    "vibration_y",
    "vibration_z",
    "light_level",
]

WINDOW = 10


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Ensure chronological order
    if "recorded_at" in df.columns:
        df["recorded_at"] = pd.to_datetime(df["recorded_at"])
        df = df.sort_values("recorded_at").reset_index(drop=True)

        # Time of day encoded as fraction of 24h (0.0 = midnight, 1.0 = midnight)
        df["time_of_day"] = (
            df["recorded_at"].dt.hour * 3600
            + df["recorded_at"].dt.minute * 60
            + df["recorded_at"].dt.second
        ) / 86400.0

    # Rolling mean and std for each sensor column
    for col in SENSOR_COLS:
        if col in df.columns:
            df[f"roll_mean_{col}"] = df[col].rolling(WINDOW, min_periods=1).mean()
            df[f"roll_std_{col}"]  = df[col].rolling(WINDOW, min_periods=1).std().fillna(0)

    return df
