# API Reference

Base URL: `https://api.phaemos.com/api/v1` (production) or `http://localhost:8000/api/v1` (local)

Interactive docs: `http://localhost:8000/docs` (Swagger UI)

## Authentication

**Device ingestion** uses an API key header:

```text
X-API-Key: <device api key>
```

**User routes** use a Bearer JWT token (15-minute expiry):

```text
Authorization: Bearer <access_token>
```

**Token refresh** uses a 7-day httpOnly cookie (no header needed - the browser sends it automatically).

---

## Telemetry

### POST /telemetry

Ingest a sensor reading. Called by ESP32/firmware every cycle.

**Auth:** `X-API-Key`

**Request body:**

```json
{
  "device_id": "uuid",
  "temperature": 34.2,
  "humidity": 61.5,
  "pressure": 1013.2,
  "vibration_x": 0.12,
  "vibration_y": -0.04,
  "vibration_z": 9.81,
  "gyro_x": 0.01,
  "gyro_y": -0.02,
  "gyro_z": 0.00,
  "bus_voltage": 5.1,
  "current_ma": 320.0,
  "power_mw": 1632.0,
  "ir_temperature": 42.5,
  "distance_mm": 185,
  "gas_level": 120,
  "gas_alert": false,
  "shaft_angle": 45.0,
  "shaft_rpm": 1200.0,
  "sound_level": 520,
  "contact_temp": 38.1,
  "light_level": 512,
  "moisture_level": 230,
  "water_detected": false,
  "fft_peak_hz": 62.5,
  "vib_magnitude": 0.87,
  "node_type": "esp32"
}
```

**Response 201:**

```json
{
  "id": "uuid",
  "anomaly_score": 0.12,
  "is_anomaly": false,
  "recorded_at": "2026-04-23T12:00:00Z"
}
```

---

### GET /telemetry/{device_id}

Returns paginated telemetry for a device.

**Auth:** Bearer JWT

**Query params:** `limit` (default 100), `offset` (default 0), `from_ts` (ISO datetime), `to_ts` (ISO datetime), `node_type`

---

### GET /telemetry/{device_id}/latest

Returns the single most recent reading for a device.

**Auth:** Bearer JWT

---

### GET /telemetry/export

Stream all telemetry for a device as a CSV file.

**Auth:** Bearer JWT

**Query params:** `device_id` (required), `from_ts` (ISO datetime, optional), `to_ts` (ISO datetime, optional)

**Response:** `text/csv` with `Content-Disposition: attachment`

---

## Devices

### GET /devices

List all registered devices. Supports tag-based filtering.

**Auth:** Bearer JWT

**Query params:** `skip` (default 0), `limit` (default 20), `tag` (optional - filter by tag string)

---

### POST /devices

Register a new device. Returns generated API key.

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{
  "name": "Workshop Node 1",
  "location": "Workshop Bay A",
  "type": "esp32"
}
```

---

### GET /devices/{id}

Get a single device with latest status.

**Auth:** Bearer JWT

---

### PATCH /devices/{id}

Update device name, location or status.

**Auth:** Bearer JWT (Admin only)

---

### DELETE /devices/{id}

Remove device and cascade-delete its telemetry and rules.

**Auth:** Bearer JWT (Admin only)

---

### POST /devices/{device_id}/tags

Add a tag to a device.

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{ "tag": "pump-room" }
```

---

### DELETE /devices/{device_id}/tags/{tag}

Remove a specific tag from a device.

**Auth:** Bearer JWT (Admin only)

---

### POST /devices/batch/firmware-update

Trigger an OTA firmware update for all devices matching a given tag.

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{
  "tag": "pump-room",
  "version": "v1.4.2"
}
```

**Response 202:**

```json
{ "detail": "Batch firmware update queued for tag pump-room." }
```

---

## Alert Rules

### GET /alert-rules

List all alert rules. Optional `?device_id=` filter.

**Auth:** Bearer JWT

---

### POST /alert-rules

Create a threshold rule for a device metric.

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{
  "device_id": "uuid",
  "metric": "temperature",
  "condition": "gt",
  "threshold": 80.0,
  "severity": "critical"
}
```

