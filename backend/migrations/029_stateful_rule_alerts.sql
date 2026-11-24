-- migration 029: stateful rule alerts
-- a rule used to write a new alert row for every reading that breached it (one every 5 seconds for as long as the breach
-- lasted). A rule alert is now one row while its condition lasts, updated in place and the database refuses a second open
-- one for the same machine and rule. This file:
--   1. adds the columns a rule alert keeps (occurrences, last and peak value, when a reading last met the condition and when
--      people were last told) and the hold and margin on a rule
--   2. creates the small table that lets a rule wait out its hold between posts without a row for every reading
--   3. moves the unique index for system alerts to one that leaves rule alerts out (a machine may have several rules and
--      each has its own alert), creating the new index before the old one is dropped
--   4. collapses the open duplicate rule alerts into one per machine and rule: the OLDEST row is kept (so the alert keeps its
--      true start time) and given kind 'rule', the count of the rows, the newest row's value as last_value, the most extreme
--      value as peak_value and the newest row's time as last_seen_at. Every other open row of that machine and rule is
--      resolved and its message says it was merged. Nothing is deleted
--   5. the unique index for rule alerts, built after the collapse
-- every step is sent only when a catalogue check says it is needed, so a re-run on a database that is up to date takes no
-- table lock at all (psql's \gexec runs what a check returns, so the file goes through psql). The indexes are built
-- CONCURRENTLY, which cannot run in a transaction block: deploy.sh pipes each file to psql without --single-transaction. If a
-- new duplicate appears between the collapse and the last index the build fails and the file can be run again.
SET lock_timeout = '3s';

SELECT $q$
ALTER TABLE alerts
    ADD COLUMN IF NOT EXISTS occurrences  INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS last_value   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS peak_value   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS notified_at  TIMESTAMPTZ
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'alerts'
      AND column_name IN ('occurrences', 'last_value', 'peak_value', 'last_seen_at', 'notified_at')
) < 5 \gexec

SELECT $q$
ALTER TABLE alert_rules
    ADD COLUMN IF NOT EXISTS for_seconds  INTEGER,
    ADD COLUMN IF NOT EXISTS clear_margin DOUBLE PRECISION
$q$
WHERE (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'alert_rules' AND column_name IN ('for_seconds', 'clear_margin')
) < 2 \gexec

CREATE TABLE IF NOT EXISTS rule_states (
    rule_id      UUID PRIMARY KEY REFERENCES alert_rules(id) ON DELETE CASCADE,
    device_id    UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    breach_since TIMESTAMPTZ,
    clear_since  TIMESTAMPTZ,
    last_eval_at TIMESTAMPTZ
);

-- an interrupted concurrent build leaves an INVALID index of the same name, which IF NOT EXISTS would then skip for ever
SELECT format('DROP INDEX CONCURRENTLY IF EXISTS %I', c.relname)
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
WHERE c.relname IN ('uq_alerts_open_system', 'uq_alerts_open_rule') AND NOT i.indisvalid \gexec

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_alerts_open_system
    ON alerts (device_id, kind, coalesce(sensor_key, ''))
    WHERE kind IS NOT NULL AND kind <> 'rule' AND resolved IS NOT TRUE;

-- the index from migration 020 treated every kind alike, so two rules on one machine would have clashed on it
SELECT 'DROP INDEX CONCURRENTLY IF EXISTS uq_alerts_open_kind'
WHERE EXISTS (SELECT 1 FROM pg_class WHERE relname = 'uq_alerts_open_kind' AND relkind = 'i') \gexec

SELECT $q$
WITH open_rows AS (
    SELECT a.id, a.device_id, a.rule_id, a.triggered_at, r.condition,
           substring(a.message from 'is (-?[0-9][0-9.eE+-]*) \(')::double precision AS v
    FROM alerts a
    JOIN alert_rules r ON r.id = a.rule_id
    WHERE a.rule_id IS NOT NULL AND a.kind IS NULL AND a.resolved IS NOT TRUE
), ranked AS (
    SELECT *, row_number() OVER (PARTITION BY device_id, rule_id ORDER BY triggered_at ASC, id ASC) AS oldest_rank
    FROM open_rows
), totals AS (
    SELECT device_id, rule_id,
           count(*) AS n,
           max(triggered_at) AS newest_at,
           (array_agg(v ORDER BY triggered_at DESC, id DESC))[1] AS last_v,
           CASE WHEN bool_and(condition = 'lt') THEN min(v) ELSE max(v) END AS peak
    FROM open_rows
    GROUP BY device_id, rule_id
), merged AS (
    UPDATE alerts a
    SET kind = 'rule', occurrences = t.n, last_value = t.last_v, peak_value = t.peak, last_seen_at = t.newest_at
    FROM ranked k
    JOIN totals t ON t.device_id = k.device_id AND t.rule_id = k.rule_id
    WHERE a.id = k.id AND k.oldest_rank = 1
    RETURNING a.id
), closed AS (
    UPDATE alerts a
    SET resolved = TRUE, resolved_at = now(),
        message = a.message || ' (closed: merged into one alert for this rule)'
    FROM ranked k
    WHERE a.id = k.id AND k.oldest_rank > 1
    RETURNING a.id
)
SELECT (SELECT count(*) FROM merged) AS alerts_kept, (SELECT count(*) FROM closed) AS duplicates_closed
$q$
WHERE EXISTS (
    SELECT 1 FROM alerts WHERE rule_id IS NOT NULL AND kind IS NULL AND resolved IS NOT TRUE
) \gexec

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_alerts_open_rule
    ON alerts (device_id, rule_id)
    WHERE kind = 'rule' AND resolved IS NOT TRUE;
