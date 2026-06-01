import os

# Must set env vars before importing any app module — pydantic-settings reads
# them at class definition time (when Settings() is instantiated on import).
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:password@localhost:5432/phaemos_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("DISCORD_WEBHOOK_URL", "")
os.environ.setdefault("ALERT_EMAIL_TO", "")

import secrets  # noqa: E402
import pytest  # noqa: E402
from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.device import Device  # noqa: E402
from app.models.user import User  # noqa: E402

# Separate test engine so tests never touch the development database.
_engine = create_engine(os.environ["DATABASE_URL"])
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    # Create all tables once for the whole test session, drop them at the end.
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture
def db(setup_database):
    # Each test gets its own transaction rolled back on teardown — fast isolation
    # without re-creating the schema between tests.
    connection = _engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db):
    # Override FastAPI's get_db dependency so every request in a test uses
    # the same transactional session (and therefore sees the test fixtures).
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def device(db):
    # A real Device row with a valid API key — used by telemetry ingest tests.
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
    # I generate a real JWT here so tests exercise the actual token-validation path
    # rather than mocking it - any regression in the auth dependency will surface
    # in these tests rather than only in manual testing.
    from app.routes.auth import create_access_token
    token = create_access_token({"sub": str(admin_user.id), "role": admin_user.role})
    return {"Authorization": f"Bearer {token}"}
