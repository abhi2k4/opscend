"""arq worker: `uv run arq app.worker.WorkerSettings` (used when REDIS_URL is set)."""

from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.cron import CronJob

from app.chat.service import job_timeout as model_job_timeout
from app.core.config import get_settings
from app.core.db import dispose_all
from app.core.logging import configure_logging
from app.jobs import (
    JOBS,
    deliver_notifications,
    expire_chat_replies,
    health_checks,
    prune,
    reconcile,
    refresh_demo,
)

# How often the public demo is tidied, as in the inline queue's `periodic_jobs`.
DEMO_REFRESH_SECONDS = 300


def every(seconds: int, at_second: int) -> dict[str, set[int]]:
    """cron() fields for a job run about every `seconds`, at second `at_second` of a minute.

    arq schedules by clock fields, not by interval, so an interval setting is mapped onto
    them: under a minute runs twice a minute (the inline queue's floor is 30s), longer
    runs every whole number of minutes, at most hourly. A step that does not divide 60
    leaves one shorter gap each hour.
    """
    if seconds < 60:
        return {"second": {at_second, (at_second + 30) % 60}}
    step = min(60, round(seconds / 60))
    return {"minute": set(range(0, 60, step)), "second": {at_second}}


def build_cron_jobs() -> list[CronJob]:
    """The periodic jobs, on the same intervals the inline queue uses."""
    settings = get_settings()
    jobs = [
        # Poll for missed webhooks.
        cron(reconcile, **every(settings.poll_interval_seconds, at_second=0), run_at_startup=True),
        # Offset from the poller.
        cron(health_checks, **every(settings.health_interval_seconds, at_second=30)),
        cron(deliver_notifications, second={5, 20, 35, 50}),  # email outbox, every 15s
        cron(expire_chat_replies, second={45}),  # every 60s: fail chat replies whose job was lost
        cron(prune, minute={7}, second={0}),  # hourly: retention (OPSCEND_RETENTION_DAYS)
    ]
    if settings.public_demo:
        # Delete idle visitors' sandboxes and rebuild stale sample data.
        jobs.append(cron(refresh_demo, **every(DEMO_REFRESH_SECONDS, at_second=10)))
    return jobs


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()


async def shutdown(ctx: dict[str, Any]) -> None:
    await dispose_all()


class WorkerSettings:
    functions: ClassVar = list(JOBS.values())
    cron_jobs: ClassVar = build_cron_jobs()
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379")
    max_jobs = 10
    job_timeout = int(model_job_timeout().total_seconds())  # 5 min; 30 with a self-hosted model
