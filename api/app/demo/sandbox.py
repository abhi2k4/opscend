"""A private copy of the sample data for each visitor of the public demo.

Without this, one visitor breaking a deploy, muting a service or pressing Reset would
change what everyone else is looking at. A sandbox is cloned from the shared sample
data the first time a browser comes back with its visitor cookie, keeps the same ids
(so a page loaded a moment earlier still points at the right rows), and is deleted
once it has been idle for a while.

The registry (`DemoSandbox`) lives in the main database so any process can see which
sandboxes exist; the cache below only saves a lookup per request.
"""

import asyncio
import logging
import shutil
import time
from datetime import timedelta

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from app.core import db
from app.core.config import get_settings
from app.core.time import utcnow
from app.models import Base, DemoSandbox

log = logging.getLogger(__name__)

# Never cloned: the registry itself, and accounts (visitors are guests).
NOT_CLONED = {"demo_sandbox", "user"}
COPY_CHUNK = 500
TOUCH_EVERY = 60.0  # seconds between writes of last_seen_at, and how long the cache is trusted
BUILD_TIMEOUT = timedelta(seconds=60)  # a half-built sandbox older than this was abandoned
WAIT_FOR_BUILD = 20.0
ACTIVE = timedelta(minutes=15)  # periodic jobs only visit sandboxes used this recently

_checked: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = {}


def name_for(visitor: str) -> str:
    return "sbx_" + visitor.replace("-", "")


async def enter(visitor: str) -> str | None:
    """The sandbox of this visitor, built on first use. None if it could not be built."""
    name = name_for(visitor)
    if not db.SANDBOX_NAME.fullmatch(name):
        return None
    now = time.monotonic()
    if now - _checked.get(name, -1e9) < TOUCH_EVERY:
        return name
    lock = _locks.setdefault(name, asyncio.Lock())
    try:
        async with lock:
            if await _ensure(name):
                _checked[name] = time.monotonic()
                return name
            return None
    finally:
        if not lock.locked():
            _locks.pop(name, None)


async def _ensure(name: str) -> bool:
    async with db.session_scope(shared=True) as session:
        row = await session.get(DemoSandbox, name)
        if row is not None and row.ready:
            row.last_seen_at = utcnow()
            await session.commit()
            return True
        if row is not None and utcnow() - row.created_at < BUILD_TIMEOUT:
            return await _wait_until_ready(name)  # another process is building it
        if row is not None:
            await session.rollback()
            await drop(name)
        await _make_room()
        session.add(DemoSandbox(id=name))
        try:
            await session.commit()
        except IntegrityError:  # lost a race with another process
            await session.rollback()
            return await _wait_until_ready(name)
    try:
        await _build(name)
    except Exception:
        log.exception("could not build sandbox %s", name)
        await drop(name)
        return False
    async with db.session_scope(shared=True) as session:
        await session.execute(update(DemoSandbox).where(DemoSandbox.id == name).values(ready=True))
        await session.commit()
    return True


async def _wait_until_ready(name: str) -> bool:
    deadline = time.monotonic() + WAIT_FOR_BUILD
    while time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        async with db.session_scope(shared=True) as session:
            ready = await session.scalar(select(DemoSandbox.ready).where(DemoSandbox.id == name))
        if ready is None:
            return False
        if ready:
            return True
    return False


async def _build(name: str) -> None:
    """Create the sandbox's tables and copy the shared sample data into them."""
    if db.sandbox_dir() is None:
        async with db.get_engine().begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{name}"'))
    tables = [t for t in Base.metadata.sorted_tables if t.name not in NOT_CLONED]
    engine = db.sandbox_engine(name)
    async with db.get_engine().connect() as source, engine.begin() as target:
        await target.run_sync(Base.metadata.create_all, tables=tables, checkfirst=False)
        for table in tables:
            rows = [dict(row) for row in (await source.execute(select(table))).mappings()]
            for start in range(0, len(rows), COPY_CHUNK):
                await target.execute(insert(table), rows[start : start + COPY_CHUNK])


async def drop(name: str) -> None:
    """Delete a sandbox and its registry row. Safe to call for one that is half built."""
    if not db.SANDBOX_NAME.fullmatch(name):
        return
    _checked.pop(name, None)
    await db.forget_sandbox(name)
    folder = db.sandbox_dir()
    if folder is None:
        async with db.get_engine().begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
    else:
        for suffix in (".db", ".db-wal", ".db-shm"):
            (folder / f"{name}{suffix}").unlink(missing_ok=True)
    async with db.session_scope(shared=True) as session:
        await session.execute(delete(DemoSandbox).where(DemoSandbox.id == name))
        await session.commit()


async def _make_room() -> None:
    """Keep the number of sandboxes bounded: the least recently used ones go first."""
    limit = max(1, get_settings().public_demo_max_sessions)
    async with db.session_scope(shared=True) as session:
        count = await session.scalar(select(func.count(DemoSandbox.id))) or 0
        if count < limit:
            return
        oldest = (
            await session.scalars(
                select(DemoSandbox.id).order_by(DemoSandbox.last_seen_at).limit(count - limit + 1)
            )
        ).all()
    for name in oldest:
        await drop(name)


async def sweep() -> int:
    """Job: delete sandboxes nobody has used for OPSCEND_PUBLIC_DEMO_SESSION_MINUTES."""
    minutes = get_settings().public_demo_session_minutes
    if minutes <= 0:
        return 0
    async with db.session_scope(shared=True) as session:
        idle = (
            await session.scalars(
                select(DemoSandbox.id).where(
                    DemoSandbox.last_seen_at < utcnow() - timedelta(minutes=minutes)
                )
            )
        ).all()
    for name in idle:
        await drop(name)
    return len(idle)


async def active() -> list[str]:
    """Sandboxes someone used recently (the ones periodic jobs should look after)."""
    async with db.session_scope(shared=True) as session:
        return list(
            (
                await session.scalars(
                    select(DemoSandbox.id).where(
                        DemoSandbox.ready.is_(True),
                        DemoSandbox.last_seen_at > utcnow() - ACTIVE,
                    )
                )
            ).all()
        )


async def drop_all() -> None:
    """Startup: remove every sandbox, including leftovers no registry row points at.

    A restart may come with a new schema version, and a sandbox is not migrated.
    """
    async with db.session_scope(shared=True) as session:
        names = set((await session.scalars(select(DemoSandbox.id))).all())
    folder = db.sandbox_dir()
    if folder is None:
        async with db.get_engine().connect() as conn:
            found = await conn.scalars(text("SELECT schema_name FROM information_schema.schemata"))
            names |= {schema for schema in found if db.SANDBOX_NAME.fullmatch(schema)}
    for name in names:
        await drop(name)
    if folder is not None and folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    _checked.clear()
