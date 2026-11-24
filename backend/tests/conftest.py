import os

# must set env vars before importing any app module - pydantic-settings reads
# them at class definition time (when Settings() is instantiated on import).
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:password@localhost:5432/phaemos_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("DISCORD_WEBHOOK_URL", "")
os.environ.setdefault("ALERT_EMAIL_TO", "")
# development is stated and never assumed, so the suite states it. The relaxations it allows are listed in app/config.py
os.environ.setdefault("ENVIRONMENT", "development")
# the proxy a test client "connects from" is loopback, which is trusted here so tests can send X-Real-IP
os.environ.setdefault("TRUSTED_PROXIES", "127.0.0.1/32,::1/128")
# most tests mint access tokens with no session. Allowed in development only and tests of the rule turn it on
os.environ.setdefault("REQUIRE_SESSION_ID", "false")

from sqlalchemy.engine import make_url  # noqa: E402

# the session fixture drops every table when it finishes, so refuse to run
# against any database that is not named as a test database. The check sits
# above the app imports because importing app.main already connects to the
# database and creates its tables.
_db_name = make_url(os.environ["DATABASE_URL"]).database or ""
if not _db_name.endswith("_test"):
    raise RuntimeError(
        f"refusing to run tests against database '{_db_name}': "
        "the name must end in _test (use `make test` or a phaemos_test database)"
    )

import secrets  # noqa: E402
import pytest  # noqa: E402
from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.device import Device  # noqa: E402
from app.models.user import User  # noqa: E402

# separate test engine, only ever created for a database that passed the check above.
_engine = create_engine(os.environ["DATABASE_URL"])
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# audit_log is a raw-SQL table (not an ORM model) so Base.metadata.create_all
# does not create it, so create it explicitly here so audit_service.log_action()
# does not fail in tests, which would roll back the outer transaction and corrupt
# the test state that follows.
_AUDIT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     VARCHAR(255),
    action      VARCHAR(100) NOT NULL,
    resource    VARCHAR(100),
    resource_id VARCHAR(255),
    detail      TEXT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    # a connection option such as ?dbname= can point the URL at another database
    # than the one in its path, so the server is asked which one it really opened.
    with _engine.connect() as conn:
        connected = conn.execute(text("SELECT current_database()")).scalar() or ""
    if not connected.endswith("_test"):
        raise RuntimeError(f"refusing to run tests against database '{connected}'")
    # create all tables once for the whole test session, drop them at the end.
    Base.metadata.create_all(bind=_engine)
    with _engine.connect() as conn:
        conn.execute(text(_AUDIT_LOG_DDL))
        conn.commit()
    yield
    Base.metadata.drop_all(bind=_engine)
    with _engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS audit_log"))
        conn.commit()


@pytest.fixture
def db(setup_database):
    # each test gets its own transaction rolled back on teardown - fast isolation
    # without re-creating the schema between tests.
    connection = _engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def vendor_keys_unset(monkeypatch):
    # a developer's real backend/.env must never cause a real send, so every test
    # starts with both vendor keys unset. A test that needs one sets it itself.
    from app.config import settings
    monkeypatch.setattr(settings, "resend_api_key", "")
    monkeypatch.setattr(settings, "brevo_api_key", "")
    yield


@pytest.fixture(autouse=True)
def registration_open(monkeypatch):
    # registration follows the environment, which a developer's backend/.env or CI may
    # change. Most tests create accounts through the API, so they start with it open;
    # tests of the closed behaviour set it to False themselves.
    from app.config import settings
    monkeypatch.setattr(settings, "registration_open", True)
    yield


@pytest.fixture(autouse=True)
def redis_breaker_closed():
    # one test that makes Redis fail must not leave later tests skipping a Redis they stand in for
    from app.services import cooldown
    cooldown._redis_down_until = 0.0
    yield
    cooldown._redis_down_until = 0.0


@pytest.fixture(autouse=True)
def socket_token_in_url_allowed(monkeypatch):
    # the URL form follows the environment too. Most socket tests use it, so it starts allowed;
    # tests of the refused behaviour set it to False themselves.
    from app.config import settings
    monkeypatch.setattr(settings, "ws_token_in_url", True)
    yield


