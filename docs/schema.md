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
  key_id           VARCHAR(16),        -- the first 8 characters of the device key, in clear, to find the machine (migration 031). Unique where set
  key_hash         VARCHAR(64),        -- keyed hash (HMAC-SHA256) of the whole key. The key itself is never stored (migration 031)
  api_key          VARCHAR(255) UNIQUE, -- old clear column, empty once a key is hashed. Dropped in a later migration
  last_boot        BIGINT,             -- the (boot, seq) pair of the last post accepted (migration 031)
  last_seq         BIGINT,
  replay_protected BOOLEAN NOT NULL DEFAULT FALSE, -- true once the machine has sent the pair
  replay_refused   INTEGER NOT NULL DEFAULT 0,     -- posts refused for an old pair since the last accepted one
  replay_refused_at TIMESTAMPTZ,
  stuck_state      JSONB NOT NULL DEFAULT '{}',    -- per column state of the stuck sensor check
  status           VARCHAR(20) DEFAULT 'offline', -- online/offline/warning/fault
  firmware_version VARCHAR(50),
  last_seen        TIMESTAMP WITH TIME ZONE,
  created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  owner_id         UUID REFERENCES users(id) ON DELETE SET NULL, -- nullable; NULL = shared/unassigned (migration 003)
  tags             TEXT[] NOT NULL DEFAULT '{}',                 -- device tags for grouping and batch OTA (migration 008)
  expected_interval_s INTEGER NOT NULL DEFAULT 5,                -- seconds between posts (migration 012)
  link_state       VARCHAR(10) NOT NULL DEFAULT 'offline',       -- online/late/offline, from the age of the last post (migration 012)
  not_fitted       TEXT[] NOT NULL DEFAULT '{}',                 -- sensor keys not expected on this machine (migration 015)
  unscored_since   TIMESTAMPTZ,                                  -- since when no reading was scored (migration 015)
  unscored_missing TEXT[] NOT NULL DEFAULT '{}',                 -- the model inputs the readings lacked (migration 015)
  unscored_alerted BOOLEAN NOT NULL DEFAULT FALSE,               -- the no-scored-reading alert is open (migration 015)
  clipping_last_true TIMESTAMPTZ,                                -- when the vibration node last reported clipping (migration 021)
  clipping_alerted BOOLEAN NOT NULL DEFAULT FALSE                -- the clipping warning is open (migration 021)
);
```

### telemetry

```sql
CREATE TABLE telemetry (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id       UUID REFERENCES devices(id) ON DELETE CASCADE,
  node_type       VARCHAR(20),                  -- esp32/stm32/nano/pico_w
  temperature     FLOAT,                        -- BME280
  humidity        FLOAT,                        -- BME280
  pressure        FLOAT,                        -- BME280
  vibration_x     FLOAT,                        -- MPU6050
  vibration_y     FLOAT,                        -- MPU6050
  vibration_z     FLOAT,                        -- MPU6050
  gyro_x          FLOAT,                        -- MPU6050
  gyro_y          FLOAT,                        -- MPU6050
  gyro_z          FLOAT,                        -- MPU6050
  bus_voltage     FLOAT,                        -- INA219
  current_ma      FLOAT,                        -- INA219
  power_mw        FLOAT,                        -- INA219
  ir_temperature  FLOAT,                        -- MLX90614
  distance_mm     FLOAT,                        -- VL53L0X
  gas_level       FLOAT,                        -- MQ-2
  gas_alert       BOOLEAN DEFAULT FALSE,         -- MQ-2 digital output
  shaft_angle     FLOAT,                        -- AS5600
  shaft_rpm       FLOAT,                        -- AS5600
  sound_level     FLOAT,                        -- MAX4466
  light_level     FLOAT,                        -- LDR
  contact_temp    FLOAT,                        -- DS18B20
  moisture_level  FLOAT,                        -- FC-28
  water_detected  BOOLEAN DEFAULT FALSE,         -- FC-28
  fft_peak_hz     FLOAT,                        -- STM32 FFT output
  vib_magnitude   FLOAT,                        -- STM32 FFT output
  vib_rms_x       FLOAT,                        -- Black Pill RMS of the alternating part, g (migration 015)
  vib_rms_y       FLOAT,
  vib_rms_z       FLOAT,
  vib_peak        FLOAT,                        -- Black Pill largest sample of the alternating part, g
  stm32_vib_x     FLOAT,                        -- Black Pill axis means, g
  stm32_vib_y     FLOAT,
  stm32_vib_z     FLOAT,
  nano_temp       FLOAT,                        -- Arduino Nano values forwarded by the hub (migration 015)
  nano_hum        FLOAT,
  nano_pres       FLOAT,
  nano_light      FLOAT,
  nano_moist      FLOAT,
  nano_water      BOOLEAN,
  vib_clipping    BOOLEAN,                      -- a sample reached the vibration sensor's limit (migration 021)
  anomaly_score   FLOAT,                        -- ML output, 0-1. NULL when the row lacked a feature and was not scored
  is_anomaly      BOOLEAN DEFAULT FALSE,
  recorded_at     TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  seq             BIGINT,                       -- the node's post counter (migration 012)
  device_ts       TIMESTAMP WITH TIME ZONE,     -- the node's own clock, when set (migration 012)
  quality         JSONB                         -- {"faults":{},"rejected":{},"dropped_health":[]} or NULL (migration 012)
);

