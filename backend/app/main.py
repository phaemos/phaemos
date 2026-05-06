from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import Base, engine
from app.routes import telemetry, devices, alerts, tickets, auth, ml

# Create all tables on startup (use Alembic migrations for production)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="PHAEMOS API",
    description="Smart Maintenance Platform - telemetry ingestion, alert rules, tickets and ML anomaly detection",
    version="1.0.0",
)

# Keep local frontend access straightforward during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Route registration is grouped by domain to keep API boundaries clear.
app.include_router(auth.router,      prefix="/api/v1/auth",        tags=["Auth"])
app.include_router(devices.router,   prefix="/api/v1/devices",     tags=["Devices"])
app.include_router(telemetry.router, prefix="/api/v1/telemetry",   tags=["Telemetry"])
app.include_router(alerts.router,    prefix="/api/v1",             tags=["Alerts"])
app.include_router(tickets.router,   prefix="/api/v1/tickets",     tags=["Tickets"])
app.include_router(ml.router,        prefix="/api/v1/ml",          tags=["ML"])


@app.get("/", include_in_schema=False)
def health():
    return {"status": "ok", "service": "PHAEMOS API", "version": app.version, "environment": settings.environment}
