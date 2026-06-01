# Background Tasks

APScheduler jobs started via the FastAPI lifespan context manager in main.py.

| File | Schedule | Purpose |
|---|---|---|
| retention.py | Daily 02:00 UTC | Deletes telemetry rows older than 90 days, logs count to audit_log |
