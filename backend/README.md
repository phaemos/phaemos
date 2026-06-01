# Backend

FastAPI application - telemetry ingestion, alert rules, tickets, ML anomaly detection, JWT auth.

| Folder / File | Purpose |
|---|---|
| [app/](app/) | Main application package |
| [ml/](ml/) | ML pipeline - training, preprocessing, evaluation |
| [migrations/](migrations/) | Alembic SQL migrations |
| [tests/](tests/) | pytest test suite |
| [scripts/](scripts/) | One-off utility scripts |
| Dockerfile | Production Docker image |
| requirements.txt | Python dependencies |

Start locally: `docker compose up db redis backend -d`
API docs: http://localhost:8000/docs
