from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.db import Base, engine
from app.routes import telemetry, devices, alerts, tickets, auth, ml, ws, firmware, audit, demo

# I create all tables on startup - use Alembic migrations for production
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="PHAEMOS API",
    description="Smart Maintenance Platform - telemetry ingestion, alert rules, tickets and ML anomaly detection",
    version="1.0.0",
)

# I expose a /metrics endpoint that Prometheus scrapes for API performance data.
Instrumentator().instrument(app).expose(app)

# I keep local frontend access straightforward during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# I group route registration by domain to keep API boundaries clear.
app.include_router(auth.router,      prefix="/api/v1/auth",        tags=["Auth"])
app.include_router(devices.router,   prefix="/api/v1/devices",     tags=["Devices"])
app.include_router(telemetry.router, prefix="/api/v1/telemetry",   tags=["Telemetry"])
app.include_router(alerts.router,    prefix="/api/v1",             tags=["Alerts"])
app.include_router(tickets.router,   prefix="/api/v1/tickets",     tags=["Tickets"])
app.include_router(ml.router,        prefix="/api/v1/ml",          tags=["ML"])
app.include_router(firmware.router,  prefix="/api/v1",             tags=["Firmware"])
app.include_router(audit.router,     prefix="/api/v1",             tags=["Audit"])
app.include_router(demo.router,      prefix="/api/v1",             tags=["Demo"])
# I give WebSocket routes a different prefix - no /api/v1 so the WS URL is clean.
app.include_router(ws.router,        tags=["WebSocket"])


@app.get("/", include_in_schema=False)
def health():
    return {"status": "ok", "service": "PHAEMOS API", "version": app.version, "environment": settings.environment}
