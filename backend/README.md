# Backend

FastAPI application - telemetry ingestion, alert rules, tickets, ML anomaly detection, JWT auth, OAuth, 2FA, webhooks, maintenance windows and GDPR endpoints.

---

## Prerequisites

- Python 3.11+
- PostgreSQL 15
- Redis 7
- Docker + Docker Compose (optional, recommended)

---

## Run locally

### With Docker (recommended)

```bash
cp ../.env.example ../.env
# edit .env with your values
docker compose up db redis backend -d
```

API: <http://localhost:8000>
Docs: <http://localhost:8000/docs>

### Without Docker

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Ensure `DATABASE_URL` and `REDIS_URL` point at running local instances before starting.

---

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `DATABASE_URL` | Yes | PostgreSQL connection string - `postgresql://user:pass@host:5432/db` |
| `REDIS_URL` | Yes | Redis connection string - `redis://localhost:6379` |
| `SECRET_KEY` | Yes | HS256 signing key for JWT tokens - minimum 32 characters, rotate to invalidate all sessions |
| `ALGORITHM` | No | JWT algorithm, default `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Access token lifetime in minutes, default `15` |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS origins, default `http://localhost:3000` |
| `ENVIRONMENT` | No | `development` or `production` - controls debug endpoints and error verbosity |
| `GOOGLE_CLIENT_ID` | No | Google OAuth2 client ID (required for Google login) |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth2 client secret |
| `GOOGLE_REDIRECT_URI` | No | Google OAuth2 callback URL, default `http://localhost:8000/api/v1/auth/google/callback` |
| `GITHUB_CLIENT_ID` | No | GitHub OAuth2 client ID (required for GitHub login) |
| `GITHUB_CLIENT_SECRET` | No | GitHub OAuth2 client secret |
| `GITHUB_REDIRECT_URI` | No | GitHub OAuth2 callback URL, default `http://localhost:8000/api/v1/auth/github/callback` |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook URL for critical alert notifications - leave blank to disable |
| `SMTP_HOST` | No | SMTP server hostname - leave blank to disable email notifications |
| `SMTP_PORT` | No | SMTP port, default `587` |
| `SMTP_USER` | No | SMTP username |
| `SMTP_PASSWORD` | No | SMTP password |
| `ALERT_EMAIL_TO` | No | Comma-separated recipient addresses for alert emails |
| `RESEND_API_KEY` | No | Resend API key for invitation emails |
| `FROM_EMAIL` | No | Sender address for invitation emails, default `no-reply@phaemos.com` |
| `BREVO_API_KEY` | No | Brevo API key for SMS critical alerts - leave blank to disable |
| `BREVO_SMS_SENDER` | No | SMS sender name shown on recipient's phone, max 11 chars, default `PHAEMOS` |
| `FIRMWARE_STORAGE_PATH` | No | Local directory for uploaded firmware binaries, default `./firmware_uploads` |
| `ANOMALY_SCORE_THRESHOLD` | No | Anomaly score above which a reading is flagged, default `0.7` |
| `ANOMALY_CRITICAL_THRESHOLD` | No | Anomaly score above which a critical alert fires, default `0.85` |
| `TURNSTILE_SECRET_KEY` | No | Cloudflare Turnstile secret key for contact form verification |
| `CONTACT_EMAIL_TO` | No | Destination address for contact form submissions, default `contact@phaemos.com` |

---

## Route table

