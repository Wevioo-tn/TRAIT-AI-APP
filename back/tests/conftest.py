"""Shared fixtures for the DB-layer test suite.

Every test in this suite runs against ``settings.database_url_test`` — a
database dedicated to the test suite, distinct from the dev database — so
tests never read or corrupt seeded/dev data. Each test runs inside its own
transaction that is rolled back afterwards, so tests never leak state into
one another either.
"""
import os
import shutil
import tempfile

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session
from app.main import app
from app.services.jwt_auth import create_access_token
from app.services.storage import LocalFileStorage, get_storage

settings = get_settings()

BACK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The identity every `client`-based test is authenticated as by default.
# Bypasses real LDAP (most tests aren't testing auth itself, just the
# endpoints behind it) — see test_auth.py for the login/LDAP path itself.
TEST_USERNAME = "h.mansouri"


@pytest.fixture(scope="session", autouse=True)
def apply_migrations():
    """Rebuild the test database schema from scratch, once per test session."""
    os.environ["ALEMBIC_DATABASE_URL"] = settings.database_url_test
    cfg = Config(os.path.join(BACK_DIR, "alembic.ini"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    del os.environ["ALEMBIC_DATABASE_URL"]


@pytest.fixture(scope="session")
def sync_engine(apply_migrations):
    engine = create_engine(settings.database_url_test, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sync_engine):
    """A Session bound to a transaction that is always rolled back."""
    connection = sync_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def clean_app_tables(sync_engine):
    """Wipe this app's own tables (never imx.*) before an API test runs.

    API tests go through real HTTP requests, each opening/committing its
    own DB session — they can't share the ``db_session`` rollback trick, so
    isolation is enforced with an explicit TRUNCATE instead. ``CASCADE``
    takes documents/checks/decisions/audit_log with it since they all FK to
    ``traites``.
    """
    with sync_engine.begin() as connection:
        connection.execute(text("TRUNCATE traites CASCADE"))
    yield


@pytest.fixture
async def client(apply_migrations, clean_app_tables):
    """An httpx AsyncClient driving the real FastAPI app, with both the DB
    and file-storage dependencies overridden so tests never touch the dev
    database or the real uploads volume."""
    test_engine = create_async_engine(settings.database_url_test, future=True)
    test_session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def override_get_session():
        async with test_session_local() as session:
            yield session

    upload_dir = tempfile.mkdtemp(prefix="trait-ai-test-uploads-")
    test_storage = LocalFileStorage(base_dir=upload_dir)

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_storage] = lambda: test_storage
    transport = ASGITransport(app=app)
    token = create_access_token(TEST_USERNAME)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {token}"}
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
    await test_engine.dispose()
    shutil.rmtree(upload_dir, ignore_errors=True)
