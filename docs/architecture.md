# Architecture Overview

## System Diagram

```text
[ Physical Layer - 4 nodes ]
  ESP32 DevKit Primary Node
    BME280 (temp/humidity/pressure)
    MPU6050 (acceleration + gyroscope)
    INA219 (bus voltage, current, power)
    MLX90614 (contactless IR temperature)
    VL53L0X (time-of-flight distance)
    MQ-2 (gas and smoke)
    AS5600 (magnetic shaft angle + RPM)
    MAX4466 (acoustic / sound level)
    DS18B20 (precision contact temperature)
    LDR (ambient light)
    FC-28 (moisture / water ingress)
    OLED, buzzer, WS2812B RGB LED, relay

  STM32 Black Pill F411CEU6 (Vibration Node)
    MPU6050 at 100 Hz sampling
    CMSIS-DSP arm_rfft_fast_f32 FFT (N=128, O(N log N))
    UART to ESP32 at 115200 baud

  Arduino Nano (Secondary Node)
    BME280, LDR, FC-28
    Serial CSV to ESP32 at 9600 baud

  Raspberry Pi Pico W (Ambient Node)
    BME280, LDR, OLED
    Direct Wi-Fi HTTP POST to API

        |
        | I2C / Analog / OneWire / UART / Serial
        v
[ Firmware Layer ]
  Nano (serial 9600) --------> ESP32 (parses + merges payload)
  STM32 (UART 115200) -------> ESP32 (FFT peak Hz forwarded to API)
  Pico W (Wi-Fi) -----------> API directly
  ESP32 (Wi-Fi POST) -------> API every 5 seconds

        |
        | HTTP POST (JSON) to /api/v1/telemetry
        | Header: X-API-Key: <device api key>
        v
[ Backend Layer - FastAPI (Python 3.11) ]
  Routes:
    /telemetry         - ingest + alert rule evaluation
    /devices           - device registry + API key management + tags
    /alerts            - alert history + resolve
    /alert-rules       - threshold rules per device/metric
    /tickets           - maintenance ticket CRUD (PHM-0001 format)
    /auth              - register, login, OAuth, 2FA, GDPR, JWT refresh
    /ml                - anomaly score endpoint + retrain
    /webhooks          - Slack/Discord/Teams webhook management
    /maintenance       - maintenance windows CRUD
    /health            - fleet health summary
    /audit-logs        - paginated audit log + CSV export
    /contact           - contact form with Turnstile verification
    /status            - public health check (no auth)

        |
        |---> PostgreSQL 15 (persistent storage, 9 migrations applied)
        |---> Redis 7 (WebSocket pub/sub, rate limiting, session store)
        v
[ ML Layer ]
  Isolation Forest (scikit-learn)
  - trained offline on historical telemetry CSV
  - loaded as model.pkl at startup
  - scores every ingest: 0 (normal) to 1 (anomaly)
  - threshold 0.7+ triggers alert + flags telemetry row
  - retrain endpoint POST /ml/retrain (admin, 1-hour cooldown)
  Phase 3: LSTM for time-series sequence prediction

        |
        v
[ Frontend Layer - Next.js 15 (App Router, TypeScript) ]
  /               - live dashboard (charts, status cards, health widget, alert banners)
  /devices        - device list + batch firmware update
  /devices/[id]   - device detail: sensor grid, per-sensor time-range charts, tags editor
  /alerts         - alert feed, resolve actions
  /tickets        - ticket table (PHM-XXXX numbers), create/update
  /admin          - user management, alert rules, OTA firmware, audit logs,
                    webhooks panel, maintenance windows panel
  /compare        - side-by-side comparison of up to 3 devices
  /about          - project overview and feature summary
  /blog           - blog post index + post detail
  /changelog      - rendered CHANGELOG.md
  /docs           - docs hub with links to MkDocs site
  /status         - live API/DB/Redis health + link to status.phaemos.com
  /security       - responsible disclosure and controls summary
  /faq            - frequently asked questions (17 questions, 6 sections)
  /support        - help channels and common troubleshooting
  /contact        - contact form with Cloudflare Turnstile
  /privacy        - privacy policy
  /terms          - terms of service
  /login          - JWT login page with OAuth buttons (Google, GitHub)
  /profile        - user profile editor + 2FA enrolment + GDPR export/delete
```

