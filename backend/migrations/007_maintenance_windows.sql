-- Migration 007: maintenance windows
-- I use IF NOT EXISTS guards so this migration is safe to rerun on a
-- partially migrated database without raising duplicate-object errors.

CREATE TABLE IF NOT EXISTS maintenance_windows (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- NULL device_id means the window applies to ALL devices in the fleet
    device_id       UUID REFERENCES devices(id) ON DELETE CASCADE,
    label           VARCHAR(200) NOT NULL,
    start_at        TIMESTAMPTZ NOT NULL,
    end_at          TIMESTAMPTZ NOT NULL,
    suppress_alerts BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_maintenance_windows_device_id
    ON maintenance_windows(device_id);

CREATE INDEX IF NOT EXISTS ix_maintenance_windows_start_end
    ON maintenance_windows(start_at, end_at);
