-- read-only check of the API's database login, run by `db-role.sh --check`. Every wrong
-- state raises an error, so psql exits non-zero and deploy.sh stops. It looks for what the
-- role holds beyond the four rights it needs, which is also what an attacker with a way to
-- change the role would have added.
\set ON_ERROR_STOP on

\getenv app_user POSTGRES_APP_USER
\getenv owner_user POSTGRES_USER

-- shown for the log: the role and its attributes
SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, rolcanlogin
FROM pg_roles WHERE rolname = :'app_user';

-- the role must exist, may sign in and must carry none of the powers that would let it
-- leave the database
SELECT NOT EXISTS (SELECT 1 FROM pg_roles
                   WHERE rolname = :'app_user' AND rolcanlogin
                     AND NOT (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls)) AS bad \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role is missing or holds a dangerous attribute'; END $$;
\endif

-- no memberships at all: pg_execute_server_program, pg_read_server_files, pg_write_server_files
-- and the rest all arrive this way
SELECT count(*) > 0 AS bad FROM pg_auth_members am JOIN pg_roles m ON m.oid = am.member WHERE m.rolname = :'app_user' \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role is a member of another role'; END $$;
\endif

-- no other login that is a superuser and no login at all but the owner and this role
SELECT count(*) > 0 AS bad FROM pg_roles
WHERE (rolsuper OR rolcanlogin) AND rolname NOT IN (:'owner_user', :'app_user') \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'another role can sign in or is a superuser besides the owner and the application role'; END $$;
\endif

-- every table in the public schema must be readable and writable by the role, except the
-- record of migrations, which it must not touch at all
SELECT count(*) > 0 AS bad
FROM pg_tables
WHERE schemaname = 'public' AND tablename <> 'schema_migrations'
  AND NOT (has_table_privilege(:'app_user', format('%I.%I', schemaname, tablename), 'SELECT')
       AND has_table_privilege(:'app_user', format('%I.%I', schemaname, tablename), 'INSERT')
       AND has_table_privilege(:'app_user', format('%I.%I', schemaname, tablename), 'UPDATE')
       AND has_table_privilege(:'app_user', format('%I.%I', schemaname, tablename), 'DELETE')) \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'a table in the public schema lacks rights for the application role'; END $$;
\endif
SELECT count(*) > 0 AS bad FROM pg_class c
WHERE c.relname = 'schema_migrations' AND c.relnamespace = 'public'::regnamespace
  AND (has_table_privilege(:'app_user', c.oid, 'SELECT') OR has_table_privilege(:'app_user', c.oid, 'INSERT')
       OR has_table_privilege(:'app_user', c.oid, 'UPDATE') OR has_table_privilege(:'app_user', c.oid, 'DELETE')) \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role may touch the record of applied migrations'; END $$;
\endif

-- no right on any table, view or sequence beyond the four, anywhere: TRUNCATE, REFERENCES,
-- TRIGGER and any grant option all show up as an extra entry in the ACL
SELECT count(*) > 0 AS bad
FROM pg_class c, aclexplode(c.relacl) a
WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f') AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = :'app_user')
  AND (a.privilege_type NOT IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE') OR a.is_grantable) \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role holds a table right beyond select, insert, update and delete'; END $$;
\endif
SELECT count(*) > 0 AS bad
FROM pg_class c, aclexplode(c.relacl) a
WHERE c.relkind = 'S' AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = :'app_user')
  AND (a.privilege_type NOT IN ('USAGE', 'SELECT') OR a.is_grantable) \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role holds a sequence right beyond usage and select'; END $$;
\endif

-- rights on the database and on the schemas: connect only and no create anywhere
SELECT has_database_privilege(:'app_user', current_database(), 'CREATE')
    OR has_database_privilege(:'app_user', current_database(), 'TEMPORARY') AS bad \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role may create in the database or make temporary tables'; END $$;
\endif
SELECT count(*) > 0 AS bad FROM pg_namespace n
WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
  AND has_schema_privilege(:'app_user', n.oid, 'CREATE') \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role may create objects in a schema'; END $$;
\endif
SELECT count(*) > 0 AS bad
FROM pg_database d, aclexplode(d.datacl) a
WHERE d.datname = current_database() AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = :'app_user')
  AND (a.privilege_type <> 'CONNECT' OR a.is_grantable) \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role holds a database right beyond connect'; END $$;
\endif

-- the role must own nothing: an owner can change the structure and grant itself anything.
-- pg_shdepend lists every object of every kind (schemas, functions, types, sequences and
-- more), not only tables
SELECT count(*) > 0 AS bad FROM pg_shdepend s
WHERE s.refclassid = 'pg_authid'::regclass AND s.deptype = 'o'
  AND s.refobjid = (SELECT oid FROM pg_roles WHERE rolname = :'app_user') \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role owns an object, which it must not'; END $$;
\endif

-- no default privilege that hands the role more than the four on tables or sequences and
-- none on functions, types or schemas
SELECT count(*) > 0 AS bad
FROM pg_default_acl d, aclexplode(d.defaclacl) a
WHERE a.grantee = (SELECT oid FROM pg_roles WHERE rolname = :'app_user')
  AND NOT ((d.defaclobjtype = 'r' AND a.privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE'))
        OR (d.defaclobjtype = 'S' AND a.privilege_type IN ('USAGE', 'SELECT'))) \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role has a default privilege beyond the four'; END $$;
\endif

-- saved settings (search_path, default_transaction_read_only, statement_timeout and the
-- rest) are written by the role itself and survive a restart: the role must hold none
SELECT count(*) > 0 AS bad FROM pg_roles WHERE rolname = :'app_user' AND rolconfig IS NOT NULL \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role carries saved settings'; END $$;
\endif
SELECT count(*) > 0 AS bad FROM pg_db_role_setting s
WHERE s.setrole = (SELECT oid FROM pg_roles WHERE rolname = :'app_user') \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role carries saved settings for a database'; END $$;
\endif

-- the functions that make a large object are closed
SELECT has_function_privilege(:'app_user', 'lo_from_bytea(oid, bytea)', 'EXECUTE')
    OR has_function_privilege(:'app_user', 'lo_create(oid)', 'EXECUTE')
    OR has_function_privilege(:'app_user', 'lo_creat(integer)', 'EXECUTE') AS bad \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'the application role may create a large object'; END $$;
\endif
