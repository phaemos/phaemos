-- migration 021: vibration clipping
-- the vibration node says when a sample reached the sensor's limit. The reading is stored as a flag on the row and
-- the device keeps when it was last true, so one machine alert can stay open while it is true and resolve after a
-- minute without it. Every column is nullable or has a constant default, so nothing is rewritten. The lock timeout
-- makes it fail and be run again instead of queueing behind a long read. Safe to run twice and a re-run on a database that
-- is up to date takes no table lock: each ALTER is sent only when a catalogue check finds a column missing.
SET lock_timeout = '3s';

SELECT $q$
ALTER TABLE telemetry ADD COLUMN IF NOT EXISTS vib_clipping BOOLEAN
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'telemetry' AND column_name IN ('vib_clipping')
) < 1 \gexec

SELECT $q$
ALTER TABLE devices
    ADD COLUMN IF NOT EXISTS clipping_last_true TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS clipping_alerted   BOOLEAN NOT NULL DEFAULT FALSE
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'devices' AND column_name IN ('clipping_last_true', 'clipping_alerted')
) < 2 \gexec
