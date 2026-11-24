import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from app import errors
from app.config import settings
from app.cors import EXPOSED_HEADERS, PerOriginCORS
from app.db import create_tables
from app.limiter import default_limit, limiter
from app.openapi import build as build_openapi
from app.logging_config import configure_logging
from app.middleware import NulGuard, RequestIdMiddleware, SecurityHeaders, SourceMiddleware
from app.routes import admin_users, phone, tokens, telemetry, devices, alerts, tickets, auth, ml, ws, firmware, audit, demo, webhooks, maintenance, contact
from app.routes.health import router as health_router, public_router as health_public_router
from app.tasks.retention import start_retention_scheduler

# without this the INFO lines that development relies on (the invite link, a logged
# contact message) are dropped, because nothing else configures logging.
configure_logging(settings.environment)

# tables are no longer created when this module is imported, so the OpenAPI document can be made with no database. The API
# creates them at start in development (see lifespan), the schema job does it in production (app.db.create_tables) and
# columns added to an existing table come from the numbered SQL files in backend/migrations (Alembic is installed, not used).


def _upgrade_device_keys() -> None:
    # device keys that are still held in clear (a database from before migration 031) are hashed here. It needs the server's secret
    # key, which the SQL file does not have. A failure never stops the start: a machine whose key is not yet hashed is upgraded by
    # its first post
    from app.db import SessionLocal
    from app.services import device_keys

    db = SessionLocal()
    try:
        device_keys.upgrade_legacy_keys(db)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("device keys were not upgraded at start (%s)", type(exc).__name__)
    finally:
        db.close()


def _log_how_we_are_running() -> None:
    """Say at start-up which mode this is, so a wrong ENVIRONMENT or TRUSTED_PROXIES is seen in the first lines."""
    from app.config import DEVELOPMENT_ONLY
    log = logging.getLogger("app.startup")
    mode, warning = settings.proxy_mode()
    log.warning("environment: %s", "DEVELOPMENT (security controls are relaxed)" if settings.is_development else "production")
    log.warning("forwarded headers: %s", mode)
    if warning:
        log.warning(warning)
    if settings.is_development:
        for line in DEVELOPMENT_ONLY:
            log.warning("development allows: %s", line)


def _encrypt_two_step_secrets() -> None:
    # two-step secrets that are still held in clear (a database from before migration 032) are encrypted here. The key is
    # derived from the server's secret, which the SQL file does not have. Safe to run on every start
    from app.db import SessionLocal
    from app.services import two_step_secrets

    db = SessionLocal()
    try:
        two_step_secrets.encrypt_legacy(db)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("two-step secrets were not encrypted at start (%s)", type(exc).__name__)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_how_we_are_running()
    if settings.is_development:
        create_tables()
    # start the retention scheduler here rather than at module level so it
    # does not launch during pytest collection (which imports main).
    start_retention_scheduler()
    _upgrade_device_keys()
    _encrypt_two_step_secrets()
    yield


def docs_options(development: bool) -> dict:
    """The interactive docs and the schema are for development. Elsewhere they are switched
    off so the public API does not publish a map of every route."""
    return {} if development else {"docs_url": None, "redoc_url": None, "openapi_url": None}


app = FastAPI(
    lifespan=lifespan,
    **docs_options(settings.is_development),
    title="PHAEMOS API",
    description="Smart Maintenance Platform - telemetry ingestion, alert rules, tickets and ML anomaly detection",
    version="1.0.0",
    # the default limit on every route (see app/limiter.py)
    dependencies=[Depends(default_limit)],
    # an operation id is the name of its function, so a generated client has readable method names
    generate_unique_id_function=lambda route: route.name,
    # a path with a trailing slash is a 404 in the standard error shape. The framework's 307 to the other spelling built an
    # absolute address from the proxy's plain http hop and a client that followed it would have sent its key in clear
    redirect_slashes=False,
)

# wire the slowapi limiter onto app.state so @limiter.limit decorators on routes
# can resolve the shared instance at request time.
app.state.limiter = limiter
errors.install(app)

# expose a /metrics endpoint that Prometheus scrapes for API performance data.
Instrumentator().instrument(app).expose(app, include_in_schema=False)

# restrict methods and headers explicitly rather than using ["*"] so the
# CORS preflight cannot be used as a probe for unexpected endpoints.
app.add_middleware(
    PerOriginCORS,
    # cookies are sent only to the credentialed origins (the dashboard). Other allowed origins, such as the
    # public site that calls the contact route, get CORS without credentials
    credentialed=settings.credentialed_origin_list,
    others=settings.origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Request-ID", "Idempotency-Key"],
    # lists send their unpaged total in this header, which a browser hides unless it is exposed
    expose_headers=EXPOSED_HEADERS,
)
# outermost last: the source is known first, then NUL characters are refused, then headers are added to every reply
app.add_middleware(SecurityHeaders)
app.add_middleware(NulGuard)
app.add_middleware(SourceMiddleware)
# the request id is made first of all, so every answer and every log line carries it
app.add_middleware(RequestIdMiddleware)

# group route registration by domain to keep API boundaries clear.
app.include_router(auth.router,      prefix="/api/v1/auth",        tags=["Auth"])
app.include_router(admin_users.router, prefix="/api/v1/auth",     tags=["Admin users"])
app.include_router(phone.router,       prefix="/api/v1/auth",     tags=["Phone"])
app.include_router(tokens.router,      prefix="/api/v1/auth",     tags=["API tokens"])
# the account routes at their new paths. The same routes are still served under /auth for one release (deprecated)
app.include_router(tokens.canonical,   prefix="/api/v1",          tags=["API tokens"])
app.include_router(admin_users.canonical, prefix="/api/v1",       tags=["Admin users"])
app.include_router(auth.canonical,     prefix="/api/v1",          tags=["Admin users"])
app.include_router(devices.router,   prefix="/api/v1/devices",     tags=["Devices"])
app.include_router(telemetry.router, prefix="/api/v1/telemetry",   tags=["Telemetry"])
app.include_router(alerts.router,    prefix="/api/v1",             tags=["Alerts"])
app.include_router(tickets.router,   prefix="/api/v1/tickets",     tags=["Tickets"])
app.include_router(ml.router,        prefix="/api/v1/ml",          tags=["ML"])
app.include_router(firmware.router,  prefix="/api/v1",             tags=["Firmware"])
app.include_router(audit.router,     prefix="/api/v1",             tags=["Audit"])
# the demo feed returns a machine's key on every call, so it is not served outside development
if settings.is_development:
    app.include_router(demo.router,      prefix="/api/v1",             tags=["Demo"])
app.include_router(webhooks.router,     prefix="/api/v1",  tags=["Webhooks"])
app.include_router(maintenance.router,  prefix="/api/v1",  tags=["Maintenance"])
app.include_router(contact.router,      prefix="/api/v1",  tags=["Contact"])
# health_router has auth-protected fleet stats; health_public_router has the no-auth /status check
app.include_router(health_router,       prefix="/api/v1",  tags=["Health"])
app.include_router(health_public_router,                   tags=["Health"])
# give WebSocket routes a different prefix - no /api/v1 so the WS URL is clean.
app.include_router(ws.router,        tags=["WebSocket"])


# the document is made from the routes above, with the credentials and error shape added (app/openapi.py)
app.openapi = lambda: build_openapi(app)


@app.get("/", include_in_schema=False)
def health():
    # no environment name here: it tells a stranger which controls are relaxed
    return {"status": "ok", "service": "PHAEMOS API", "version": settings.release_version, "api_version": "v1"}