---

### PUT /alert-rules/{id}

Update a rule's metric, condition, threshold or severity.

**Auth:** Bearer JWT (Admin only)

---

### DELETE /alert-rules/{id}

Delete an alert rule.

**Auth:** Bearer JWT (Admin only)

---

## Alerts

### GET /alerts

List all alerts. Filter by `resolved=false` for active alerts.

**Auth:** Bearer JWT

---

### GET /alerts/{device_id}

All alerts for a specific device.

**Auth:** Bearer JWT

---

### PATCH /alerts/{id}/resolve

Mark an alert as resolved.

**Auth:** Bearer JWT (Admin or Technician)

---

## Tickets

### GET /tickets

List all tickets. Technicians see only tickets assigned to them.

**Auth:** Bearer JWT

**Query params:** `skip` (default 0), `limit` (default 20), `status` (optional: open, in_progress, closed)

---

### POST /tickets

Create a maintenance ticket, optionally linked to an alert.

**Auth:** Bearer JWT

**Request body:**

```json
{
  "device_id": "uuid",
  "alert_id": "uuid or null",
  "title": "High temperature on Workshop Node 1",
  "description": "Temperature exceeded 80C threshold.",
  "priority": "critical"
}
```

**Response:** includes `ticket_number` field (displayed as PHM-0001 format)

---

### GET /tickets/{id}

Get a single ticket with full detail including `ticket_number`.

**Auth:** Bearer JWT

---

### PATCH /tickets/{id}

Update ticket status, priority or assignee.

**Auth:** Bearer JWT (Admin or Technician)

---

## Auth

### POST /auth/register

Create a new user account.

**Rate limit:** 10/hour per IP

**Request body:**

```json
{
  "name": "Jane Smith",
  "email": "jane@example.com",
  "password": "securepassword"
}
```

---

### POST /auth/login

Login and receive a short-lived access token. Sets a 7-day httpOnly refresh cookie.

**Rate limit:** 5/minute per IP

**Request body:**

```json
{
  "email": "jane@example.com",
  "password": "securepassword"
}
```

**Response 200:**

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

If the account has 2FA enabled, the response returns `{ "requires_2fa": true, "temp_token": "..." }` instead, and the client must call `POST /auth/2fa/verify` to complete login.

---

### POST /auth/refresh

Exchange the httpOnly refresh cookie for a new 15-minute access token. No request body needed - the cookie is read automatically.

**Auth:** None (cookie-based)

**Response 200:**

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

---

### POST /auth/logout

Clear the httpOnly refresh cookie.

**Auth:** Bearer JWT

**Response 200:**

```json
{ "detail": "Logged out." }
```

---

### GET /auth/me

Returns the currently authenticated user's profile.

**Auth:** Bearer JWT

---

### PATCH /auth/me

Update the current user's name, email or phone number.

**Auth:** Bearer JWT

**Rate limit:** 5/hour per IP

**Request body (all fields optional):**

```json
{
  "name": "Jane Smith",
  "email": "jane@example.com",
  "phone_number": "+447700900000"
}
```

---

### POST /auth/change-password

Change the current user's password.

**Auth:** Bearer JWT

**Rate limit:** 5/hour per IP

**Request body:**

```json
{
  "old_password": "currentpassword",
  "new_password": "newsecurepassword"
}
```

---

### DELETE /auth/me

GDPR account deletion. Anonymises the user's tickets and audit log entries, then deletes the account.

**Auth:** Bearer JWT

**Response 200:**

```json
{ "detail": "Account deleted." }
```

---

### GET /auth/me/export

GDPR data export. Returns a JSON bundle of all data associated with the current user.

**Auth:** Bearer JWT

**Response 200:** JSON object containing user profile, tickets, audit log entries.

---

### GET /auth/google

Initiate Google OAuth flow. Redirects to Google consent screen.

**Auth:** None (public)

---

### GET /auth/google/callback

Google OAuth callback. Exchanges the authorisation code, creates or finds the user by email, and issues tokens.

**Auth:** None (public)

---

### GET /auth/github

