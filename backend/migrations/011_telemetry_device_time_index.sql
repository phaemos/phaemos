-- migration 011: composite index for per-device time-range reads on telemetry
-- the history, export, bucketed and anomaly reads filter on device_id and a recorded_at
-- range, newest first. The single-column indexes from 001 cannot serve that together.
--
-- CONCURRENTLY keeps writes from device ingest flowing while the index builds. It cannot
-- run inside a transaction block, which is fine because `make migrate` and deploy.sh pipe
-- each file to psql without --single-transaction, so each statement below runs by itself.
--
-- an interrupted concurrent build leaves an INVALID index of the same name. IF NOT EXISTS
-- would then skip it for ever. The first statement finds such a leftover and drops it.
-- \gexec runs what the query returns. On a healthy database it returns no rows and does nothing.
SELECT format('DROP INDEX CONCURRENTLY IF EXISTS %I', c.relname)
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
WHERE c.relname = 'idx_telemetry_device_time' AND NOT i.indisvalid \gexec

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_telemetry_device_time
    ON telemetry (device_id, recorded_at DESC);