CREATE INDEX idx_telemetry_device_recorded ON telemetry (device_id, recorded_at DESC);
```

All sensor columns are nullable - a device only reports the metrics its node type actually measures.

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
  resolved_at  TIMESTAMP,
  category     VARCHAR(20) NOT NULL DEFAULT 'machine',  -- machine or monitoring (migration 012)
  sensor_key   VARCHAR(50),                             -- the sensor a monitoring alert is about (migration 012)
  kind         VARCHAR(30)                              -- offline/reset_loop/unscored/sensor/clipping, NULL for rule alerts. One open alert per device, kind and sensor (migration 020)
);
```

### alert_rules and rule_states

`alert_rules` gains `for_seconds INTEGER` and `clear_margin DOUBLE PRECISION`, both NULL for the default (migration 029). `rule_states` holds one row for each rule while it is watched:

```sql
CREATE TABLE rule_states (
  rule_id      UUID PRIMARY KEY REFERENCES alert_rules(id) ON DELETE CASCADE,
  device_id    UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  breach_since TIMESTAMPTZ,   -- when the condition began to hold
  clear_since  TIMESTAMPTZ,   -- when the value came back inside the limit
  last_eval_at TIMESTAMPTZ    -- when a reading last carried the metric
);
```

`alerts` gains `occurrences INTEGER NOT NULL DEFAULT 1`, `last_value`, `peak_value`, `last_seen_at` and `notified_at` and two partial unique indexes: `uq_alerts_open_system` (one open alert of a kind and a sensor, per device, for every kind but `rule`) and `uq_alerts_open_rule` (one open `rule` alert per device and rule).

### device_health

One row per device with the latest vitals a node reported (migration 012).

```sql
CREATE TABLE device_health (
  device_id        UUID PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
  boot_count       INTEGER,
  uptime_s         INTEGER,
  reset_reason     VARCHAR(40),
  rssi             INTEGER,
  heap_free        INTEGER,
  firmware_version VARCHAR(50),
  last_seq         BIGINT,
  reported_at      TIMESTAMPTZ,
  faults           JSONB NOT NULL DEFAULT '{}',   -- sensor key -> state in the latest post
  lost_posts       BIGINT NOT NULL DEFAULT 0,     -- posts lost to gaps in seq
  last_gap_at      TIMESTAMPTZ,
  dropped_fields   BIGINT NOT NULL DEFAULT 0,     -- health fields dropped as unusable
  links            JSONB NOT NULL DEFAULT '{}',   -- latest serial link counters (migration 015)
  sensor_track     JSONB NOT NULL DEFAULT '{}',   -- per sensor fault timing the fault alerts run from (migration 015)
  diag             JSONB NOT NULL DEFAULT '{}',   -- the hub's latest bench counters (migration 028)
  board_mismatch   BOOLEAN NOT NULL DEFAULT FALSE,-- the firmware says its image does not match the board (migration 028)
  not_fitted_by_firmware JSONB NOT NULL DEFAULT '[]', -- sensor keys the firmware was built without (migration 028)
  boot_events      JSONB NOT NULL DEFAULT '[]'    -- ISO times of boots in the last hour
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
  password_hash          VARCHAR(255),                       -- NULL for accounts created through OAuth (migration 005)
  role                   VARCHAR(20) DEFAULT 'viewer',       -- admin/technician/viewer
  created_at             TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  last_login             TIMESTAMP WITH TIME ZONE,
  failed_login_attempts  INTEGER NOT NULL DEFAULT 0,         -- brute-force lockout counter (migration 002)
  locked_until           TIMESTAMP WITH TIME ZONE,           -- NULL = not locked (migration 002)
  -- OAuth + 2FA + RBAC columns (migration 005, 009)
  oauth_provider         VARCHAR(50),                        -- 'google' or 'github', NULL for password accounts
  oauth_id               VARCHAR(200),                       -- provider user ID
  phone_number           VARCHAR(30),                        -- optional, used for SMS alerts
  totp_secret            VARCHAR(64),                        -- TOTP shared secret (set when 2FA enabled)
  totp_enabled           BOOLEAN NOT NULL DEFAULT FALSE,     -- whether 2FA is active for this user
  permissions            JSONB,                               -- retired: nothing reads or sets it (migration 009)
  token_version          INTEGER NOT NULL DEFAULT 0,          -- raised to end every session for the user (migration 010)
  totp_last_step         BIGINT                               -- last accepted TOTP time step, so no code is accepted twice (migration 010)
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
