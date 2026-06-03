# Phaemos

**Industrial IoT predictive maintenance platform.**

Phaemos connects embedded sensor nodes (ESP32, STM32, Arduino Nano, Raspberry Pi Pico W) to a FastAPI backend that runs Isolation Forest anomaly detection on the incoming telemetry. Alerts fire via email, SMS, Slack, Discord and Teams when readings deviate from the learned normal baseline.

---

## What it does

- **Ingests telemetry** from up to four hardware node types over HTTP
- **Detects anomalies** using a trained Isolation Forest model - no labeled fault data required
- **Alerts** via configurable webhooks, email and SMS when the anomaly score crosses a threshold
- **Presents** a real-time dashboard, device management, ticket tracker and admin panel
- **Exports** audit logs with HMAC-SHA256 tamper evidence

---

## Documentation

| Section | What is in it |
|---|---|
| [Architecture](architecture.md) | System diagram, data flow, background tasks |
| [Deployment](deployment.md) | VPS, Vercel and DNS setup |
| [Deployment Checklist](deployment-checklist.md) | Pre-launch checklist |
| [API Reference](api-reference.md) | All REST endpoints with auth and shapes |
| [Sensor Reference](sensor_reference.md) | All sensors, specs, calibration ranges |
| [Database Schema](schema.md) | PostgreSQL table definitions |
| [Security](security.md) | 18-measure security controls |
| [Decision Log](decisions.md) | Why we chose what we chose |
| [Monitoring](uptime-kuma.md) | Uptime monitoring setup |

---

## Quick links

- [GitHub repository](https://github.com/zaccesss/phaemos)
- [Live platform](https://phaemos.com)
- [Status page](https://status.phaemos.com)
- [Contact](https://phaemos.com/contact)
- [Contributing](https://github.com/zaccesss/phaemos/blob/main/CONTRIBUTING.md)

---

## Licence

Phaemos is released under the [GNU Affero General Public License v3](https://github.com/zaccesss/phaemos/blob/main/LICENSE).
Anyone running a modified version as a network service must publish the source code under the same terms.