Initiate GitHub OAuth flow. Redirects to GitHub consent screen.

**Auth:** None (public)

---

### GET /auth/github/callback

GitHub OAuth callback. Exchanges the authorisation code, creates or finds the user by email, and issues tokens.

**Auth:** None (public)

---

### GET /auth/users

Return a paginated list of all users.

**Auth:** Bearer JWT (Admin only)

**Query params:** `skip`, `limit` (default 50)

---

### PATCH /auth/users/{user_id}/permissions

Set per-user permission overrides (e.g. `can_manage_devices`, `devices_scope`).

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{
  "permissions": {
    "can_manage_devices": true,
    "devices_scope": ["uuid1", "uuid2"]
  }
}
```

---

### POST /auth/invite

Send an invitation email to a new user with a signed JWT link.

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{
  "email": "newuser@example.com",
  "role": "technician"
}
```

---

### GET /auth/accept-invite/{token}

Validate an invitation token. Returns the email address encoded in the token.

**Auth:** None (public)

---

### POST /auth/accept-invite

Set a password and activate an invited account.

**Auth:** None (public)

**Request body:**

```json
{
  "token": "signed-jwt-from-email",
  "password": "newpassword"
}
```

---

### POST /auth/2fa/enable

Generate a TOTP secret and QR code URI for the current user. Does not activate 2FA until confirmed.

**Auth:** Bearer JWT

**Response 200:**

```json
{
  "secret": "BASE32SECRET",
  "qr_uri": "otpauth://totp/PHAEMOS:jane@example.com?secret=..."
}
```

---

### POST /auth/2fa/confirm

Confirm TOTP enrolment by submitting the first valid code from the authenticator app. Activates 2FA on the account.

**Auth:** Bearer JWT

**Request body:**

```json
{ "code": "123456" }
```

---

### POST /auth/2fa/verify

Verify a TOTP code during the two-step login flow (after `POST /auth/login` returns `requires_2fa: true`).

**Auth:** None (public - uses temp_token from login response)

**Request body:**

```json
{
  "temp_token": "...",
  "code": "123456"
}
```

**Response 200:** same as `/auth/login` - access token + refresh cookie

---

### POST /auth/2fa/disable

Disable 2FA on the current account. Requires a valid TOTP code to prevent accidental or unauthorised disabling.

**Auth:** Bearer JWT

**Request body:**

```json
{ "code": "123456" }
```

---

## Firmware

### GET /firmware/latest

Returns metadata for the latest available firmware version.

**Auth:** `X-API-Key` (device auth)

**Response 200:**

```json
{
  "version": "v1.4.2",
  "released_at": "2026-05-01T09:00:00Z",
  "size_bytes": 487320
}
```

---

### GET /firmware/download

Download the latest firmware binary.

**Auth:** `X-API-Key` (device auth)

**Response:** `application/octet-stream` binary

---

## Health

### GET /health/summary

Fleet-wide health statistics.

**Auth:** Bearer JWT

**Response 200:**

```json
{
  "total_devices": 12,
  "online": 10,
  "offline": 2,
  "active_alerts": 3,
  "open_tickets": 5,
  "health_score": 84
}
```

---

## Status (public)

### GET /status

Public health check. Returns API, database and Redis status. No authentication required.

**Auth:** None

**Response 200:**

```json
{
  "status": "ok",
  "api": "ok",
  "database": "ok",
  "redis": "ok",
  "updated_at": "2026-06-03T10:00:00Z"
}
```

---

## Maintenance Windows

### GET /maintenance-windows

List all maintenance windows ordered by start time.

**Auth:** Bearer JWT

---

### POST /maintenance-windows

