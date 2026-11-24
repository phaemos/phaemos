-- migration 028: model alerts under the open-alert index, resolved never NULL, firmware diagnostics and board checks
-- three things, each sent only when a catalogue check says it is needed, so a re-run on a database that is up to date takes
-- no table lock at all (psql's \gexec runs what a check returns, so the file goes through psql):
--   1. the columns on device_health for the hub's bench counters, its board check and the sensors its firmware was built
--      without
--   2. the model's own alerts get a kind, so the unique index from migration 020 covers them too. Where a device holds more
--      than one open model alert the newest is kept and each older one is resolved and says why. (The model alert is the
--      one whose message starts "Anomaly detected" and which has no rule)
--   3. alerts.resolved becomes NOT NULL with a default of false. A NULL counted as open for the unique index and as not open for
--      every lookup, so no row may hold one. The change is made in steps that hold no long lock: a CHECK added NOT VALID (a
--      brief lock), validated (which blocks nothing), then SET NOT NULL, which uses the validated check and does not scan the
--      table. If a NULL is written between the backfill and the validation the validation fails: run the file again
SET lock_timeout = '3s';

SELECT $q$
ALTER TABLE device_health
    ADD COLUMN IF NOT EXISTS diag                   JSONB   NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS board_mismatch         BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS not_fitted_by_firmware JSONB   NOT NULL DEFAULT '[]'::jsonb
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'device_health'
      AND column_name IN ('diag', 'board_mismatch', 'not_fitted_by_firmware')
) < 3 \gexec

SELECT $q$
UPDATE alerts SET resolved = TRUE,
                  resolved_at = now(),
                  message = message || ' (closed: a newer alert of the same kind was open)'
WHERE id IN (
    SELECT id FROM (
        SELECT id, row_number() OVER (PARTITION BY device_id ORDER BY triggered_at DESC, id DESC) AS newest
        FROM alerts
        WHERE kind IS NULL AND rule_id IS NULL AND resolved IS NOT TRUE AND message LIKE 'Anomaly detected%'
    ) ranked
    WHERE newest > 1
)
$q$
WHERE EXISTS (SELECT 1 FROM alerts WHERE kind IS NULL AND rule_id IS NULL AND message LIKE 'Anomaly detected%') \gexec

SELECT $q$ UPDATE alerts SET kind = 'anomaly' WHERE kind IS NULL AND rule_id IS NULL AND message LIKE 'Anomaly detected%' $q$
WHERE EXISTS (SELECT 1 FROM alerts WHERE kind IS NULL AND rule_id IS NULL AND message LIKE 'Anomaly detected%') \gexec

SELECT $q$ UPDATE alerts SET resolved = FALSE WHERE resolved IS NULL $q$
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'alerts' AND column_name = 'resolved' AND is_nullable = 'YES'
) \gexec

SELECT $q$ ALTER TABLE alerts ADD CONSTRAINT alerts_resolved_not_null CHECK (resolved IS NOT NULL) NOT VALID $q$
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'alerts' AND column_name = 'resolved' AND is_nullable = 'YES'
) AND NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'alerts_resolved_not_null' AND conrelid = 'alerts'::regclass
) \gexec

SELECT $q$ ALTER TABLE alerts VALIDATE CONSTRAINT alerts_resolved_not_null $q$
WHERE EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'alerts_resolved_not_null' AND conrelid = 'alerts'::regclass AND NOT convalidated
) \gexec

SELECT $q$ ALTER TABLE alerts ALTER COLUMN resolved SET NOT NULL, ALTER COLUMN resolved SET DEFAULT FALSE $q$
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'alerts' AND column_name = 'resolved' AND is_nullable = 'YES'
) AND EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'alerts_resolved_not_null' AND conrelid = 'alerts'::regclass AND convalidated
) \gexec

SELECT $q$ ALTER TABLE alerts DROP CONSTRAINT alerts_resolved_not_null $q$
WHERE EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'alerts_resolved_not_null' AND conrelid = 'alerts'::regclass
) AND EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'alerts' AND column_name = 'resolved' AND is_nullable = 'NO'
) \gexec