| Method | Path | Auth | Description |
| ------ | ---- | ---- | ----------- |
| GET | `/health` | None | Liveness check |
| GET | `/status` | None | Public health check - API, database, Redis status |
| **Auth** | | | |
| POST | `/api/v1/auth/register` | None | Create account (10/hr rate limit) |
| POST | `/api/v1/auth/login` | None | Login, returns access token + sets refresh cookie (5/min rate limit) |
| POST | `/api/v1/auth/refresh` | Cookie | Exchange refresh cookie for new access token |
| POST | `/api/v1/auth/logout` | Bearer | Clear refresh cookie |
| GET | `/api/v1/auth/me` | Bearer | Get current user profile |
| PATCH | `/api/v1/auth/me` | Bearer | Update name, email, phone number |
| POST | `/api/v1/auth/change-password` | Bearer | Change password (5/hr rate limit) |
| DELETE | `/api/v1/auth/me` | Bearer | GDPR account deletion |
| GET | `/api/v1/auth/me/export` | Bearer | GDPR data export as JSON |
| GET | `/api/v1/auth/google` | None | Initiate Google OAuth |
| GET | `/api/v1/auth/google/callback` | None | Google OAuth callback |
| GET | `/api/v1/auth/github` | None | Initiate GitHub OAuth |
| GET | `/api/v1/auth/github/callback` | None | GitHub OAuth callback |
| GET | `/api/v1/auth/users` | Admin | List all users (paginated) |
| PATCH | `/api/v1/auth/users/{user_id}/permissions` | Admin | Set per-user permission overrides |
| POST | `/api/v1/auth/invite` | Admin | Send invitation email with signed JWT |
| GET | `/api/v1/auth/accept-invite/{token}` | None | Validate invitation token |
| POST | `/api/v1/auth/accept-invite` | None | Set password and activate invited account |
| POST | `/api/v1/auth/2fa/enable` | Bearer | Generate TOTP secret and QR code |
| POST | `/api/v1/auth/2fa/confirm` | Bearer | Confirm TOTP enrolment |
| POST | `/api/v1/auth/2fa/verify` | None | Verify TOTP code during login |
| POST | `/api/v1/auth/2fa/disable` | Bearer | Disable 2FA (requires valid TOTP code) |
| **Devices** | | | |
| GET | `/api/v1/devices` | Bearer | List devices (tag filter supported) |
| POST | `/api/v1/devices` | Admin | Register new device, returns API key |
| GET | `/api/v1/devices/{id}` | Bearer | Get single device |
| PATCH | `/api/v1/devices/{id}` | Admin | Update device |
| DELETE | `/api/v1/devices/{id}` | Admin | Delete device (cascades) |
| POST | `/api/v1/devices/{device_id}/tags` | Admin | Add a tag to a device |
| DELETE | `/api/v1/devices/{device_id}/tags/{tag}` | Admin | Remove a tag from a device |
| POST | `/api/v1/devices/batch/firmware-update` | Admin | Batch OTA update by tag |
| **Telemetry** | | | |
| POST | `/api/v1/telemetry` | X-API-Key | Ingest sensor reading |
| GET | `/api/v1/telemetry/{device_id}` | Bearer | Paginated telemetry (from_ts/to_ts/node_type filters) |
| GET | `/api/v1/telemetry/{device_id}/latest` | Bearer | Latest reading for a device |
| GET | `/api/v1/telemetry/export` | Bearer | Stream telemetry as CSV |
| **Alert Rules** | | | |
| GET | `/api/v1/alert-rules` | Bearer | List rules (device_id filter) |
| POST | `/api/v1/alert-rules` | Admin | Create threshold rule |
| PUT | `/api/v1/alert-rules/{id}` | Admin | Update rule |
| DELETE | `/api/v1/alert-rules/{id}` | Admin | Delete rule |
| **Alerts** | | | |
| GET | `/api/v1/alerts` | Bearer | List alerts |
| GET | `/api/v1/alerts/{device_id}` | Bearer | Alerts for a device |
| PATCH | `/api/v1/alerts/{id}/resolve` | Admin/Tech | Resolve an alert |
| **Tickets** | | | |
| GET | `/api/v1/tickets` | Bearer | List tickets (paginated, status filter) |
| POST | `/api/v1/tickets` | Bearer | Create ticket |
| GET | `/api/v1/tickets/{id}` | Bearer | Get ticket |
| PATCH | `/api/v1/tickets/{id}` | Admin/Tech | Update ticket |
| **Webhooks** | | | |
| GET | `/api/v1/webhooks` | Admin | List webhooks |
| POST | `/api/v1/webhooks` | Admin | Create webhook |
| PATCH | `/api/v1/webhooks/{webhook_id}` | Admin | Update webhook |
| DELETE | `/api/v1/webhooks/{webhook_id}` | Admin | Delete webhook |
| POST | `/api/v1/webhooks/{webhook_id}/test` | Admin | Fire test payload |
| **Maintenance Windows** | | | |
| GET | `/api/v1/maintenance-windows` | Bearer | List windows |
| POST | `/api/v1/maintenance-windows` | Admin | Create window |
| PATCH | `/api/v1/maintenance-windows/{window_id}` | Admin | Update window |
| DELETE | `/api/v1/maintenance-windows/{window_id}` | Admin | Delete window |
| **Health** | | | |
| GET | `/api/v1/health/summary` | Bearer | Fleet health stats |
| **Firmware** | | | |
| GET | `/api/v1/firmware/latest` | X-API-Key | Latest firmware metadata |
| GET | `/api/v1/firmware/download` | X-API-Key | Download firmware binary |
| **ML** | | | |
| POST | `/api/v1/ml/retrain` | Admin | Trigger background retrain |
| POST | `/api/v1/ml/score` | Admin | Score a single reading |
| GET | `/api/v1/ml/anomalies/{device_id}` | Bearer | Anomalous readings for a device |
| **Audit** | | | |
| GET | `/api/v1/audit-logs` | Admin | Paginated audit log |
| GET | `/api/v1/audit-logs/export` | Admin | CSV export with HMAC-SHA256 signature |
| **Contact** | | | |
| POST | `/api/v1/contact` | None | Contact form (Turnstile verify, 3/hr rate limit) |
| **Demo** | | | |
| POST | `/api/v1/demo/start` | None | Start synthetic telemetry generation |
| POST | `/api/v1/demo/stop` | None | Stop synthetic telemetry generation |
| **WebSocket** | | | |
| WS | `/ws/telemetry/{device_id}` | ?token= | Live telemetry push stream |

