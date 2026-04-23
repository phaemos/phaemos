# Database Schema

## Entity Relationship Summary

```
users
  |-- tickets (assigned_to, created_by)
  |-- audit_logs

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
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        VARCHAR(100) NOT NULL,
  location    VARCHAR(100),
  type        VARCHAR(50),        -- 'esp32', 'arduino', 'stm32'
  api_key     VARCHAR(255) UNIQUE NOT NULL,
  status      VARCHAR(20) DEFAULT 'offline', -- online/offline/warning/fault
  last_seen   TIMESTAMP,
  created_at  TIMESTAMP DEFAULT NOW()
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
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          VARCHAR(100),
  email         VARCHAR(150) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role          VARCHAR(20) DEFAULT 'viewer',  -- admin/technician/viewer
  created_at    TIMESTAMP DEFAULT NOW()
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

## Notes

- All primary keys use UUID to avoid enumerable IDs in API responses
- `telemetry` has a composite index on `(device_id, recorded_at DESC)` for fast latest-reading queries
- Cascade deletes on telemetry and alert_rules when a device is removed
- `updated_at` on tickets should be updated via a trigger or application logic on every PATCH
