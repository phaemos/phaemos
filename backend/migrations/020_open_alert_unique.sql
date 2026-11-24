-- migration 020: one open system alert of a kind per device
-- two posts from one node handled at the same time could each open the same fault alert, leaving one that no state
-- would ever close. The application now serialises those changes per device and this index makes the database refuse
-- the second one as well.
--
-- kind says what a system alert is about: offline, reset_loop, unscored, sensor (with sensor_key) or clipping. Rule
-- and model alerts keep kind NULL and are not limited, because a rule that stays breached writes one alert per
-- reading by design. The key is the device, the kind and the sensor key and only for alerts still open.
--
-- three steps, none with a long lock:
--   1. the column. A nullable column with no default rewrites nothing. The lock timeout makes it fail and be run
--      again instead of queueing behind a long read
--   2. the kind of the monitoring alerts that exist already is worked out from their text and where a device holds
--      more than one open alert of one kind the newest is kept and each older one is resolved and says why
--   3. the unique index, built CONCURRENTLY in the style of 011 and 014, so alerts keep taking writes. It cannot run
--      inside a transaction block and `make migrate` and deploy.sh pipe each file to psql without
--      --single-transaction. A leftover invalid index of the same name from an interrupted build is dropped first.
--      If a new duplicate appears between steps 2 and 3 the build fails. Run the file again
SET lock_timeout = '3s';

SELECT $q$
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS kind VARCHAR(30)
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'alerts' AND column_name IN ('kind')
) < 1 \gexec

UPDATE alerts SET kind = CASE
        WHEN sensor_key IS NOT NULL THEN 'sensor'
        WHEN message LIKE '%has not reported for 2 minutes%' THEN 'offline'
        WHEN message LIKE '%has restarted 3 times in 10 minutes%' THEN 'reset_loop'
        WHEN message LIKE '%has had no scored reading for 10 minutes%' THEN 'unscored'
    END
WHERE category = 'monitoring' AND kind IS NULL;

UPDATE alerts SET resolved = TRUE,
                  resolved_at = now(),
                  message = message || ' (closed: a newer alert of the same kind was open)'
WHERE id IN (
    SELECT id FROM (
        SELECT id, row_number() OVER (
                   PARTITION BY device_id, kind, coalesce(sensor_key, '')
                   ORDER BY triggered_at DESC, id DESC
               ) AS newest
        FROM alerts
        WHERE kind IS NOT NULL AND kind <> 'rule' AND resolved IS NOT TRUE
    ) ranked
    WHERE newest > 1
);

SELECT format('DROP INDEX CONCURRENTLY IF EXISTS %I', c.relname)
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
WHERE c.relname = 'uq_alerts_open_kind' AND NOT i.indisvalid \gexec

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_alerts_open_kind
    ON alerts (device_id, kind, coalesce(sensor_key, ''))
    WHERE kind IS NOT NULL AND kind <> 'rule' AND resolved IS NOT TRUE;
