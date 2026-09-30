# SQL

I keep all SQL scripts here. Alembic handles schema migrations automatically - this folder is for manual queries, seed data and emergency fixes only.

---

## Folder structure

```
sql/
├── migrations/     Emergency manual SQL fixes (Alembic handles normal migrations)
├── queries/        Useful analytical and operational queries
└── seed/           Demo and development seed data
```

---

## How to run queries

Connect to the database and run a query file:

```bash
# Local Docker stack
psql postgresql://postgres:password@localhost:5432/phaemos -f sql/queries/device-summary.sql

# Production (Render)
psql $DATABASE_URL -f sql/queries/device-summary.sql
```

---

## Notes

- Never commit credentials in SQL files
- All files have a first-person header comment explaining when and why to use them
- Seed files are for local development only - never run on production data
