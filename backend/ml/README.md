# ML Pipeline

Isolation Forest anomaly detection pipeline.

| File | Purpose |
|---|---|
| train.py | Train model on a telemetry CSV export - outputs model.pkl |
| preprocess.py | Feature engineering - rolling stats, time-of-day feature |
| evaluate.py | Evaluate trained model - precision/recall, distribution plot, JSON report |

Run training: `python train.py --csv telemetry_export.csv`
The trained model.pkl is loaded by `app/services/ml_service.py` on startup.
