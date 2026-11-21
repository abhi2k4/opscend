"""FastAPI application and startup sequence."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select, update

from app import __version__
from app.core.config import get_settings
from app.core.db import get_engine, run_migrations, session_scope
from app.core.logging import configure_logging
from app.core.queue import init_queue
from app.core.security import hash_password, verify_password
from app.core.time import utcnow
from app.demo.seed import demo_exists, seed_demo
from app.jobs import JOBS, periodic_jobs
from app.models import ChatMessage, Investigation, User
from app.routes import api_router

log = logging.getLogger(__name__)


async def ensure_admin() -> None:
    """Keep the single user in step with OPSCEND_ADMIN_EMAIL / OPSCEND_ADMIN_PASSWORD."""
    settings = get_settings()
    email = settings.admin_email.strip().lower()
    async with session_scope() as session:
        user = await session.scalar(select(User).order_by(User.created_at).limit(1))
        if user is None:
            session.add(User(email=email, password_hash=hash_password(settings.admin_password)))
        else:
            user.email = email
            if not verify_password(settings.admin_password, user.password_hash):
                user.password_hash = hash_password(settings.admin_password)
        await session.commit()


async def fail_orphaned_investigations() -> None:
    """Inline jobs die with the process, so anything still 'running' at boot never finishes."""
    async with session_scope() as session:
        await session.execute(
            update(Investigation)
            .where(Investigation.status.in_(("queued", "running")))
            .values(
                status="failed",
                error="Interrupted by an API restart. Run it again.",
                finished_at=utcnow(),
            )
        )
        await session.execute(
            update(ChatMessage)
            .where(ChatMessage.status.in_(("pending", "running")))
            .values(
                status="failed",
                error="Interrupted by an API restart. Ask again.",
                finished_at=utcnow(),
            )
        )
        await session.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    if settings.auto_migrate:
        await run_migrations()
    await ensure_admin()
    if settings.demo:
        async with session_scope() as session:
            if not await demo_exists(session):
                await seed_demo(session)
                log.info("seeded demo data")
    queue = init_queue(JOBS, periodic_jobs())
    if queue.kind == "inline":
        await fail_orphaned_investigations()
    await queue.start()
    log.info(
        "Opscend %s ready: database=%s queue=%s demo=%s ai_configured=%s",
        __version__,
        settings.database_kind,
        queue.kind,
        settings.demo,
        settings.ai_configured,
    )
    yield
    await queue.stop()
    await get_engine().dispose()


app = FastAPI(
    title="Opscend API",
    version=__version__,
    description="One timeline for Vercel, Railway and GitHub deploys, with a read-only AI "
    "investigator that explains why a deploy broke.",
    lifespan=lifespan,
    docs_url=None,  # served in Opscend's own skin by app/routes/docs.py
    redoc_url=None,
    openapi_url="/api/openapi.json",
)
app.include_router(api_router)
