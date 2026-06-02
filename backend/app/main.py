from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.db import Base, engine
from app.limiter import limiter
from app.routes import telemetry, devices, alerts, tickets, auth, ml, ws, firmware, audit, demo, webhooks
from app.routes.health import router as health_router, public_router as health_public_router
from app.tasks.retention import start_retention_scheduler

# I create all tables on startup - use Alembic migrations for production
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # I start the retention scheduler here rather than at module level so it
    # does not launch during pytest collection (which imports main).
    start_retention_scheduler()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="PHAEMOS API",
    description="Smart Maintenance Platform - telemetry ingestion, alert rules, tickets and ML anomaly detection",
    version="1.0.0",
)

# I wire the slowapi limiter onto app.state so @limiter.limit decorators on routes
# can resolve the shared instance at request time.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# I expose a /metrics endpoint that Prometheus scrapes for API performance data.
Instrumentator().instrument(app).expose(app)

# I restrict methods and headers explicitly rather than using ["*"] so the
# CORS preflight cannot be used as a probe for unexpected endpoints.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
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
app.include_router(webhooks.router,     prefix="/api/v1",  tags=["Webhooks"])
# health_router has auth-protected fleet stats; health_public_router has the no-auth /status check
app.include_router(health_router,       prefix="/api/v1",  tags=["Health"])
app.include_router(health_public_router,                   tags=["Health"])
# I give WebSocket routes a different prefix - no /api/v1 so the WS URL is clean.
app.include_router(ws.router,        tags=["WebSocket"])


@app.get("/", include_in_schema=False)
def health():
    return {"status": "ok", "service": "PHAEMOS API", "version": app.version, "environment": settings.environment}
