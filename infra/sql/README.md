# SQL

The SQL scripts live here. The API creates missing tables itself and the numbered files in `backend/migrations/` add the columns and indexes it does not (Alembic is installed but not used). This folder is for manual queries, seed data and emergency fixes only.

---

## Folder structure

```
sql/
├── roles/          The API's database role (app-role.sql) and its check, run by scripts/db-role.sh
├── migrations/     Emergency manual SQL fixes (normal migrations are in backend/migrations)
├── queries/        Useful analytical and operational queries
└── seed/           Demo and development seed data
```

---

## How to run queries

Connect to the database and run a query file:

```bash
# Local Docker stack
psql postgresql://postgres:password@localhost:5432/phaemos -f sql/queries/device-summary.sql

# Production droplet, through the database container
docker compose --env-file backend/.env -f infra/docker-compose.prod.yml exec -T db \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < infra/sql/queries/device-summary.sql
```

---

## Notes

- Never commit credentials in SQL files
- All files have a header comment explaining when and why to use them
- Seed files are for local development only - never run on production data
