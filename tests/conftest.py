import os
from contextlib import nullcontext
from pathlib import Path

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://taskflow:taskflow@localhost:5432/taskflow_test"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")
# Must be set before the app is imported so settings pick up the test services.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["REDIS_URL"] = TEST_REDIS_URL
# Run background jobs inline so tests can assert their effects directly.
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from alembic.config import Config
from app.api.deps import get_db
from app.main import app
from app.worker import jobs

ROOT = Path(__file__).resolve().parent.parent


def _ensure_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine():
    _ensure_database()
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    # Building the schema with the real migrations also tests them.
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine):
    # Each test runs in an outer transaction that is rolled back, even though
    # the app code commits (those commits only release a savepoint).
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db_session
    # Jobs open their own session; point them at the test transaction so they can
    # see uncommitted test data and get rolled back with it.
    monkeypatch.setattr(jobs, "SessionLocal", lambda: nullcontext(db_session))
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def create_user(client):
    """Sign up a user and return their Authorization headers."""

    def _create(email: str = "user@example.com", password: str = "password123") -> dict[str, str]:
        client.post("/auth/signup", json={"email": email, "password": password})
        resp = client.post("/auth/login", data={"username": email, "password": password})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return _create


@pytest.fixture(autouse=True)
def clean_redis():
    from app.core.cache import redis_client

    redis_client.flushdb()
