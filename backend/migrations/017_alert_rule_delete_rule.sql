-- migration 017: alerts.rule_id keeps the alert when its rule is deleted
-- migration 001 gave alerts.rule_id ON DELETE SET NULL. A database built by the API's create_all had no rule,
-- so deleting an alert rule that had ever fired failed with a foreign key error. Same method as migration 013:
-- change the key only when its rule is wrong, find it by its column whatever it is called and give up after
-- 5 seconds on a busy table instead of queueing everything behind it.

SET lock_timeout = '5s';

CREATE OR REPLACE FUNCTION pg_temp.ensure_fk_set_null(tbl text, col text, reftbl text) RETURNS void AS $$
DECLARE
    found boolean := false;
    wrong boolean := false;
    c record;
BEGIN
    FOR c IN
        SELECT con.conname, con.confdeltype
        FROM pg_constraint con
        JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY (con.conkey)
        WHERE con.contype = 'f'
          AND con.conrelid = to_regclass(tbl)
          AND a.attname = col
    LOOP
        found := true;
        IF c.confdeltype <> 'n' THEN
            wrong := true;
        END IF;
    END LOOP;
    IF found AND NOT wrong THEN
        RETURN;
    END IF;
    FOR c IN
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY (con.conkey)
        WHERE con.contype = 'f' AND con.conrelid = to_regclass(tbl) AND a.attname = col
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', tbl, c.conname);
    END LOOP;
    EXECUTE format(
        'ALTER TABLE %s ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES %s(id) ON DELETE SET NULL',
        tbl, tbl || '_' || col || '_fkey', col, reftbl
    );
END
$$ LANGUAGE plpgsql;

SELECT pg_temp.ensure_fk_set_null('alerts', 'rule_id', 'alert_rules');
