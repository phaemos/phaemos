-- migration 037: indexes for keyset paging
-- GET /alerts and GET /telemetry/{device_id} page with `before=<time>,<id>`: the rows that sort after one row in the list's own
-- order (newest first, ties broken by id). These indexes have the same order, so the page is read straight off the index however
-- far back it is and no row is read and thrown away
--   alerts (device_id, triggered_at DESC, id DESC)  one machine's alerts
--   alerts (triggered_at DESC, id DESC)             every alert the caller may read
--   telemetry (device_id, recorded_at DESC, id DESC) one machine's readings (the existing idx_telemetry_device_time stays: the
--                                                     planner picks the one that fits and it is dropped in a later release)
-- built CONCURRENTLY, which cannot run in a transaction block: pipe the file to psql without --single-transaction. An interrupted
-- build leaves an INVALID index that IF NOT EXISTS would skip for ever, so those are dropped first
SET lock_timeout = '3s';

SELECT format('DROP INDEX CONCURRENTLY IF EXISTS %I', c.relname)
FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
WHERE c.relname IN ('ix_alerts_device_triggered_id', 'ix_alerts_triggered_id', 'ix_telemetry_device_time_id') AND NOT i.indisvalid \gexec

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_alerts_device_triggered_id ON alerts (device_id, triggered_at DESC, id DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_alerts_triggered_id ON alerts (triggered_at DESC, id DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_telemetry_device_time_id ON telemetry (device_id, recorded_at DESC, id DESC);
