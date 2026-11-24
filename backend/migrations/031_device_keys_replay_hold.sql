-- migration 031: hashed device keys, replay protection, the stuck sensor state and the rule hold figures
-- 1. a device key is no longer stored. A machine is found by key_id (the first 8 characters of its key, which are not secret on
--    their own) and the key itself is checked against key_hash, a keyed hash made by the application. Existing keys are given
--    their key_id here. Their hashes need the server's secret key, which SQL does not have, so the application hashes each
--    one (and empties its old clear column) when it starts or when that machine next posts. Nothing has to be re-issued.
--    Run it twice and nothing changes: every step is sent only when a catalogue check says it is needed
-- 2. replay protection: the (boot, seq) pair of the last post accepted, whether the machine has ever sent the pair and a count
--    of posts refused for an old pair
-- 3. the stuck sensor state per machine
-- 4. what a rule's readings added up to before its alert was raised (count and peak) and when the condition first held, so the
--    alert covers the qualifying period as well
-- the unique index is built CONCURRENTLY, which cannot run in a transaction block: pipe the file to psql without --single-transaction
SET lock_timeout = '3s';

SELECT $q$
ALTER TABLE devices
    ADD COLUMN IF NOT EXISTS key_id            VARCHAR(16),
    ADD COLUMN IF NOT EXISTS key_hash          VARCHAR(64),
    ADD COLUMN IF NOT EXISTS last_boot         BIGINT,
    ADD COLUMN IF NOT EXISTS last_seq          BIGINT,
    ADD COLUMN IF NOT EXISTS replay_protected  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS replay_refused    INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS replay_refused_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS stuck_state       JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS counter_jump_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS counter_jump_note VARCHAR(120)
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'devices'
      AND column_name IN ('key_id', 'key_hash', 'last_boot', 'last_seq', 'replay_protected', 'replay_refused',
                          'replay_refused_at', 'stuck_state', 'counter_jump_at', 'counter_jump_note')
) < 10 \gexec

-- the old clear column may be empty once a key is hashed
SELECT 'ALTER TABLE devices ALTER COLUMN api_key DROP NOT NULL'
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'devices' AND column_name = 'api_key' AND is_nullable = 'NO'
) \gexec

SELECT 'UPDATE devices SET key_id = left(api_key, 8) WHERE key_id IS NULL AND api_key IS NOT NULL'
WHERE EXISTS (SELECT 1 FROM devices WHERE key_id IS NULL AND api_key IS NOT NULL) \gexec

-- an interrupted concurrent build leaves an INVALID index of the same name, which IF NOT EXISTS would then skip for ever
SELECT 'DROP INDEX CONCURRENTLY IF EXISTS uq_devices_key_id'
WHERE EXISTS (
    SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = 'uq_devices_key_id' AND NOT i.indisvalid
) \gexec

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_devices_key_id ON devices (key_id) WHERE key_id IS NOT NULL;

SELECT $q$
ALTER TABLE rule_states
    ADD COLUMN IF NOT EXISTS hold_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS hold_peak  DOUBLE PRECISION
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'rule_states' AND column_name IN ('hold_count', 'hold_peak')
) < 2 \gexec

SELECT 'ALTER TABLE alerts ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ, ADD COLUMN IF NOT EXISTS evidence JSONB'
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'alerts' AND column_name IN ('first_seen_at', 'evidence')
) < 2 \gexec