Create a maintenance window. Optionally scoped to a specific device.

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{
  "label": "Monthly pump inspection",
  "start_at": "2026-06-10T08:00:00Z",
  "end_at": "2026-06-10T12:00:00Z",
  "suppress_alerts": true,
  "device_id": "uuid or null"
}
```

---

### PATCH /maintenance-windows/{window_id}

Update a maintenance window's label, times or suppress_alerts flag.

**Auth:** Bearer JWT (Admin only)

---

### DELETE /maintenance-windows/{window_id}

Delete a maintenance window.

**Auth:** Bearer JWT (Admin only)

---

## Webhooks

### GET /webhooks

List all configured webhooks.

**Auth:** Bearer JWT (Admin only)

---

### POST /webhooks

Create a new webhook destination (Slack, Discord or Teams).

**Auth:** Bearer JWT (Admin only)

**Request body:**

```json
{
  "name": "Slack - #alerts",
  "url": "https://hooks.slack.com/services/...",
  "enabled": true,
  "template": null
}
```

---

### PATCH /webhooks/{webhook_id}

Update a webhook's name, URL, enabled state or template.

**Auth:** Bearer JWT (Admin only)

---

### DELETE /webhooks/{webhook_id}

Delete a webhook.

**Auth:** Bearer JWT (Admin only)

---

### POST /webhooks/{webhook_id}/test

Fire a test payload to the webhook URL to verify the connection.

**Auth:** Bearer JWT (Admin only)

**Response 200:**

```json
{ "detail": "Test payload sent." }
```

---

## Audit

### GET /audit-logs

Returns paginated audit log entries.

**Auth:** Bearer JWT (Admin only)

**Query params:** `skip`, `limit` (default 50)

---

### GET /audit-logs/export

Export filtered audit log entries as a CSV file. Response includes an `X-Signature` header containing an HMAC-SHA256 of the CSV body for integrity verification.

**Auth:** Bearer JWT (Admin only)

**Query params:** `from` (ISO datetime), `to` (ISO datetime), `action` (string filter), `user_id` (UUID filter)

**Response:** `text/csv` with `Content-Disposition: attachment` and `X-Signature: sha256=<hmac>`

---

## Contact

### POST /contact

Submit a contact form message. Turnstile token is verified server-side before the email is sent.

**Auth:** None (public)

**Rate limit:** 3/hour per IP

**Request body:**

```json
{
  "name": "Jane Smith",
  "email": "jane@example.com",
  "message": "Hello, I have a question about...",
  "turnstile_token": "..."
}
```

**Response 200:**

```json
{ "detail": "Message received. We will be in touch shortly." }
```

---

## ML

### POST /ml/retrain

Trigger a background retrain of the Isolation Forest model on the last 10,000 telemetry rows. Returns immediately with 202; the task runs asynchronously.

**Auth:** Bearer JWT (Admin only)

**Response 202:**

```json
{ "detail": "Retrain started. Model will be updated in the background." }
```

**Response 429 (cooldown active):**

```json
{ "detail": "Retrain cooldown active. Try again in 47 minutes." }
```

---

### POST /ml/score

Score a single reading manually (useful for testing the model).

**Auth:** Bearer JWT (Admin only)

**Request body:** same as telemetry payload

**Response:**

```json
{
  "anomaly_score": 0.83,
  "is_anomaly": true
}
```

---

### GET /ml/anomalies/{device_id}

Returns all anomalous telemetry rows for a device.

**Auth:** Bearer JWT

---

## WebSocket

### WS /ws/telemetry/{device_id}

Receive live telemetry pushes for a single device without polling.

**Auth:** `?token=<jwt>` query parameter (Bearer token passed as query string because the WebSocket handshake cannot carry custom headers)

**Close codes:**

- `1008` - auth failure (invalid or missing token). The frontend must not retry on 1008 to avoid an infinite loop on an expired token.

**Messages:** Server pushes the same JSON shape as `TelemetryResponse` whenever a new reading is ingested via `POST /telemetry`.

---

## Demo

### POST /demo/start

Register (or reuse) a Demo Node virtual device and start a 5-second APScheduler job generating synthetic telemetry.

**Auth:** None

**Response:**

```json
{ "device_id": "uuid", "api_key": "string", "status": "started" }
```

---

### POST /demo/stop

Cancel the demo telemetry job.

**Auth:** None

---

## Error Responses

| Code | Meaning |
| ---- | ------- |
| 400 | Bad request - validation error |
| 401 | Missing or invalid auth |
| 403 | Insufficient role |
| 404 | Resource not found |
| 422 | Unprocessable entity (Pydantic) |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
