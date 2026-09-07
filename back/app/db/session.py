"""Async SQLAlchemy engine/session wiring for the FastAPI app.

Alembic and the seed script use their own *synchronous* engine (see
migrations/env.py and scripts/seed.py) because schema migrations and one-off
data loading gain nothing from async and are simpler to reason about as
straight-line sync code. The running API uses the async engine defined here.
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with AsyncSessionLocal() as session:
        yield session