@pytest.fixture(autouse=True)
def no_background_scheduler(monkeypatch):
    # every client fixture starts the app's lifespan, which used to start a scheduler thread that was never stopped;
    # each leaked scheduler then ran the liveness sweep every 15 seconds for the rest of the run, taking the sweep's
    # lock and touching the database in the middle of other tests. No test needs the scheduler running: the ones about
    # it call start_retention_scheduler themselves with a stand-in scheduler
    import app.main
    monkeypatch.setattr(app.main, "start_retention_scheduler", lambda: None)
    # nor does any test need the start-up hashing of old device keys, which would open its own session on every client. The
    # tests of it call device_keys.upgrade_legacy_keys themselves
    monkeypatch.setattr(app.main, "_upgrade_device_keys", lambda: None)


def pytest_configure(config):
    config.addinivalue_line("markers", "real_fault_gating: run with the real rule for which fault claims may stop a sensor")


@pytest.fixture(autouse=True)
def claimed_faults_stop_their_sensor(request, monkeypatch):
    # in production a node's fault claim stops its sensor only while the matching sensor alert is open (health_service.
    # stoppable_sensors). The tests written before that rule post a fault and expect the sensor stopped in the same post,
    # because they are about what a stopped sensor does. They run with every claim counted (None means all). A test of the
    # rule itself carries the mark real_fault_gating and runs with the real one
    if request.node.get_closest_marker("real_fault_gating"):
        return
    from app.services import health_service

    monkeypatch.setattr(health_service, "stoppable_sensors", lambda db, device: None)


