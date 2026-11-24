-- migration 015: sensor fault alerts, serial link values and the satellites' readings
-- adds what the fault alerts keep (per sensor timing and link counters on device_health), the devices columns for
-- sensors that are not fitted and for the no-scored-reading alert and the telemetry columns for the six values the
-- hub already posts from the Arduino Nano and the seven it forwards from the Black Pill.
-- safe to run twice and a re-run on a database that is up to date takes no table lock at all: each ALTER TABLE is sent
-- only when a catalogue check finds a column missing (psql's \gexec runs what the check returns, so the file goes through
-- psql). A lock that cannot be had in three seconds fails the file and it can be run again.
SET lock_timeout = '3s';

-- one statement, so the telemetry table is locked once. Every column is nullable with no default, so nothing is
-- rewritten
SELECT $q$
ALTER TABLE telemetry
    ADD COLUMN IF NOT EXISTS nano_temp   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS nano_hum    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS nano_pres   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS nano_light  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS nano_moist  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS nano_water  BOOLEAN,
    ADD COLUMN IF NOT EXISTS vib_rms_x   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS vib_rms_y   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS vib_rms_z   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS vib_peak    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS stm32_vib_x DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS stm32_vib_y DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS stm32_vib_z DOUBLE PRECISION
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'telemetry' AND column_name IN ('nano_temp', 'nano_hum', 'nano_pres', 'nano_light', 'nano_moist', 'nano_water', 'vib_rms_x', 'vib_rms_y', 'vib_rms_z', 'vib_peak', 'stm32_vib_x', 'stm32_vib_y', 'stm32_vib_z')
) < 13 \gexec

-- the latest serial link counters and the timing the sensor fault alerts run from
SELECT $q$
ALTER TABLE device_health
    ADD COLUMN IF NOT EXISTS links        JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS sensor_track JSONB NOT NULL DEFAULT '{}'::jsonb
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'device_health' AND column_name IN ('links', 'sensor_track')
) < 2 \gexec

-- sensor keys that are not expected on a machine and the state behind the no-scored-reading alert
SELECT $q$
ALTER TABLE devices
    ADD COLUMN IF NOT EXISTS not_fitted       TEXT[]      NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS unscored_since   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS unscored_missing TEXT[]      NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS unscored_alerted BOOLEAN     NOT NULL DEFAULT FALSE
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'devices' AND column_name IN ('not_fitted', 'unscored_since', 'unscored_missing', 'unscored_alerted')
) < 4 \gexec
