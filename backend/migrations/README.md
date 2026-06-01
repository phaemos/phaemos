# Alembic Migrations

SQL migrations managed by Alembic. Applied automatically on Render deploy via `alembic upgrade head`.

| File | Description |
|---|---|
| 001_initial_schema.sql | Full initial schema - all tables, types, indexes |

Run locally: `alembic upgrade head` (requires DATABASE_URL in environment)
