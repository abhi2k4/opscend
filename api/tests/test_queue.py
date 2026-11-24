"""Model jobs get their own slots, so they cannot hold up deploy events."""

import asyncio
from typing import Any

from app import worker
from app.core.queue import AI_JOBS, AI_QUEUE_NAME, ArqQueue, InlineQueue
from app.jobs import JOBS


class FakePool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def enqueue_job(self, name: str, *args: Any, _queue_name: str | None = None, **_: Any):
        self.calls.append((name, _queue_name))


async def test_arq_sends_model_jobs_to_their_own_queue():
    queue = ArqQueue("redis://unused")
    queue._pool = FakePool()
    for name in ("process_event", "investigate", "chat_reply", "sync_integration"):
        await queue.enqueue(name, "id")
    assert queue._pool.calls == [
        ("process_event", None),
        ("investigate", AI_QUEUE_NAME),
        ("chat_reply", AI_QUEUE_NAME),
        ("sync_integration", None),
    ]


async def test_inline_runs_at_most_ai_concurrency_model_jobs_at_once():
    running = {"ai": 0, "peak": 0}
    release = asyncio.Event()
    events: list[str] = []

    async def model_job(ctx: dict[str, Any], *_: Any) -> None:
        running["ai"] += 1
        running["peak"] = max(running["peak"], running["ai"])
        await release.wait()
        running["ai"] -= 1

    async def event_job(ctx: dict[str, Any], event_id: str) -> None:
        events.append(event_id)

    queue = InlineQueue(
        {"investigate": model_job, "chat_reply": model_job, "process_event": event_job},
        ai_concurrency=2,
    )
    for _ in range(5):
        await queue.enqueue("investigate", "x")
    await queue.enqueue("chat_reply", "y")
    await queue.enqueue("process_event", "evt_1")
    for _ in range(5):
        await asyncio.sleep(0)

    assert running == {"ai": 2, "peak": 2}  # four model jobs wait for a slot
    assert events == ["evt_1"]  # the deploy event did not wait behind them
    release.set()
    await queue.drain()
    assert running == {"ai": 0, "peak": 2}


async def test_worker_consumes_the_ai_queue_with_its_own_slots(env, monkeypatch):
    env.setenv("OPSCEND_AI_CONCURRENCY", "2")
    started: list[Any] = []
    closed: list[Any] = []

    async def fake_run(self) -> None:  # no Redis in tests
        started.append(self)

    async def fake_close(self) -> None:
        closed.append(self)

    monkeypatch.setattr(worker.Worker, "async_run", fake_run)
    monkeypatch.setattr(worker.Worker, "close", fake_close)
    monkeypatch.setattr(worker, "dispose_all", lambda: asyncio.sleep(0))

    ctx: dict[str, Any] = {}
    await worker.startup(ctx)
    await asyncio.sleep(0)
    ai_worker = ctx["ai_worker"]
    assert started == [ai_worker]
    assert ai_worker.queue_name == AI_QUEUE_NAME
    assert set(ai_worker.functions) == set(AI_JOBS)
    assert ai_worker.max_jobs == 2
    # The main worker still knows every job, so model jobs queued before an upgrade run.
    assert {f.__name__ for f in worker.WorkerSettings.functions} == set(JOBS)

    await worker.shutdown(ctx)
    assert closed == [ai_worker]