---

## Migrations

Apply in order. Each file is idempotent when run on a fresh database in sequence.

```bash
make migrate
# or manually:
psql $DATABASE_URL -f migrations/001_initial_schema.sql
psql $DATABASE_URL -f migrations/002_security_hardening.sql
psql $DATABASE_URL -f migrations/003_multi_tenant.sql
psql $DATABASE_URL -f migrations/004_ticket_numbers.sql
psql $DATABASE_URL -f migrations/005_oauth_and_profile.sql
psql $DATABASE_URL -f migrations/006_webhooks.sql
psql $DATABASE_URL -f migrations/007_maintenance_windows.sql
psql $DATABASE_URL -f migrations/008_device_tags.sql
psql $DATABASE_URL -f migrations/009_rbac_permissions.sql
```

| Migration | What it adds |
| --------- | ------------ |
| 001 | Initial schema - users, devices, telemetry, alert_rules, alerts, tickets, audit_logs |
| 002 | Security hardening - failed_login_attempts, locked_until on users |
| 003 | Multi-tenant - owner_id FK on devices |
| 004 | Ticket numbers - ticket_number SERIAL on tickets |
| 005 | OAuth and profile - oauth_provider, oauth_id, phone_number, totp_secret, totp_enabled on users |
| 006 | Webhooks - webhooks table |
| 007 | Maintenance windows - maintenance_windows table |
| 008 | Device tags - tags TEXT[] on devices |
| 009 | RBAC permissions - permissions JSONB on users |

---

## Tests

```bash
make test
# or:
cd backend && pytest
# with coverage:
cd backend && pytest --cov=app tests/
```

Tests require a running PostgreSQL instance. The CI workflow starts a Docker container automatically. Locally, `docker compose up db -d` is the quickest way to get one.
