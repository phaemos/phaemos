# SQL Migrations

Alembic handles all schema migrations automatically. I only put files here for emergency manual fixes that cannot wait for a proper migration.

---

## When to use this folder

- Hotfix on a live database that needs to go out before the next release
- One-off data correction (e.g. backfilling a new column)
- Emergency rollback of a migration that went wrong

---

## Format

Name files with a timestamp and description: `2026-05-22-fix-alerts-resolved-column-type.sql`

Each file must include:
1. A header comment explaining what it does and when to run it
2. A transaction block with rollback on error
3. Notes on whether it is safe to run more than once (idempotent)

---

## See also

Alembic migration files live in `backend/alembic/versions/` (once Alembic is initialised).
