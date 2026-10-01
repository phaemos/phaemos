# PHAEMOS

**Reveal before failure.** An open industrial IoT platform for predictive maintenance.

PHAEMOS connects embedded sensor nodes (ESP32, STM32 Black Pill, Arduino Nano and Raspberry Pi Pico 2W) to
a FastAPI backend that scores every incoming reading with an Isolation Forest. Alerts go out by email,
SMS, Slack, Discord and Teams when a machine drifts from its learned normal behaviour.

The name is pronounced FAY-mos and means "an ordered system that reveals", from Ancient Greek roots tied
to revelation and structure. It reveals hidden machine behaviour through telemetry, alerting and anomaly
detection before a failure becomes visible.

---

## What it does

- **Ingests telemetry** from four hardware node types over HTTPS, with an optional Rust gateway that
  spools readings through network outages
- **Detects anomalies** with a trained Isolation Forest model, so no labelled fault data is needed
- **Alerts** through configurable rules, webhooks, email and SMS when the anomaly score crosses a threshold
- **Presents** a real-time dashboard, device management, a ticket tracker and an admin panel
- **Exports** audit logs with HMAC-SHA256 tamper evidence

---

## Documentation

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
| [Security](security.md) | The 27 security controls |
| [Decision log](decisions.md) | Why each main choice was made |
| [Releases](releases.md) | Tagging a release and the changelog check |
| [Week by week](week_by_week.md) | The phase-based development timeline |
| [Verification](VERIFICATION.md) | What is verified and merged against what is still pending |
| [Monitoring](instatus.md) | The Instatus status page setup |

---

## Quick links

- [GitHub repository](https://github.com/phaemos/phaemos)
- [Live platform](https://phaemos.com)
- [Status page](https://status.phaemos.com)
- [Contact](https://phaemos.com/contact)
- [Contributing](https://github.com/phaemos/phaemos/blob/main/CONTRIBUTING.md)

---

## Licence

PHAEMOS is released under the [GNU Affero General Public License v3](https://github.com/phaemos/phaemos/blob/main/LICENSE).
Anyone running a modified version as a network service must publish its source under the same terms.
