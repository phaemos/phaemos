---
hide:
  - navigation
---

# PHAEMOS

<div class="ph-status" markdown>

**Where the project stands.** Nothing has run on real machines yet. The firmware has not been tested on physical boards
and the anomaly model has not been trained on real data. The model is being reworked and its claims are under review.
What exists today is the backend, the dashboard, the simulator and the automated checks. The
[verification tracker](VERIFICATION.md) lists what is verified and merged against what is still pending.

</div>

**Reveal before failure** is the aim of the project. PHAEMOS is an open industrial IoT platform for predictive
maintenance. It is designed to connect embedded sensor nodes (ESP32, STM32 Black Pill, Arduino Nano and Raspberry Pi
Pico 2W) to a FastAPI backend that scores every incoming reading against a model of each machine (an Isolation Forest, a
per-sensor baseline and a sequential change detector). It is designed to send alerts by email, SMS, Slack, Discord and
Teams when a machine drifts from its learned normal behaviour.

The name is pronounced FAY-mos and means "an ordered system that reveals", from Ancient Greek roots tied
to revelation and structure. The aim is to reveal hidden machine behaviour through telemetry, alerting and anomaly
detection before a failure becomes visible.

## Where to start

These pages are for the people who run machines and for the people who build and maintain the system. Pick the line
that fits what you are doing.

<dl class="ph-start" markdown>
<dt>I want to run it</dt>
<dd markdown>Start with [Development](development.md) to run the platform on one computer with or without Docker.
Then read [Deployment](deployment.md) and the [deployment checklist](deployment-checklist.md) before you put it on a server.</dd>
<dt>I am building a node</dt>
<dd markdown>Read the [sensor reference](sensor_reference.md) for every sensor, its interface and its expected range.
The [tech stack](tech-stack.md) lists the four boards and the [architecture](architecture.md) shows how a reading travels.</dd>
<dt>I am using the API</dt>
<dd markdown>The [API reference](api-reference.md) lists every endpoint. Read the [API conventions](api-conventions.md) for
the shared rules and [API stability](api-stability.md) for what may change.</dd>
<dt>I care about security</dt>
<dd markdown>[Security](security.md) lists the security controls. The [decision log](decisions.md) says why each main
choice was made.</dd>
</dl>

## What it is designed to do

- **Ingests telemetry** from four hardware node types over HTTPS, with an optional Rust gateway that
  spools readings through network outages
- **Detects anomalies** with a model per machine (an Isolation Forest, a per-sensor baseline and a sequential change detector), so no labelled fault data is needed. The model is being reworked and has been measured on simulated machines only
- **Alerts** through configurable rules, webhooks, email and SMS when the anomaly score crosses a threshold
- **Presents** a real-time dashboard, device management, a ticket tracker and an admin panel
- **Exports** audit logs with HMAC-SHA256 tamper evidence

---

## All pages

| Section | What is in it |
| --- | --- |
| [Architecture](architecture.md) | System diagram, data flow, auth, background tasks and webhooks |
| [Development](development.md) | Running locally with or without Docker, the smoke test, the simulator and the tests |
| [Deployment](deployment.md) | The server, Vercel and DNS setup |
| [Deployment checklist](deployment-checklist.md) | Checks to run before going live |
| [Scalability](scalability.md) | Six stages from a single server to a distributed setup |
| [API reference](api-reference.md) | Every REST endpoint with its auth and request and response shapes |
| [Sensor reference](sensor_reference.md) | Every sensor with its interface, specs and expected ranges |
| [Database schema](schema.md) | PostgreSQL table definitions |
| [Tech stack](tech-stack.md) | Every language and tool by layer, plus the four boards |
| [Repositories](repositories.md) | The monorepo, the published component repositories and how publishing works |
| [Security](security.md) | The security controls |
| [Decision log](decisions.md) | Why each main choice was made |
| [Releases](releases.md) | Tagging a release and the changelog check |
| [Week by week](week_by_week.md) | The phase-based development timeline |
| [Verification](VERIFICATION.md) | What is verified and merged against what is still pending |
| [Monitoring](instatus.md) | The Instatus status page setup |

---

## Quick links

<div class="ph-links" markdown>

- [GitHub repository](https://github.com/phaemos/phaemos)
- [Live platform](https://phaemos.com)
- [Status page](https://status.phaemos.com)
- [Contact](https://phaemos.com/contact)
- [Contributing](https://github.com/phaemos/phaemos/blob/main/CONTRIBUTING.md)

</div>

---

## Licence

Software is released under the [GNU Affero General Public License v3](https://github.com/phaemos/phaemos/blob/main/LICENSE) or later. The hardware designs are released under the [CERN Open Hardware Licence v2, Strongly Reciprocal](https://github.com/phaemos/phaemos/blob/main/hardware/LICENSE). The [licensing notice](https://github.com/phaemos/phaemos/blob/main/NOTICE.md) explains which licence covers what.
