---
title: "What PHAEMOS is and what works today"
date: "2026-05-01"
slug: "introducing-phaemos"
excerpt: "What PHAEMOS does from sensor node to ticket, which parts run today and which parts are still to be built."
---

Rewritten in November 2026 to match the product as it is now.

PHAEMOS is an open industrial IoT platform for predictive maintenance. Sensor nodes send readings from a machine. A backend scores each reading against a model of normal behaviour. A dashboard shows the readings live and raises an alert when a machine drifts.

## What runs today

The software runs end to end: ingest, storage, scoring, alerts, tickets and the dashboard. It runs on simulated readings, because the sensor nodes are not yet wired to machines.

A node posts a reading to the API with its machine's key in a header. The backend scores the reading and stores it in PostgreSQL. It checks the reading against the alert rules and pushes it to the dashboard over a WebSocket. The simulator in the repository produces readings for any of the four node types and can inject faults such as a failing bearing.

Around that core we built what a maintenance team needs:

- alert rules and maintenance windows
- tickets
- webhooks to Slack, Discord and Teams
- email and text message alerts
- an audit log of changes
- roles, with optional two-step sign-in

An optional gateway written in Rust sits beside the machines. It reads a node's serial output and writes each reading to disk. If the network drops it sends the readings on in order once the link returns.

## Why a model and not fixed limits

We start with no labelled fault data, so a supervised classifier was not an option. We chose an Isolation Forest from scikit-learn. It learns what normal looks like and flags readings that deviate. The next post covers how scoring works in detail.

A reading that scores as an anomaly does not raise an alert on its own. An alert is raised when at least four in five scored readings in a window are anomalous. It opens a ticket for the machine.

## What does not work yet

- **The nodes are not on machines.** They are designed and not yet built. The plan is to prototype on development boards and breakouts. Carrier boards are still being designed.
- **The model has only seen simulated readings.** We have no figures for how it behaves on a real machine.
- **The STM32 vibration firmware has not run on a board.** It compiles and its FFT passes a host test.

## What comes next

Our hardware plan has four phases: breadboard prototyping, circuit simulation and schematics, PCB layout and enclosures. We are in the first. Once real nodes are producing readings we train the model on them, which the decision log says needs one to two weeks of real data. The milestones on GitHub hold the order.

## Try it

You need Docker and Node.js.

```bash
cp .env.example .env
make dev
```

The dashboard is then on port 3000 and the API on port 8000. To feed it without hardware, install the simulator:

```bash
pip install -e client/python
phaemos-sim --node esp32 --count 5 --dry-run
```

The software is licensed under the GNU Affero General Public License v3.0 or later. The hardware designs are under the CERN Open Hardware Licence v2, Strongly Reciprocal. For questions use GitHub Discussions.
