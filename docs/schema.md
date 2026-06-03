# Database Schema

## Entity Relationship Summary

```text
users
  |-- tickets (assigned_to, created_by)
  |-- audit_logs
  |-- devices (owner_id - nullable)

devices
  |-- telemetry
  |-- alert_rules
  |-- alerts
  |-- tickets

alert_rules
  |-- alerts

alerts
  |-- tickets
```

## Tables

### devices

```sql
CREATE TABLE devices (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name             VARCHAR(100) NOT NULL,
  location         VARCHAR(100),
  type             VARCHAR(50),        -- 'esp32', 'arduino', 'stm32'
  api_key          VARCHAR(255) UNIQUE NOT NULL,
  status           VARCHAR(20) DEFAULT 'offline', -- online/offline/warning/fault
  firmware_version VARCHAR(50),
  last_seen        TIMESTAMP WITH TIME ZONE,
  created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  owner_id         UUID REFERENCES users(id) ON DELETE SET NULL, -- nullable; NULL = shared/unassigned (migration 003)
  tags             TEXT[] NOT NULL DEFAULT '{}'                  -- device tags for grouping and batch OTA (migration 008)
);
```

### telemetry

```sql
CREATE TABLE telemetry (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id     UUID REFERENCES devices(id) ON DELETE CASCADE,
  temperature   FLOAT,
  humidity      FLOAT,
  vibration_x   FLOAT,
  vibration_y   FLOAT,
  vibration_z   FLOAT,
  light_level   FLOAT,
  anomaly_score FLOAT,            -- ML output, 0-1
  is_anomaly    BOOLEAN DEFAULT FALSE,
  recorded_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_telemetry_device_recorded ON telemetry (device_id, recorded_at DESC);
```

### alert_rules

```sql
CREATE TABLE alert_rules (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id   UUID REFERENCES devices(id) ON DELETE CASCADE,
  metric      VARCHAR(50),        -- 'temperature', 'vibration_x', etc.
  condition   VARCHAR(10),        -- 'gt', 'lt', 'eq'
  threshold   FLOAT NOT NULL,
  severity    VARCHAR(20),        -- 'info', 'warning', 'critical'
  created_at  TIMESTAMP DEFAULT NOW()
);
```

### alerts

```sql
CREATE TABLE alerts (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id    UUID REFERENCES devices(id) ON DELETE CASCADE,
  rule_id      UUID REFERENCES alert_rules(id),
  message      TEXT,
  severity     VARCHAR(20),
  resolved     BOOLEAN DEFAULT FALSE,
  triggered_at TIMESTAMP DEFAULT NOW(),
  resolved_at  TIMESTAMP
);
```

### tickets

```sql
CREATE TABLE tickets (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket_number SERIAL NOT NULL,               -- auto-incrementing human-readable ID (PHM-0001 format) (migration 004)
  device_id     UUID REFERENCES devices(id),
  alert_id      UUID REFERENCES alerts(id),
  title         VARCHAR(200),
  description   TEXT,
  status        VARCHAR(20) DEFAULT 'open',    -- open/in_progress/closed
  priority      VARCHAR(20),                   -- low/medium/high/critical
  assigned_to   UUID REFERENCES users(id),
  created_by    UUID REFERENCES users(id),
  created_at    TIMESTAMP DEFAULT NOW(),
  updated_at    TIMESTAMP DEFAULT NOW()
);
```

### users

```sql
CREATE TABLE users (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                   VARCHAR(100),
  email                  VARCHAR(150) UNIQUE NOT NULL,
  password_hash          VARCHAR(255) NOT NULL,
  role                   VARCHAR(20) DEFAULT 'viewer',       -- admin/technician/viewer
  created_at             TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  last_login             TIMESTAMP WITH TIME ZONE,
  failed_login_attempts  INTEGER NOT NULL DEFAULT 0,         -- brute-force lockout counter (migration 002)
  locked_until           TIMESTAMP WITH TIME ZONE,           -- NULL = not locked (migration 002)
  -- OAuth + 2FA + RBAC columns (migration 005, 009)
  oauth_provider         VARCHAR(50),                        -- 'google' or 'github', NULL for password accounts
  oauth_id               VARCHAR(200),                       -- provider user ID
  phone_number           VARCHAR(20),                        -- optional, used for SMS alerts
  totp_secret            VARCHAR(100),                       -- TOTP shared secret (set when 2FA enabled)
  totp_enabled           BOOLEAN NOT NULL DEFAULT FALSE,     -- whether 2FA is active for this user
  permissions            JSONB NOT NULL DEFAULT '{}'         -- per-user permission overrides (migration 009)
);
```

### audit_logs

```sql
CREATE TABLE audit_logs (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID REFERENCES users(id),
  action     VARCHAR(100),   -- 'create_ticket', 'resolve_alert', etc.
  target     VARCHAR(100),   -- 'ticket', 'alert', 'device', etc.
  detail     TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### webhooks

Added in migration 006 (PR 95).

```sql
CREATE TABLE webhooks (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name       VARCHAR(200) NOT NULL,
  url        TEXT NOT NULL,
  enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  template   TEXT,                              -- optional Jinja2-style template; NULL = default payload
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### maintenance_windows

Added in migration 007 (PR 97).

```sql
CREATE TABLE maintenance_windows (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id       UUID REFERENCES devices(id) ON DELETE CASCADE, -- NULL = fleet-wide window
  label           VARCHAR(200) NOT NULL,
  start_at        TIMESTAMP WITH TIME ZONE NOT NULL,
  end_at          TIMESTAMP WITH TIME ZONE NOT NULL,
  suppress_alerts BOOLEAN NOT NULL DEFAULT TRUE,
  created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## Entity Relationship (updated)

```text
users
  |-- tickets (assigned_to, created_by)
  |-- audit_logs
  |-- devices (owner_id - nullable)
  |-- maintenance_windows (created_by)

devices
  |-- telemetry
  |-- alert_rules
  |-- alerts
  |-- tickets
  |-- maintenance_windows (device_id - nullable, NULL = fleet-wide)

alert_rules
  |-- alerts

alerts
  |-- tickets

webhooks  (standalone - fired on alert creation)
```

---

## Notes

- All primary keys use UUID to avoid enumerable IDs in API responses
- `telemetry` has a composite index on `(device_id, recorded_at DESC)` for fast latest-reading queries
- Cascade deletes on telemetry and alert_rules when a device is removed
- `updated_at` on tickets should be updated via a trigger or application logic on every PATCH
