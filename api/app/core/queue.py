"""Job queue abstraction.

With `REDIS_URL` set, jobs go to arq and run in the worker (`app/worker.py`).
Without it, the very same job functions run inline as asyncio tasks inside the API
process, including the periodic ones, so Opscend needs no infrastructure to run.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from app.core.config import get_settings
from app.core.db import current_sandbox

log = logging.getLogger(__name__)

Job = Callable[..., Awaitable[Any]]

#: Jobs that call the model. They can run for minutes (30 with a self-hosted model),
#: so they get their own slots, OPSCEND_AI_CONCURRENCY of them: a burst of failed
#: deploys cannot fill every worker slot with investigations while the deploy events
#: that come next wait, and a local model server is not sent more than it can serve.
AI_JOBS = frozenset({"investigate", "chat_reply"})
#: The arq queue for AI_JOBS (app/worker.py consumes it next to the default queue).
AI_QUEUE_NAME = "arq:queue:ai"


class JobQueue(Protocol):
    kind: str

    async def enqueue(self, name: str, *args: Any) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class InlineQueue:
    """Runs jobs as background tasks in this process."""

    kind = "inline"

    def __init__(
        self,
        jobs: dict[str, Job],
        periodic: dict[str, int] | None = None,
        ai_concurrency: int = 3,
    ) -> None:
        self._jobs = jobs
        self._periodic = periodic or {}
        self._ai_slots = asyncio.Semaphore(ai_concurrency)
        self._tasks: set[asyncio.Task[Any]] = set()
        self._loops: list[asyncio.Task[None]] = []

    async def enqueue(self, name: str, *args: Any) -> None:
        # The task copies the current context, so a job enqueued from inside a demo
        # sandbox runs in that sandbox.
        task = asyncio.create_task(self._run(name, *args), name=f"job:{name}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, name: str, *args: Any) -> None:
        if name in AI_JOBS:
            async with self._ai_slots:  # extra model jobs wait here, nothing else does
                await self._call(name, *args)
        else:
            await self._call(name, *args)

    async def _call(self, name: str, *args: Any) -> None:
        try:
            await self._jobs[name]({}, *args)
        except Exception:
            log.exception("job %s failed", name)

    async def _every(self, name: str, seconds: int) -> None:
        while True:
            await asyncio.sleep(seconds)
            await self._run(name)

    async def start(self) -> None:
        self._loops = [
            asyncio.create_task(self._every(name, seconds), name=f"cron:{name}")
            for name, seconds in self._periodic.items()
        ]

    async def drain(self) -> None:
        """Wait until every enqueued job has finished (used by tests and shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def stop(self) -> None:
        for task in [*self._loops, *self._tasks]:
            task.cancel()
        await asyncio.gather(*self._loops, *self._tasks, return_exceptions=True)
        self._loops.clear()


class ArqQueue:
    """Hands jobs to the arq worker through Redis."""

    kind = "arq"

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._pool: Any = None

    async def start(self) -> None:
        from arq import create_pool
        from arq.connections import RedisSettings

        self._pool = await create_pool(RedisSettings.from_dsn(self._redis_url))

    async def enqueue(self, name: str, *args: Any) -> None:
        # The worker is another process: tell it which demo sandbox the job belongs to.
        sandbox = current_sandbox()
        extra = {"sandbox": sandbox} if sandbox else {}
        queue_name = AI_QUEUE_NAME if name in AI_JOBS else None  # None: the default queue
        await self._pool.enqueue_job(name, *args, _queue_name=queue_name, **extra)

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()


_queue: JobQueue | None = None


def init_queue(jobs: dict[str, Job], periodic: dict[str, int]) -> JobQueue:
    """Create the process-wide queue for the configured backend."""
    global _queue
    settings = get_settings()
    if settings.redis_url:
        _queue = ArqQueue(settings.redis_url)
    else:
        _queue = InlineQueue(
            jobs, periodic if settings.background_jobs else None, settings.ai_concurrency
        )
    return _queue


def get_queue() -> JobQueue:
    if _queue is None:
        raise RuntimeError("job queue is not initialised")
    return _queue
