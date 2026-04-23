# API Reference

Base URL: `http://localhost:8000/api/v1`

Interactive docs: `http://localhost:8000/docs` (Swagger UI)

## Authentication

**Device ingestion** uses an API key header:

```
X-API-Key: <device api key>
```

**User routes** use a Bearer JWT token:

```
Authorization: Bearer <jwt token>
```

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
  "vibration_x": 0.12,
  "vibration_y": -0.04,
  "vibration_z": 9.81,
  "light_level": 512
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

**Query params:** `limit` (default 100), `offset` (default 0)

**Auth:** Bearer JWT

---

### GET /telemetry/{device_id}/latest

Returns the single most recent reading for a device.

**Auth:** Bearer JWT

---

## Devices

### GET /devices

List all registered devices.

**Auth:** Bearer JWT

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

## Alert Rules

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

---

### GET /tickets/{id}

Get a single ticket with full detail.

**Auth:** Bearer JWT

---

### PATCH /tickets/{id}

Update ticket status, priority or assignee.

**Auth:** Bearer JWT (Admin or Technician)

---

## Auth

### POST /auth/register

Create a new user account.

**Request body:**

```json
{
  "name": "Isaac Adjei",
  "email": "isaac@example.com",
  "password": "securepassword"
}
```

---

### POST /auth/login

Login and receive a JWT token.

**Request body:**

```json
{
  "email": "isaac@example.com",
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

---

### GET /auth/me

Returns the currently authenticated user's profile.

**Auth:** Bearer JWT

---

## ML

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

## Error Responses

| Code | Meaning                         |
| ---- | ------------------------------- |
| 400  | Bad request - validation error  |
| 401  | Missing or invalid auth         |
| 403  | Insufficient role               |
| 404  | Resource not found              |
| 422  | Unprocessable entity (Pydantic) |
| 500  | Internal server error           |
