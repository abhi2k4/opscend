"""arq worker: `uv run arq app.worker.WorkerSettings` (used when REDIS_URL is set)."""

from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.logging import configure_logging
from app.jobs import JOBS, health_checks, reconcile


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()


async def shutdown(ctx: dict[str, Any]) -> None:
    await get_engine().dispose()


class WorkerSettings:
    functions: ClassVar = list(JOBS.values())
    cron_jobs: ClassVar = [
        cron(reconcile, second={0}, run_at_startup=True),  # every 60s: poll for missed webhooks
        cron(health_checks, second={30}),  # every 60s, offset from the poller
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379")
    max_jobs = 10
    job_timeout = 300
