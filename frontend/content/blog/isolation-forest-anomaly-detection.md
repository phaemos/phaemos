---
title: "How PHAEMOS scores a reading"
date: "2026-05-15"
slug: "isolation-forest-anomaly-detection"
excerpt: "How the backend turns a reading into a score from 0 to 1, when a score becomes an alert and how an admin retrains the model."
---

Rewritten in November 2026 to match the product as it is now.

Every reading that reaches the API gets an anomaly score from 0 to 1. A higher score means the reading is further from what the model learned as normal. This post describes how that score is made and what it leads to. The model has only been trained on simulated readings so far. We have no accuracy figures for real machines.

## Why an Isolation Forest

We had no labelled fault data, so a supervised classifier could not be trained. An Isolation Forest is unsupervised. It learns from normal readings and needs no labelled faults. We use the scikit-learn implementation with 100 trees. We do not tell it how many readings to expect to be unusual. The cut-off is measured on readings held back from training.

## From raw score to 0 to 1

The raw Isolation Forest score is not on a scale a person can read. We map it in two steps. After training we record how a typical training reading scored. A typical reading maps to 0 and the model's own decision boundary maps to 0.7. The result is clipped to the range 0 to 1 and rounded to four decimal places.

A score of 0.7 or more counts as an anomaly. A fixed shift of the raw score used to give 0.9 or more for every reading, which is why we calibrate against the training data instead.

## What the model reads

The general model reads six values: temperature, humidity, vibration on three axes and light level. We used to fill a missing value with zero, which made a failed sensor look like a reading. We no longer do. A reading with a missing input is not scored by the node's own model. It falls back to the general model when that has every input it needs and is left unscored when neither does. A sensor that has failed raises its own monitoring alert, so the failure is reported on its own and is not hidden inside a score.

A machine or a node type also gets a model of its own once it has enough clean history, which is at least 500 readings to fit and a day held back for testing. That model uses the sensor columns which at least 90 per cent of that node's readings carry. There are 23 columns it can choose from. A node type with no model of its own is scored by the general model. Before any model is trained every score is 0.

## From score to alert

One anomalous reading does not raise an alert. We look at a window of readings instead. It is the longer of two minutes and 24 posting intervals and at least four in every five scored readings in it must be at or over the boundary.

When that happens the backend raises an anomaly alert and opens a ticket named after the machine. The alert is critical when the median score of the window reaches 0.85 and a warning below that. The ticket has high priority. A critical alert gives it critical priority. If the machine already has an open ticket from an earlier anomaly the new alert is added to it.

The alert clears by itself after a calm spell of at least half an hour whose median score is under 0.5. While a maintenance window is active for the machine no anomaly alert is raised.

## Retraining

The models retrain every night at 03:30 UTC. An admin can also start a retrain with a POST to `/api/v1/ml/retrain`. The API answers 202 and fits the models in the background on the last 14 days of every machine. A new model replaces the one in service only if it passes the checks on false alerts and on the newest readings. It loads without a restart. A second manual retrain has to wait an hour. That wait is kept in memory, so it resets when the API restarts. The result is written to the audit log.

If the process stops during a retrain the old model file stays in place and scoring carries on with it.

The same training code is available offline in `backend/ml/train.py`, which reads a CSV export of the readings table.

## What it cannot do yet

The model has not seen a real machine, so we cannot say how often it flags a healthy one or misses a fault. We plan to train it on real readings once the nodes are wired to machines. Until then the thresholds of 0.7 and 0.85 come from the calibration above and not from field experience.