## Data Flow (Happy Path)

1. ESP32 reads all 11 sensors every 5 seconds
2. Merges UART data from STM32 (FFT peak Hz) and serial data from Nano (BME280/LDR/FC-28)
3. Builds JSON payload with device_id + all readings
4. POSTs to `POST /api/v1/telemetry` with `X-API-Key` header
5. FastAPI validates API key - looks up device
6. ML service scores the reading via Isolation Forest
7. Alert service checks reading against all rules for that device
8. If rule triggered - inserts alert row - auto-creates ticket if critical
9. Telemetry row saved to PostgreSQL with anomaly_score + is_anomaly
10. If alert severity is critical - webhook service fires Slack/Discord/Teams payload
11. Frontend polls `GET /api/v1/telemetry/{device_id}/latest` every 5s, or receives push via WebSocket

## Authentication Architecture

```text
[ User Login ]
  POST /auth/login
    - Validates email + password (or TOTP code if 2FA enabled)
    - Returns: access_token (15-min JWT, Bearer) + sets httpOnly refresh cookie (7-day JWT)

  POST /auth/refresh
    - Reads httpOnly refresh cookie (no body required)
    - Returns: new access_token (15-min JWT)

  POST /auth/logout
    - Clears the httpOnly refresh cookie

[ OAuth Login ]
  GET /auth/google  --> redirect to Google consent screen
  GET /auth/google/callback  --> exchange code, find or create user, issue tokens

  GET /auth/github  --> redirect to GitHub consent screen
  GET /auth/github/callback  --> exchange code, find or create user, issue tokens

[ Device Auth ]
  X-API-Key: <static key>  --> set once in firmware config.h / NVS
```

## Deployment

| Service | Platform | Notes |
| ------- | -------- | ----- |
| Frontend | Vercel | Auto-deploy from main branch at phaemos.com |
| Docs site | Vercel | MkDocs Material build at docs.phaemos.com |
| Backend + DB + Redis | DigitalOcean VPS | Docker Compose + Nginx reverse proxy at api.phaemos.com |
| Status monitoring | Instatus | Hosted SaaS at status.phaemos.com (survives VPS outage) |
| Observability | Prometheus + Grafana | Docker Compose overlay on the VPS |

See [docs/deployment.md](deployment.md) for full setup instructions.

## Security Boundaries

- Device authentication: `X-API-Key` header on all telemetry ingests
- User authentication: JWT Bearer token (15-min expiry) on all protected routes
- Token refresh: 7-day httpOnly refresh cookie - short-lived access tokens minimise exposure window
- OAuth: Google and GitHub OAuth2 via authlib - users matched by email to prevent duplicate accounts
- 2FA: optional per-user TOTP enrolment via pyotp - QR code flow, confirmed before activation
- Role enforcement: middleware checks `user.role` (admin / technician / viewer) on every protected endpoint
- Per-user permission overrides: `permissions JSONB` column on users for fine-grained RBAC
- Password storage: bcrypt (passlib, cost factor 12)
- Rate limiting: slowapi per-IP limits on login (5/min), register (10/hr), contact (3/hr); X-Real-IP read from Nginx proxy
- No raw SQL: all queries via SQLAlchemy ORM (parameterised queries prevent injection)

## Background Tasks

Two APScheduler BackgroundScheduler instances run in daemon threads inside the FastAPI process:

| Task | Schedule | Description |
| ---- | -------- | ----------- |
| Demo telemetry | Every 5s (on-demand) | Generates sinusoidal sensor data for the Demo Node when /demo/start is called |
| Data retention | Daily at 02:00 UTC | Deletes telemetry rows older than 90 days; logs row count to audit_log |

Both tasks use their own SQLAlchemy sessions (not the request-scoped `Depends(get_db)`) to avoid cross-thread session sharing.

## Webhook Architecture

When a critical alert fires, the webhook service iterates all enabled webhook records and POSTs a JSON payload to each URL. Templates are optional - if provided, the template string is rendered with alert context before sending. Destinations supported: Slack (incoming webhooks), Discord (webhook URLs), Microsoft Teams (connector cards).

## Licence

PHAEMOS is released under the [GNU Affero General Public License v3](../LICENSE). Anyone running a modified version as a network service must publish the source under the same terms.
