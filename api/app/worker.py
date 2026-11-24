"""arq worker: `uv run arq app.worker.WorkerSettings` (used when REDIS_URL is set).

One process consumes two queues: the default one (deploy events, polling, health
checks, email) with 10 slots, and the AI queue (investigations, chat replies) with
OPSCEND_AI_CONCURRENCY slots, so slow model runs never hold up the rest.
"""

import asyncio
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.worker import Worker

from app.chat.service import job_timeout as model_job_timeout
from app.core.config import get_settings
from app.core.db import dispose_all
from app.core.logging import configure_logging
from app.core.queue import AI_JOBS, AI_QUEUE_NAME
from app.jobs import (
    JOBS,
    deliver_notifications,
    expire_chat_replies,
    health_checks,
    prune,
    reconcile,
)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    # Started from the main worker's startup so the usual `arq app.worker.WorkerSettings`
    # command runs both; it shares this process, its event loop and its signals.
    ai_worker = Worker(
        functions=[JOBS[name] for name in AI_JOBS],
        queue_name=AI_QUEUE_NAME,
        redis_settings=WorkerSettings.redis_settings,
        max_jobs=get_settings().ai_concurrency,
        job_timeout=WorkerSettings.job_timeout,
        handle_signals=False,
    )
    ctx["ai_worker"] = ai_worker
    ctx["ai_worker_task"] = asyncio.create_task(ai_worker.async_run())


async def shutdown(ctx: dict[str, Any]) -> None:
    if ai_worker := ctx.get("ai_worker"):
        await ai_worker.close()  # stops polling, waits for running model jobs
    if task := ctx.get("ai_worker_task"):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await dispose_all()


class WorkerSettings:
    # Every job, model jobs included: ones enqueued on this queue before an upgrade
    # still run. New model jobs go to the AI queue (core/queue.py).
    functions: ClassVar = list(JOBS.values())
    cron_jobs: ClassVar = [
        cron(reconcile, second={0}, run_at_startup=True),  # every 60s: poll for missed webhooks
        cron(health_checks, second={30}),  # every 60s, offset from the poller
        cron(deliver_notifications, second={5, 20, 35, 50}),  # email outbox, every 15s
        cron(expire_chat_replies, second={45}),  # every 60s: fail chat replies whose job was lost
        cron(prune, minute={7}, second={0}),  # hourly: retention (OPSCEND_RETENTION_DAYS)
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379")
    max_jobs = 10
    job_timeout = int(model_job_timeout().total_seconds())  # 5 min; 30 with a self-hosted model
