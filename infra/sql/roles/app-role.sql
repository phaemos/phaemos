-- the API's database login. Run by infra/scripts/db-role.sh as the database owner, through
-- psql inside the database container. Safe to run again: it first takes away EVERYTHING the
-- role holds (memberships, rights, owned objects, saved settings) and then gives back the four
-- rights it needs, so a role that was changed by hand or by an attacker, ends up the same as
-- a new one. Everything is one transaction: a failure leaves the old state in place.
--
-- the role can connect, use the public schema and read and write the tables and sequences
-- that are in it. It cannot create anything, own anything, run a program, read a file, make a
-- role, create a large object or touch another database. Tables made later by the migrations
-- or by the schema job are covered by the default privileges at the bottom, because the owner
-- makes them.
--
-- every value comes from the container's environment through \getenv, so the password is
-- on no command line and in no file.

\set ON_ERROR_STOP on

\getenv app_user POSTGRES_APP_USER
\getenv app_pw POSTGRES_APP_PASSWORD
\getenv owner_user POSTGRES_USER
\getenv db_name POSTGRES_DB

-- stop at once on an empty value or on a role that would be the owner itself. The division
-- RAISE EXCEPTION is the way to fail a psql script with an exit code and a message
SELECT (:'app_user' = '' OR :'app_pw' = '' OR :'app_user' = :'owner_user') AS bad \gset
\if :bad
    DO $$ BEGIN RAISE EXCEPTION 'POSTGRES_APP_USER and POSTGRES_APP_PASSWORD must be set and the user must not be POSTGRES_USER'; END $$;
\endif

BEGIN;

-- an earlier name for the role (POSTGRES_APP_USER was changed) keeps its login and its rights
-- unless it is closed here. The comment on the role is how this script finds its own roles.
SELECT format('ALTER ROLE %I NOLOGIN', rolname)
FROM pg_roles
WHERE shobj_description(oid, 'pg_authid') = 'phaemos application role' AND rolname <> :'app_user'
\gexec
SELECT format('DROP OWNED BY %I', rolname)
FROM pg_roles
WHERE shobj_description(oid, 'pg_authid') = 'phaemos application role' AND rolname <> :'app_user'
\gexec

-- the role: no superuser, no database or role creation, no replication, no row security bypass
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

-- take back everything a changed role could hold. Order matters:
--  1. memberships (pg_execute_server_program and every other role it was put in)
SELECT format('REVOKE %I FROM %I', r.rolname, m.rolname)
FROM pg_auth_members am
JOIN pg_roles r ON r.oid = am.roleid
JOIN pg_roles m ON m.oid = am.member
WHERE m.rolname = :'app_user'
\gexec
--  2. objects it owns move to the owner (nothing is dropped) and then every right it was
--     given, on tables, schemas, the database and as a default, is removed
SELECT format('REASSIGN OWNED BY %I TO %I', :'app_user', :'owner_user') \gexec
SELECT format('DROP OWNED BY %I', :'app_user') \gexec
--  3. saved settings, such as a search_path or a read-only default set by the role itself
SELECT format('ALTER ROLE %I RESET ALL', :'app_user') \gexec
SELECT format('ALTER ROLE %I IN DATABASE %I RESET ALL', :'app_user', :'db_name') \gexec

-- the 20 connections: the API's pool opens at most 15 and the server allows 30, so 20 leaves
-- room for the owner's own sessions. A connection flood from the API cannot starve a backup.
SELECT format(
    'ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT CONNECTION LIMIT 20',
    :'app_user', :'app_pw')
\gexec
SELECT format('COMMENT ON ROLE %I IS %L', :'app_user', 'phaemos application role') \gexec

-- nobody but the owner may connect and the role may connect to this database only. The
-- revoke also takes TEMPORARY away from everyone else. The two maintenance databases are
-- closed to everyone who is not a superuser, so the role cannot even sign in to them
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db_name') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'db_name', :'app_user') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', datname)
FROM pg_database WHERE datname IN ('postgres', 'template1') AND datname <> :'db_name'
\gexec

-- nobody may create objects in the public schema (the default since PostgreSQL 15, stated
-- here so an older database gets it too). The role may look things up in it
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app_user') \gexec

-- large objects. Any role may make one with lo_from_bytea and one that exists blocks a
-- restore (the dump then fails on a duplicate key). Nothing in the application uses them, so
-- the functions that make one are closed to everyone but a superuser. This is a right on
-- the system catalogue, so it outlasts a restore that drops the public schema
REVOKE EXECUTE ON FUNCTION lo_create(oid), lo_creat(integer), lo_from_bytea(oid, bytea) FROM PUBLIC;

-- what exists now. A restore drops and recreates the schema, so this runs after one too
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', :'app_user') \gexec
SELECT format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', :'app_user') \gexec

-- what the owner makes from now on
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
              :'owner_user', :'app_user') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO %I',
              :'owner_user', :'app_user') \gexec

-- the record of applied migrations. The role has no business reading or changing it: a
-- changed hash there would let a migration run again or hide that a file was edited. It is
-- made here, after the grants above, so the default privileges did not reach it
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   text PRIMARY KEY,
    sha256     text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
SELECT format('REVOKE ALL ON TABLE schema_migrations FROM %I', :'app_user') \gexec

COMMIT;
