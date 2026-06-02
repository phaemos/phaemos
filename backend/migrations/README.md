# SQL Migrations

Plain SQL migrations. Apply in order when upgrading an existing database.
For a fresh install, `Base.metadata.create_all()` (via `make seed`) creates the full schema from the ORM models - you only need these files when adding columns to an existing database.

| File | Description |
| --- | --- |
| 001_initial_schema.sql | Full initial schema - all tables, indexes, v2 telemetry columns |
| 002_security_hardening.sql | Adds `failed_login_attempts` and `locked_until` to users |
| 003_multi_tenant.sql | Adds nullable `owner_id` FK on devices referencing users |

All scripts use `IF NOT EXISTS` / `IF EXISTS` guards and are safe to re-run.

Run manually on the live DB container:

```bash
docker exec phaemos-db-1 psql -U postgres -d phaemos -f /path/to/migration.sql
```

Or use `make migrate` (runs 001 on a fresh container).
