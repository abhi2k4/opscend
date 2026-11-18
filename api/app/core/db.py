"""Async SQLAlchemy engine, session factory and migration runner."""

import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import API_DIR, get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    url = get_settings().database_url
    engine = create_async_engine(url, pool_pre_ping=True)
    if url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


def session_scope() -> AsyncSession:
    """A new session for jobs and startup code: `async with session_scope() as s:`."""
    return get_sessionmaker()()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one session per request."""
    async with session_scope() as session:
        yield session


def _upgrade_head() -> None:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(config, "head")


async def run_migrations() -> None:
    """Apply Alembic migrations; run in a thread because env.py drives its own event loop."""
    await asyncio.to_thread(_upgrade_head)
