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
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.user import User
from app.db.session import get_session
from app.main import app
from app.services.jwt_auth import create_access_token
from app.services.password_hash import hash_password
from app.services.storage import LocalFileStorage, get_storage

settings = get_settings()

BACK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The identity every `client`-based test is authenticated as by default.
# Most tests bypass a real login (they aren't testing auth itself, just the
# endpoints behind it) via create_access_token below — see test_auth.py for
# the actual login path, which needs `seed_test_user` (also below) to have
# a real row to authenticate against.
TEST_USERNAME = "h.mansouri"
TEST_PASSWORD = "secret123"


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


@pytest.fixture(scope="session", autouse=True)
def seed_test_user(sync_engine):
    """A real row in the real `users` table — TEST_USERNAME/TEST_PASSWORD
    must actually authenticate for test_auth.py's login tests, not just be
    accepted as a pre-made JWT the way every other `client`-based test
    treats them. Session-scoped: `users` is never touched by
    `clean_app_tables`'s per-test TRUNCATE, so one real Argon2 hash for the
    whole session is enough."""
    with Session(sync_engine) as session:
        existing = session.scalar(select(User).where(User.username == TEST_USERNAME))
        if existing is None:
            session.add(User(username=TEST_USERNAME, password_hash=hash_password(TEST_PASSWORD)))
            session.commit()


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
