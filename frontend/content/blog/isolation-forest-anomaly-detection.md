---
title: "How Isolation Forest Powers PHAEMOS Anomaly Detection"
date: "2026-05-15"
slug: "isolation-forest-anomaly-detection"
excerpt: "Isolation Forest spots equipment anomalies without needing labelled failure data - here is how it works in PHAEMOS and when to retrain the model."
---

# How Isolation Forest Powers PHAEMOS Anomaly Detection

Setting thresholds for equipment health is harder than it looks. A temperature of 45 C might be perfectly normal for a motor running at full load in summer, but alarming for the same motor idling in a cool room. A single fixed threshold produces either constant noise or missed faults depending on operating conditions.

PHAEMOS uses an Isolation Forest instead.

## What Isolation Forest does

Isolation Forest is an anomaly detection algorithm based on a simple insight: anomalies are rare and different, so they are easier to isolate than normal points.

The algorithm builds an ensemble of random decision trees. For each tree, it picks a random feature and a random split value, recursively partitioning the data until each point is isolated. Points that get isolated in fewer splits are anomalies - they are different enough from the bulk of the data that they stand out immediately.

The output is an anomaly score between -1 and 1. In PHAEMOS:

- Score >= 0: normal operating range
- Score between -0.1 and 0: slightly unusual - monitor but do not alert
- Score < -0.1: anomaly - alert fires, technician is notified

The threshold of -0.1 is configurable via alert rules. Teams running older or dirtier equipment might raise it to -0.15 to reduce noise; teams monitoring precision machinery might lower it to -0.05.

## What features go into the model

The model scores each telemetry reading using these features:

- `temperature` - ambient and surface temperature from the NTC thermistors
- `vibration_x`, `vibration_y`, `vibration_z` - three-axis accelerometer readings
- `fft_peak_hz` - the dominant frequency component extracted by the STM32 FFT
- `current` - motor current draw from the ACS712 current sensor
- `voltage` - supply voltage from the INA219
- `pressure` - atmospheric pressure from the BMP280

The combination matters. A vibration spike is normal during a tool change. The same spike accompanied by a current surge and elevated bearing temperature is a warning sign. The model learns these correlations from historical data so it is not fooled by single-metric events.

## When to train the model

The model ships as a pre-trained `model.pkl` in the repository, fitted on synthetic data with known-good operating profiles. This is good enough to detect gross anomalies out of the box.

For real deployments, retrain the model on your actual hardware after a burn-in period of at least two weeks of normal operation. Use the admin panel or the API:

```bash
curl -X POST http://localhost:8000/api/v1/ml/retrain \
  -H "Authorization: Bearer <admin-token>"
```

The endpoint fits a new Isolation Forest on the last 10,000 telemetry rows (roughly 14 hours at 5-second intervals), saves `model.pkl`, and hot-reloads it without a restart. There is a 1-hour cooldown between retrains to prevent thrashing.

Retrain whenever:
- You add a new device type with different operating characteristics
- Operating conditions change significantly (new load profile, different ambient environment)
- You are seeing systematic false positives that are too expensive to filter with alert rules

## Limitations

Isolation Forest assumes that anomalies are rare. If more than 10% of your training data contains fault conditions, the model learns faults as normal. Always retrain on data from a known-good period.

The model does not know about time. It scores each reading independently without sequence context. A slow drift that stays within normal range at every point but trends in a dangerous direction will not be caught. PHAEMOS alert rules (threshold-based) are the right tool for drift detection; Isolation Forest handles sudden deviations.

Questions: [dev@phaemos.com](mailto:dev@phaemos.com)
