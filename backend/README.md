# Backend

FastAPI application - telemetry ingestion, alert rules, tickets, ML anomaly detection, JWT auth, OAuth, 2FA, webhooks, maintenance windows and GDPR endpoints.

> [!NOTE]
> This folder is published to [phaemos/backend](https://github.com/phaemos/backend) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos).

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
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --no-access-log --ws-max-size 8192 --ws-per-message-deflate false
```

After any change to `requirements.txt` (the `cryptography` lower bound was raised) regenerate `requirements.lock` with `infra/scripts/lock-requirements.sh`, because the production image installs from the lock with `--require-hashes` and the build fails if the two disagree.

The access log is off because the live readings socket carries its token in the URL. Ensure `DATABASE_URL` and `REDIS_URL` point at running local instances before starting.

---

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `DATABASE_URL` | Yes | PostgreSQL connection string - `postgresql://user:pass@host:5432/db` |
| `REDIS_URL` | Yes | Redis connection string - `redis://localhost:6379` |
| `SECRET_KEY` | Yes | HS256 signing key for JWT tokens. Never empty. Outside development the API refuses to start with fewer than 32 characters or a value containing `change`, `placeholder`, `example`, `secret` or `test`. Rotate it to invalidate all sessions |
| `ALGORITHM` | No | JWT algorithm, default `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Access token lifetime in minutes, default `15` |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Production compose only | Create the database and build the API's `DATABASE_URL` in `infra/docker-compose.prod.yml`. The API itself never reads them |
| `TRUSTED_PROXIES` | No | Addresses allowed to set `X-Real-IP`. The production compose file sets the Docker gateway |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS origins, default `http://localhost:3000` |
| `WS_TOKEN_IN_URL` | No | Whether the live socket still accepts `?token=` in its address. Unset, it is allowed in development and refused elsewhere. Do not turn it on in production |
| `REFRESH_GRACE_SECONDS` | No | Seconds a swapped refresh token is still accepted. Default 10 |
| `EMAIL_CHANGES_PER_HOUR` / `EMAIL_CHANGES_PER_DAY` | No | Limits on one account changing its email. Defaults 3 and 5 |
| `SESSION_MAX_DAYS` | No | Absolute life of a sign-in session in days. Default 30 |
| `CREDENTIALED_ORIGINS` | No | The allowed origins that may send cookies. Default: the first of `ALLOWED_ORIGINS` |
| `WS_MAX_PER_USER` | No | Live sockets one account may hold at once. Default 5 |
| `WS_MAX_PER_ADDRESS` | No | Live sockets one address may hold at once. Default 20 |
| `SECRET_KEY_PREVIOUS` | No | The key before a rotation, used only to verify tokens and decrypt stored secrets |
| `TRUSTED_PROXIES` | No | The proxy address X-Real-IP is believed from. Empty by default, so forwarded headers are ignored |
| `REQUIRE_SESSION_ID` | Development only | Whether an access token with no session is accepted. Always required in production |
| `LOG_EMAIL_BODIES` | Development only | Log the body of an unsent email, which can hold a link with a token |
| `REGISTRATION_OPEN` | No | Whether anyone may create an account (`POST /auth/register` and a first OAuth sign-in). Unset, it is open in development and closed everywhere else. A self-made account is a viewer and a viewer reads every machine. Existing accounts still sign in and invitations still work |
| `ENVIRONMENT` | No | `development` by default. Exactly `development` (ignoring case and spaces) is development and any other value is treated as production: the refresh cookie is marked secure, the contact form needs Turnstile and Resend, only warnings are logged and `/docs`, `/redoc` and `/openapi.json` are switched off. The production compose file fixes it to `production` |
| `GOOGLE_CLIENT_ID` | No | Google OAuth2 client ID (required for Google login) |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth2 client secret |
| `GOOGLE_REDIRECT_URI` | No | Google OAuth2 callback URL, default `http://localhost:8000/api/v1/auth/google/callback` |
| `GITHUB_CLIENT_ID` | No | GitHub OAuth2 client ID (required for GitHub login) |
| `GITHUB_CLIENT_SECRET` | No | GitHub OAuth2 client secret |
| `GITHUB_REDIRECT_URI` | No | GitHub OAuth2 callback URL, default `http://localhost:8000/api/v1/auth/github/callback` |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook URL for critical alert notifications - leave blank to disable |
| `ALERT_EMAIL_TO` | No | Comma-separated recipient addresses for alert emails. Empty sends none |
| `RESEND_API_KEY` | For email | Resend API key (Send access) for contact messages, invitations and alert emails. Empty or `placeholder`: development logs what would have been sent and any other environment answers 503 on the contact form |
| `FROM_EMAIL` | No | Sender address on the verified Resend domain, default `no-reply@phaemos.com` |
| `BREVO_API_KEY` | For SMS | Brevo API key for critical alert texts. Leave blank to disable |
| `BREVO_SMS_SENDER` | No | Sender name on the text: 11 letters or digits at most. A numeric name may have up to 15 digits. No spaces. Default `PHAEMOS` |
| `ALERT_EMAIL_DAILY_CAP` | No | Most alert emails one UTC day may send in all. Each recipient counts. Default `50` |
| `ALERT_SMS_DAILY_CAP` | No | Most critical alert texts one UTC day may send in all. Default `20` |
| `DASHBOARD_URL` | No | Public address of the dashboard with no trailing slash. Invitation links are built from it. Default `http://localhost:3000` |
| `FIRMWARE_STORAGE_PATH` | No | Local directory for uploaded firmware binaries, default `./firmware_uploads` |
| `MODEL_PATH` | No | Where the trained model is read and written, default `ml/model.pkl` beside the code. Production points it at a Docker volume |
| `TURNSTILE_SECRET_KEY` | Outside development | Cloudflare Turnstile secret key for contact form verification. Empty when `ENVIRONMENT` is anything but `development`: the contact form answers 503. Empty in development: verification is skipped. |
| `CONTACT_EMAIL_TO` | No | Destination address for contact form submissions, default `contact@phaemos.com` |

---

## Route table

| Method | Path | Auth | Description |
| ------ | ---- | ---- | ----------- |
| GET | `/` | None | Liveness check |
| GET | `/status` | None | Public health check - API, database, Redis status |
| **Auth** | | | |
| POST | `/api/v1/auth/register` | None | Create a viewer account (10/hr rate limit). 403 when `REGISTRATION_OPEN` is off |
| GET | `/api/v1/auth/providers` | None | Which sign-in providers are configured, by name |
| GET | `/api/v1/auth/sessions` | Bearer | The caller's own live sessions (label, times, which is current) |
| DELETE | `/api/v1/auth/sessions/{id}` | Bearer | End one of the caller's own sessions |
| POST | `/api/v1/auth/sessions/end-others` | Bearer | Sign out everywhere else |
| POST | `/api/v1/auth/link/{provider}` | Bearer + proof | Start linking Google or GitHub to an account with a password |
| POST | `/api/v1/auth/invite/check` | None | Whether an invitation is valid, expired or used |
| GET | `/api/v1/auth/invitations` | Admin | Pending invitations |
| DELETE | `/api/v1/auth/invitations/{id}` | Admin + proof | Cancel an invitation |
| POST | `/api/v1/auth/users/{id}/deactivate`, `/reactivate`, `/clear-two-step`, `/reset-link` | Admin + proof | Account controls |
| PATCH | `/api/v1/auth/users/{id}/role` | Admin + proof | Change a role |
| DELETE | `/api/v1/auth/users/{id}` | Admin + proof | Remove an account |
| POST | `/api/v1/auth/reset-password` | Link | Choose a password with an admin's reset link |
| POST | `/api/v1/auth/login` | None | Login, returns access token + sets refresh cookie (5/min rate limit) |
| POST | `/api/v1/auth/refresh` | Cookie | Exchange refresh cookie for new access token |
| POST | `/api/v1/auth/logout` | Bearer | Clear refresh cookie |
| GET | `/api/v1/auth/me` | Bearer | Get current user profile |
| PATCH | `/api/v1/auth/me` | Bearer | Update name, email, phone number |
| POST | `/api/v1/auth/tokens` | Session and fresh proof | Make an access token (shown once) |
| GET | `/api/v1/auth/tokens` | Session or token | List the account's tokens |
| DELETE | `/api/v1/auth/tokens/{id}` | Session | Revoke a token |
| GET | `/api/v1/auth/whoami` | Session or token | The caller's account and how it signed in |
| POST | `/api/v1/auth/change-password` | Bearer | Change password (5/hr rate limit) |
| DELETE | `/api/v1/auth/me` | Bearer + proof | GDPR account deletion. Needs the password, a two-step code or a typed DELETE in the body. 409 while the person owns machines or is the last admin |
| GET | `/api/v1/auth/me/export` | Bearer | GDPR data export as JSON: profile, tickets raised and assigned, owned machines and own audit entries |
| GET | `/api/v1/auth/google` | None | Initiate Google OAuth |
| GET | `/api/v1/auth/google/callback` | None | Google OAuth callback |
| GET | `/api/v1/auth/github` | None | Initiate GitHub OAuth |
| GET | `/api/v1/auth/github/callback` | None | GitHub OAuth callback |
| GET | `/api/v1/auth/users` | Admin | List all users (paginated, no phone numbers) |
| POST | `/api/v1/auth/invite` | Admin | Send invitation email with signed JWT |
| GET | `/api/v1/auth/accept-invite/{token}` | None | Validate invitation token |
| POST | `/api/v1/auth/accept-invite` | None | Set password and activate invited account |
| POST | `/api/v1/auth/2fa/enable` | Bearer | Generate TOTP secret and QR code |
| POST | `/api/v1/auth/2fa/confirm` | Bearer | Confirm TOTP enrolment |
| POST | `/api/v1/auth/2fa/verify` | Sign-in challenge | Second sign-in step: the challenge from login or OAuth plus a TOTP code |
| POST | `/api/v1/auth/2fa/disable` | Bearer | Disable 2FA (requires valid TOTP code) |
| **Devices** | | | |
| GET | `/api/v1/devices` | Bearer | List devices (tag filter supported) |
| POST | `/api/v1/devices` | Admin | Register new device, returns API key |
| GET | `/api/v1/devices/{id}` | Bearer | Get single device |
| PATCH | `/api/v1/devices/{id}` | Admin/Tech | Update device. Owner, tags and firmware version are admin-only |
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
| POST | `/api/v1/tickets` | Admin/Tech | Create ticket (a technician needs write access to its machine) |
| GET | `/api/v1/tickets/assignees` | Admin/Tech | People a ticket can be assigned to (id and name) |
| GET | `/api/v1/tickets/{id}` | Bearer | Get ticket |
| PATCH | `/api/v1/tickets/{id}` | Admin/Tech | Update ticket |
| **Webhooks** | | | |
| GET | `/api/v1/webhooks` | Admin | List webhooks |
| POST | `/api/v1/webhooks` | Admin | Create webhook (https and public addresses only) |
| PATCH | `/api/v1/webhooks/{webhook_id}` | Admin | Update webhook |
| DELETE | `/api/v1/webhooks/{webhook_id}` | Admin | Delete webhook |
| POST | `/api/v1/webhooks/{webhook_id}/test` | Admin | Fire test payload |
| **Maintenance Windows** | | | |
| GET | `/api/v1/maintenance-windows` | Bearer | List windows |
| POST | `/api/v1/maintenance-windows` | Admin | Create window |
| PATCH | `/api/v1/maintenance-windows/{window_id}` | Admin | Update window |
| DELETE | `/api/v1/maintenance-windows/{window_id}` | Admin | Delete window |
| **Health** | | | |
| GET | `/api/v1/health/summary` | Bearer | Health stats for the machines the caller may read |
| **Firmware** | | | |
| GET | `/api/v1/firmware/latest` | X-API-Key | Latest firmware metadata (registered machine key, 30/min) |
| GET | `/api/v1/firmware/download` | X-API-Key | Download firmware binary (registered machine key, 10/min) |
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

## First admin

Registration is closed outside development, so the first admin is created from a terminal. The command asks for
an email and a password, typed without echo, applies the same password rules as the API and refuses an email that
already has an account:

```bash
python -m app.scripts.create_admin
```

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
psql $DATABASE_URL -f migrations/010_session_security.sql
psql $DATABASE_URL -f migrations/011_telemetry_device_time_index.sql
psql $DATABASE_URL -f migrations/013_ticket_delete_rules.sql
psql $DATABASE_URL -f migrations/016_user_sessions.sql
psql $DATABASE_URL -f migrations/017_alert_rule_delete_rule.sql
psql $DATABASE_URL -f migrations/018_provider_signin.sql
psql $DATABASE_URL -f migrations/019_webhook_disabled_reason.sql
psql $DATABASE_URL -f migrations/022_session_details.sql
psql $DATABASE_URL -f migrations/023_used_invites.sql
psql $DATABASE_URL -f migrations/024_email_changes.sql
psql $DATABASE_URL -f migrations/025_session_rotation.sql
psql $DATABASE_URL -f migrations/032_accounts_hardening.sql
psql $DATABASE_URL -f migrations/033_email_lower_case.sql
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
| 009 | RBAC permissions - permissions JSONB on users (retired, nothing reads it) |
| 010 | Session security - session version and one-time code columns |
| 011 | Telemetry index on device and time, built concurrently (see migrations/README.md) |
| 013 | Ticket foreign keys with ON DELETE SET NULL on every database (changed only where wrong, with a lock timeout) |
| 016 | Server-side sign-in sessions (`user_sessions`) |
| 022 | Session label and provider return time (on the session, not the user) |
| 023 | Used invitations (`used_invites`) |
| 024 | `users.email_since` and `email_changes`, for email change limits and notices |
| 025 | `user_sessions.previous_jti` and `rotated_at`, for the refresh grace |
| 032 | `users.is_active`, `deactivated_at`, `totp_secret` as TEXT for encrypted secrets and the `invitations` table |
| 033 | Lower-case email addresses and a unique index on `lower(email)` |
| 017 | `alerts.rule_id` keeps the alert when its rule is deleted |
| 018 | Retired (the time moved to the session in 022) |
| 019 | `webhooks.disabled_reason` |

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

The suite drops its tables when it finishes, so it refuses any database whose name does not end in `_test`. `make test` creates and uses `phaemos_test`. A direct `pytest` run uses `phaemos_test` on localhost unless `DATABASE_URL` says otherwise.
