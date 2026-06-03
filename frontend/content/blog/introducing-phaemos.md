---
title: "Introducing PHAEMOS - Predict Failure Before It Happens"
date: "2026-05-01"
slug: "introducing-phaemos"
excerpt: "PHAEMOS is an open-source smart maintenance platform that uses vibration FFT analysis and machine learning to catch equipment failure before it disrupts operations."
---

# Introducing PHAEMOS - Predict Failure Before It Happens

Most maintenance systems are reactive. A machine breaks. Someone notices. Someone files a ticket. Someone eventually fixes it. By then the production line has been down for hours and the repair bill has doubled because the secondary failure cascaded.

PHAEMOS takes the opposite approach: measure everything continuously, model what normal looks like, and raise an alert the moment readings drift out of range - before the failure, not after.

## What makes it different

**Real vibration analysis** - Most IoT platforms treat sensor data as raw numbers. PHAEMOS runs a 128-point FFT on accelerometer readings using CMSIS-DSP on the STM32 node, extracting the peak frequency component. Bearing faults, shaft imbalance, and misalignment each produce characteristic frequency signatures. Logging the raw peak frequency means the ML model and alert rules have something meaningful to work with, not just an average g-force.

**Isolation Forest anomaly detection** - A rule saying "alert if temperature > 40 C" is brittle. Set it too tight and you get noise; too loose and you miss slow-developing faults. PHAEMOS trains an Isolation Forest on historical telemetry so the model learns what normal looks like for each combination of device, load, and ambient conditions. The anomaly score updates continuously. When it drops below -0.1, something unusual is happening.

**Ticket workflow** - An alert is only useful if someone acts on it. PHAEMOS connects alerts directly to a ticket system with priority, assignment and status tracking. Alerts can create tickets in one click. Nothing gets lost in a Slack thread.

**Four-node hardware** - The platform is built for real hardware: an ESP32 running Wi-Fi telemetry, an STM32 BlackPill for FFT-heavy vibration processing, a Raspberry Pi Pico W for power monitoring and temperature, and an Arduino Nano for legacy sensor bridging. All four nodes ship firmware from the same repository and report to the same backend.

## Versus the alternatives

**ThingsBoard** is mature and feature-rich but heavyweight - it requires Java, a separate time-series DB, and assumes you are running at enterprise scale. Getting a simple alert pipeline running takes days. PHAEMOS runs with `docker compose up`.

**Grafana + InfluxDB** gives you excellent visualisation but no workflow layer. You can see the anomaly; you cannot act on it without building a separate ticketing integration. PHAEMOS has the ticket system built in.

**Node-RED** is great for rapid prototyping but not a long-term platform. It has no auth system, no multi-tenancy, and no ML layer.

PHAEMOS is designed to be the right size: more structured than Node-RED, lighter than ThingsBoard, with the workflow layer Grafana lacks.

## Try it

```bash
git clone https://github.com/zaccesss/phaemos
cd phaemos
make dev
```

The backend starts on port 8000, the frontend on port 3000. Default admin credentials are in `.env.example`. Full setup guide in `docs/deployment.md`.

Questions or feedback: [hello@phaemos.com](mailto:hello@phaemos.com)
