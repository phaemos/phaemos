-- migration 012: node health, link state and monitoring alerts
-- nodes now send optional health fields with each reading (a post counter, boot count, uptime, a map of faulted
-- sensors and a few vitals). The backend keeps them with the reading, keeps the latest vitals per device, tells
-- a silent node from a quiet machine and separates alerts about the machine from alerts about its monitoring.
-- every statement is safe to run twice and a re-run on a database that is up to date takes no table lock at all: each
-- ALTER TABLE is sent only when a catalogue check finds a column missing (psql's \gexec runs what the check returns, so the
-- file goes through psql). An ALTER takes its lock before it notices the columns exist, which is why the check comes first.

-- an ALTER that cannot get its lock within three seconds fails and can be run again, instead of queueing behind a
-- long read and holding up every insert behind it. The setting lasts for this session only
SET lock_timeout = '3s';

-- per reading: the node's post counter, the time from its own clock and the fault record for that reading.
-- quality holds {"faults": {sensor: state}, "rejected": {field: value}} and is NULL when nothing was wrong
-- one statement, so the table is locked once and not three times
SELECT $q$
ALTER TABLE telemetry
    ADD COLUMN IF NOT EXISTS seq       BIGINT,
    ADD COLUMN IF NOT EXISTS device_ts TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS quality   JSONB
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'telemetry' AND column_name IN ('seq', 'device_ts', 'quality')
) < 3 \gexec

-- the latest vitals per device. One row, replaced by each post that carries health fields
CREATE TABLE IF NOT EXISTS device_health (
    device_id        UUID PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    boot_count       INTEGER,
    uptime_s         INTEGER,
    reset_reason     VARCHAR(40),
    rssi             INTEGER,
    heap_free        INTEGER,
    firmware_version VARCHAR(50),
    last_seq         BIGINT,
    reported_at      TIMESTAMPTZ,
    -- sensor key -> state for the faulted sensors in the latest post. {} when all was well
    faults           JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- posts lost to gaps in the sequence number and when the latest gap was seen
    lost_posts       BIGINT NOT NULL DEFAULT 0,
    last_gap_at      TIMESTAMPTZ,
    -- health fields a node sent that were out of bounds or malformed. They are dropped and the reading is kept
    dropped_fields   BIGINT NOT NULL DEFAULT 0,
    -- ISO times of the boots seen in the last hour. A restart loop is three of them inside ten minutes
    boot_events      JSONB NOT NULL DEFAULT '[]'::jsonb
);

-- a table made by an earlier run of this file gets the column too
SELECT $q$
ALTER TABLE device_health ADD COLUMN IF NOT EXISTS dropped_fields BIGINT NOT NULL DEFAULT 0
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'device_health' AND column_name IN ('dropped_fields')
) < 1 \gexec

-- how often a node posts and the state its last post's age puts it in: online, late or offline.
-- Existing devices start as offline. The liveness sweep corrects every one of them within a quarter of a minute
-- of the API starting and a post sets online at once
SELECT $q$
ALTER TABLE devices
    ADD COLUMN IF NOT EXISTS expected_interval_s INTEGER     NOT NULL DEFAULT 5,
    ADD COLUMN IF NOT EXISTS link_state          VARCHAR(10) NOT NULL DEFAULT 'offline'
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'devices' AND column_name IN ('expected_interval_s', 'link_state')
) < 2 \gexec

-- machine alerts are about the machine. Monitoring alerts are about the way it is watched (a silent node, a restart
-- loop). Every existing alert is a machine alert
SELECT $q$
ALTER TABLE alerts
    ADD COLUMN IF NOT EXISTS category   VARCHAR(20) NOT NULL DEFAULT 'machine',
    ADD COLUMN IF NOT EXISTS sensor_key VARCHAR(50)
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'alerts' AND column_name IN ('category', 'sensor_key')
) < 2 \gexec

-- the index on alerts (category, resolved) is built by migration 014 without blocking writes
