-- migration 014: index on alert category for the alert list
-- the alert list is filtered by category and resolved state. Migration 012 used to build this index in a plain
-- CREATE INDEX, which blocks writes to alerts while it builds and rule alerts are written on every breaching
-- reading. It is built here with CONCURRENTLY instead, in the style of 011, so a live table keeps taking writes.
-- 013 was already taken by the ticket delete rules.
--
-- CONCURRENTLY cannot run inside a transaction block. `make migrate` and deploy.sh pipe each file to psql without
-- --single-transaction, so each statement below runs by itself.
--
-- an interrupted concurrent build leaves an INVALID index of the same name. IF NOT EXISTS would then skip it for
-- ever. The first statement finds such a leftover and drops it. \gexec runs what the query returns. On a healthy
-- database it returns no rows and does nothing.
SELECT format('DROP INDEX CONCURRENTLY IF EXISTS %I', c.relname)
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
WHERE c.relname = 'ix_alerts_category_resolved' AND NOT i.indisvalid \gexec

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_alerts_category_resolved
    ON alerts (category, resolved);
