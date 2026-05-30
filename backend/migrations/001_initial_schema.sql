-- 001_initial_schema.sql
-- I number migrations so they run in a deterministic order and so it is obvious
-- at a glance how far a given environment has been migrated.
-- Run with: psql $DATABASE_URL -f migrations/001_initial_schema.sql


-- ---------------------------------------------------------------------------
-- devices
-- I use UUID PKs throughout because devices may be provisioned across multiple
-- regions before being synced to a central DB - integer sequences would collide.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    id               UUID PRIMARY KEY,
    name             VARCHAR(100) NOT NULL,
    location         VARCHAR(200),
    type             VARCHAR(50),
    -- api_key is the shared secret a physical node presents on every telemetry POST.
    -- I make it UNIQUE so a duplicate key cannot be registered by accident.
    api_key          VARCHAR(100) UNIQUE NOT NULL,
    status           VARCHAR(20) DEFAULT 'offline',
    last_seen        TIMESTAMP WITH TIME ZONE,
    firmware_version VARCHAR(20),
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- users
-- Stores human operators and API service accounts.
-- I use gen_random_uuid() as the default so rows inserted without an explicit
-- id still get a proper UUID without requiring application-side generation.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    name            VARCHAR(100),
    -- I store hashed_password rather than password - bcrypt hash goes here.
    hashed_password VARCHAR(255) NOT NULL,
    -- role controls what the UI shows and what API endpoints are accessible.
    -- Allowed values: 'admin', 'operator', 'viewer'
    role            VARCHAR(20) DEFAULT 'viewer',
    is_active       BOOLEAN DEFAULT TRUE,
    last_login      TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- telemetry
-- Central time-series table. Every sensor reading from every node lands here.
-- I include all v2 sensor columns even if a given node only populates a subset -
-- NULL means "sensor not present on this node", not "bad reading".
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telemetry (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id     UUID REFERENCES devices(id) ON DELETE CASCADE,
    -- node_type lets the ML pipeline segment training data by hardware variant.
    node_type     VARCHAR(20),
    -- Environmental sensors
    temperature   FLOAT,
    humidity      FLOAT,
    pressure      FLOAT,
    -- IMU - vibration accelerometer axes
    vibration_x   FLOAT,
    vibration_y   FLOAT,
    vibration_z   FLOAT,
    -- IMU - gyroscope axes
    gyro_x        FLOAT,
    gyro_y        FLOAT,
    gyro_z        FLOAT,
    -- Power monitoring (INA219)
    bus_voltage   FLOAT,
    current_ma    FLOAT,
    power_mw      FLOAT,
    -- Thermal imaging (MLX90614 contactless IR)
    ir_temperature FLOAT,
    -- Distance (VL53L0X ToF)
    distance_mm   FLOAT,
    -- Gas / air quality
    gas_level     FLOAT,
    gas_alert     BOOLEAN DEFAULT FALSE,
    -- Rotary encoder
    shaft_angle   FLOAT,
    shaft_rpm     FLOAT,
    -- Acoustic
    sound_level   FLOAT,
    -- Ambient light (BH1750 / LDR)
    light_level   FLOAT,
    -- Contact thermistor
    contact_temp  FLOAT,
    -- Soil / liquid moisture
    moisture_level FLOAT,
    water_detected BOOLEAN DEFAULT FALSE,
    -- Derived / computed fields populated by the ML pipeline
    fft_peak_hz   FLOAT,
    vib_magnitude FLOAT,
    anomaly_score FLOAT,
    is_anomaly    BOOLEAN DEFAULT FALSE,
    recorded_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- alert_rules
-- User-defined threshold rules evaluated server-side on each telemetry insert.
-- I keep rules in the DB rather than config files so operators can change them
-- via the UI without redeploying anything.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_rules (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id     UUID REFERENCES devices(id) ON DELETE CASCADE,
    -- sensor_field matches a column name in telemetry, e.g. "temperature"
    sensor_field  VARCHAR(50) NOT NULL,
    -- operator is one of: '>', '<', '>=', '<=', '=='
    operator      VARCHAR(10) NOT NULL,
    threshold     FLOAT NOT NULL,
    severity      VARCHAR(20) DEFAULT 'warning',
    -- message is the human-readable text shown in the UI and notifications.
    message       VARCHAR(255),
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- alerts
-- Each row is one fired alert event. I keep resolved alerts in the same table
-- (rather than archiving them) so we can query resolution time distributions.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id    UUID REFERENCES devices(id) ON DELETE CASCADE,
    -- rule_id is SET NULL on rule deletion so historic alerts are not lost.
    rule_id      UUID REFERENCES alert_rules(id) ON DELETE SET NULL,
    message      TEXT,
    severity     VARCHAR(20),
    resolved     BOOLEAN DEFAULT FALSE,
    triggered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at  TIMESTAMP WITH TIME ZONE
);


-- ---------------------------------------------------------------------------
-- tickets
-- Maintenance work items linked to a device and optionally to the alert that
-- triggered them. assigned_to and created_by reference users but are SET NULL
-- on user deletion to preserve the ticket history.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tickets (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id   UUID REFERENCES devices(id) ON DELETE SET NULL,
    alert_id    UUID REFERENCES alerts(id) ON DELETE SET NULL,
    title       VARCHAR(255) NOT NULL,
    description TEXT,
    -- status values: 'open', 'in_progress', 'resolved', 'closed'
    status      VARCHAR(20) DEFAULT 'open',
    -- priority values: 'low', 'medium', 'high', 'critical'
    priority    VARCHAR(20),
    assigned_to UUID REFERENCES users(id) ON DELETE SET NULL,
    created_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- audit_log
-- Append-only record of every state-changing API call. I use VARCHAR for
-- user_id and resource_id rather than UUID FKs so the table survives user
-- or resource deletion without orphan issues - the audit trail must be
-- immutable even when the referenced entities are gone.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     VARCHAR(255),
    action      VARCHAR(100) NOT NULL,
    resource    VARCHAR(100),
    resource_id VARCHAR(255),
    detail      TEXT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- Indexes
-- I create these after all tables are defined to keep the schema section clean.
-- Each index is justified by a specific query pattern in the application.
-- ---------------------------------------------------------------------------

-- telemetry is queried most often by device and by time, so both columns get indexes.
CREATE INDEX IF NOT EXISTS idx_telemetry_device_id   ON telemetry (device_id);
-- DESC because the dashboard always fetches the N most recent readings.
CREATE INDEX IF NOT EXISTS idx_telemetry_recorded_at ON telemetry (recorded_at DESC);
-- I index is_anomaly so the ML dashboard can filter anomalous rows without a full scan.
CREATE INDEX IF NOT EXISTS idx_telemetry_is_anomaly  ON telemetry (is_anomaly);

-- alerts are almost always filtered by device on the device detail page.
CREATE INDEX IF NOT EXISTS idx_alerts_device_id      ON alerts (device_id);
-- resolved is a low-cardinality boolean but the unresolved set is small, so a partial
-- index would be ideal here - using a plain index for simplicity until query plans
-- show a need to optimise further.
CREATE INDEX IF NOT EXISTS idx_alerts_resolved       ON alerts (resolved);

-- tickets are listed and filtered by status on the maintenance board.
CREATE INDEX IF NOT EXISTS idx_tickets_status        ON tickets (status);

-- audit_log is queried by user (compliance reports) and by time (recent activity feed).
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id     ON audit_log (user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at  ON audit_log (created_at DESC);