@pytest.fixture(autouse=True)
def webhook_no_backoff(monkeypatch):
    # a webhook delivery pauses 2 and 8 seconds between its tries. A test must not wait for that
    from app.services import webhook_service

    monkeypatch.setattr(webhook_service, "_sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def notify_pool_inline(monkeypatch):
    # a notification is handed to the notify pool, whose worker threads would run it after the test had moved on. In a
    # test it runs at once in the caller's thread, which keeps every assertion about what was sent deterministic. The tests
    # of the pool itself switch this off
    from app.services import notify_pool
    notify_pool.reset()
    monkeypatch.setattr(notify_pool, "run_inline", True)


@pytest.fixture(autouse=True)
def notification_reset_recorder(monkeypatch):
    # a failed send marks its rule alert as not yet notified through its own session, which would commit outside a test's
    # transaction. It is recorded here instead and a test reads the list
    from app.services import alert_service
    calls = []
    monkeypatch.setattr(alert_service, "_forget_notification", lambda alert_id: calls.append(alert_id))
    return calls


@pytest.fixture
def stub_score(monkeypatch):
    # stands in for the model at the one place the ingest route calls it. It takes the real signature (see
    # ml_service.score_reading), so when that changes this is the only edit. Call it with a score (or None for a reading
    # the model could not score) and each post gets exactly that, flagged as an anomaly from the public boundary of 0.7
    from app.routes import telemetry as telemetry_route
    from app.services import ml_service

    def fake(reading, device_id=None, at=None, track=True):
        score = fake.score
        return score, bool(score is not None and score >= 0.7)

    fake.score = None

    def use(score):
        fake.score = score
        monkeypatch.setattr(telemetry_route, "score_reading", fake)
        return fake

    use.signature = ml_service.score_reading
    return use


@pytest.fixture
def forget_failed(db, notification_reset_recorder):
    # a failed send calls _forget_notification, which the autouse recorder replaces (the real one commits through its own
    # session). This applies what the real one does to the test's session: the alerts whose send failed lose notified_at
    from app.models.alert import Alert

    def apply():
        ids = list(notification_reset_recorder)
        notification_reset_recorder.clear()
        for alert_id in ids:
            alert = db.get(Alert, alert_id)
            if alert is not None:
                alert.notified_at = None
        db.flush()
        return ids

    return apply


@pytest.fixture
def old_three_in_a_row(monkeypatch):
    # the anomaly decision is the model builder's pure module. The tests of how an alert is raised, kept, escalated and
    # resolved by the alert service stand it in with the old rule (three scored readings in a row over or under the
    # boundary, from the last minute), so they do not depend on the maths. A test of one action stubs decide itself
    from app.services import alert_service, anomaly_decision

    Decision = anomaly_decision.Decision

    def decide(points, open_alert_since, last_resolved_at, now, interval_s):
        window = max(60, 6 * interval_s)
        last = [p for p in points if (now - p[0]).total_seconds() <= window][-3:]
        if len(last) < 3:
            return Decision("none")
        if all(score < 0.7 for _, score in last):
            return Decision("resolve", reason="the scores are back under the boundary") if open_alert_since else Decision("none")
        if all(score >= 0.7 for _, score in last):
            peak = max(score for _, score in last)
            severity = "critical" if peak >= 0.85 else "warning"
            reason = f"3 readings in a row outside its normal range (score {peak:.2f})"
            if open_alert_since is not None:
                return Decision("escalate", "critical", reason) if severity == "critical" else Decision("none")
            return Decision("raise", severity, reason)
        return Decision("none")

    monkeypatch.setattr(alert_service.anomaly_decision, "decide", decide)
    return decide


@pytest.fixture(autouse=True)
def cap_audit(monkeypatch):
    # the entry written when a daily alert limit is reached goes to the audit log through its own session, which
    # would commit outside a test's transaction. It is recorded here instead and a test reads the list
    from app.services import alert_service
    calls = []
    monkeypatch.setattr(alert_service, "_write_cap_audit", lambda channel, cap: calls.append((channel, cap)))
    return calls


@pytest.fixture(autouse=True)
def reset_sign_in_guard(monkeypatch):
    # counters in this process only, so a shared Redis never carries a count from one test into another
    from app.services import signin_guard
    monkeypatch.setattr(signin_guard, "memory_only", True)
    signin_guard.reset()
    yield
    signin_guard.reset()


@pytest.fixture(autouse=True)
def reset_rate_limits():
    # the limiter is shared by the whole session, so clear it before each test
    # rather than letting earlier tests use up a later test's allowance.
    from app.limiter import limiter
    from app.services import heavy_reads, ingest_limit
    limiter.reset()
    heavy_reads.reset()
    ingest_limit.reset()
    yield


@pytest.fixture
def client(db):
    # override FastAPI's get_db dependency so every request in a test uses
    # the same transactional session (and therefore sees the test fixtures).
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def device(db):
    # a real Device row with a valid API key - used by telemetry ingest tests.
    dev = Device(
        name="Test ESP32",
        location="Lab",
        type="esp32",
        api_key=secrets.token_urlsafe(32),
    )
    db.add(dev)
    db.flush()  # write to the transaction without committing
    return dev


@pytest.fixture
def admin_user(db):
    user = User(
        name="Admin",
        email="admin@test.com",
        password_hash=_pwd_ctx.hash("Admin1234!"),
        role="admin",
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def auth_headers(admin_user):
    # generate a real JWT here so tests exercise the actual token-validation path
    # rather than mocking it - any regression in the auth dependency will surface
    # in these tests rather than only in manual testing.
    from app.routes.auth import create_access_token
    token = create_access_token({"sub": str(admin_user.id), "role": admin_user.role})
    return {"Authorization": f"Bearer {token}"}


def _pristine_model_state():
    """Every module-level cache the anomaly model keeps, back to what a freshly started worker has."""
    import threading

    from app.services import change_detector, ml_service
    ml_service._model = None
    ml_service._problem = None
    ml_service._load_failure = None
    ml_service._loaded_mtime = None
    ml_service._next_check = 0.0
    ml_service._packed.clear()
    ml_service._logged.clear()
    ml_service._local = threading.local()
    ml_service._refusal_cache.update({"mtime": None, "data": {}})
    store = ml_service._state_store
    if hasattr(store, "fallback"):
        store.fallback = change_detector.MemoryStateStore()


@pytest.fixture(autouse=True)
def model_state_isolated():
    # the anomaly model keeps its loaded file, the reason it will not load, a per-thread note of the last reading's problem,
    # the packed trees and the last retrain's refusals in module globals. One test's leftovers (a refusal on record, a
    # cached problem) must not become another test's answer, so each test starts and ends with a fresh worker's state
    _pristine_model_state()
    yield
    _pristine_model_state()
