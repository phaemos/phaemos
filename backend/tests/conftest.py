import os

# must set env vars before importing any app module - pydantic-settings reads
# them at class definition time (when Settings() is instantiated on import).
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:password@localhost:5432/phaemos_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("DISCORD_WEBHOOK_URL", "")
os.environ.setdefault("ALERT_EMAIL_TO", "")

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
def reset_rate_limits():
    # the limiter is shared by the whole session, so clear it before each test
    # rather than letting earlier tests use up a later test's allowance.
    from app.limiter import limiter
    limiter.reset()
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
