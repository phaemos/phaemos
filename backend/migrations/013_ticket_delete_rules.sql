-- migration 013: delete rules on the tickets foreign keys
-- migration 001 created these four with ON DELETE SET NULL so a ticket outlives the machine, alert or person it
-- names. A database built by the API's create_all had them without any rule, so deleting a user who was assigned
-- a ticket failed.
--
-- deploy.sh and `make migrate` run every file on every deploy, so this file only changes a key when its delete
-- rule is not already SET NULL. A database that is right is only read and no lock is taken. A key under another
-- name is found by its column and replaced. lock_timeout makes a change that has to wait for a busy table give up
-- after 5 seconds and fail the deploy with a clear error, instead of queueing every other statement behind it.
-- no psql meta commands and no CONCURRENTLY.

SET lock_timeout = '5s';

-- a temporary function lives only for this session. It looks up every foreign key on one column and drops and
-- re-adds them only when one has a delete rule other than SET NULL (confdeltype 'n') or when there is none.
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

SELECT pg_temp.ensure_fk_set_null('tickets', 'device_id',   'devices');
SELECT pg_temp.ensure_fk_set_null('tickets', 'alert_id',    'alerts');
SELECT pg_temp.ensure_fk_set_null('tickets', 'assigned_to', 'users');
SELECT pg_temp.ensure_fk_set_null('tickets', 'created_by',  'users');
