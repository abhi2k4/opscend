"""Async SQLAlchemy engine, session factory and migration runner."""

import asyncio
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import API_DIR, get_settings


def _new_engine(url: str) -> AsyncEngine:
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
def get_engine() -> AsyncEngine:
    return _new_engine(get_settings().database_url)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


# --- sandboxes: a private copy of the data per visitor of the public demo ------------
#
# On Postgres a sandbox is a schema reached through the shared engine; on SQLite it is
# a database file of its own. Which one a session talks to is decided by a context
# variable, so routes, tools and jobs need no changes: they call session_scope().

SANDBOX_NAME = re.compile(r"^sbx_[0-9a-f]{32}$")
_sandbox: ContextVar[str | None] = ContextVar("opscend_sandbox", default=None)
_sandbox_engines: dict[str, AsyncEngine] = {}
_sandbox_makers: dict[str, async_sessionmaker[AsyncSession]] = {}


def current_sandbox() -> str | None:
    return _sandbox.get()


@contextmanager
def use_sandbox(name: str | None) -> Iterator[None]:
    """Run the enclosed code against one sandbox (None = the shared database)."""
    token = _sandbox.set(name)
    try:
        yield
    finally:
        _sandbox.reset(token)


def sandbox_dir() -> Path | None:
    """Where SQLite sandboxes live; None on Postgres."""
    url = make_url(get_settings().database_url)
    if not url.drivername.startswith("sqlite") or not url.database:
        return None
    main = Path(url.database)
    return main.parent / f"{main.name}.sandboxes"


def sandbox_engine(name: str) -> AsyncEngine:
    if not SANDBOX_NAME.fullmatch(name):
        raise ValueError(f"not a sandbox name: {name!r}")
    if name not in _sandbox_engines:
        folder = sandbox_dir()
        if folder is None:
            engine = get_engine().execution_options(schema_translate_map={None: name})
        else:
            folder.mkdir(parents=True, exist_ok=True)
            engine = _new_engine(f"sqlite+aiosqlite:///{folder / name}.db")
        _sandbox_engines[name] = engine
    return _sandbox_engines[name]


async def forget_sandbox(name: str) -> None:
    """Drop this process's handles on a sandbox (its data is removed by the caller)."""
    _sandbox_makers.pop(name, None)
    engine = _sandbox_engines.pop(name, None)
    if engine is not None and sandbox_dir() is not None:
        await engine.dispose()


async def dispose_all() -> None:
    for name in list(_sandbox_engines):
        await forget_sandbox(name)
    await get_engine().dispose()


def reset_caches() -> None:
    """Forget every engine (tests switch databases between cases)."""
    _sandbox_engines.clear()
    _sandbox_makers.clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


def session_scope(*, shared: bool = False) -> AsyncSession:
    """A new session for jobs and startup code: `async with session_scope() as s:`.

    Inside a sandbox it talks to that sandbox; `shared=True` reaches the main database
    regardless.
    """
    name = None if shared else _sandbox.get()
    if name is None:
        return get_sessionmaker()()
    if name not in _sandbox_makers:
        _sandbox_makers[name] = async_sessionmaker(sandbox_engine(name), expire_on_commit=False)
    return _sandbox_makers[name]()


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
