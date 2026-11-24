# ML Pipeline

Scripts around the anomaly model. The model itself is trained, measured and saved by the API: `POST /api/v1/ml/retrain` and the nightly retrain run `app/services/ml_service.train_bundle` and write a signed model file. See [the architecture page](../../docs/architecture.md#the-anomaly-model) for what it detects and what it does not.

| File | Purpose |
|---|---|
| train.py | An older script that trained on a telemetry CSV export. It calls a function the service no longer has and the file it would write carries no signature, so the API would refuse to read it. Use the API's retrain |
| preprocess.py | Feature engineering - rolling stats, time-of-day feature |
| evaluate.py | Scores labelled readings with a saved model - precision/recall, distribution plot, JSON report. It reads only a model file this server signed |

The evaluation on simulated machines is `make ml-eval` (`app/scripts/evaluate_model.py`).
