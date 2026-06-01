# App Package

| Folder / File | Purpose |
|---|---|
| [models/](models/) | SQLAlchemy ORM models - DB table definitions |
| [routes/](routes/) | FastAPI route handlers - one file per domain |
| [schemas/](schemas/) | Pydantic request/response schemas |
| [services/](services/) | Business logic shared across routes |
| [tasks/](tasks/) | Background tasks (APScheduler) |
| main.py | FastAPI app factory - router registration, CORS, lifespan |
| db.py | Database engine and session factory |
| config.py | Settings loaded from environment variables |
