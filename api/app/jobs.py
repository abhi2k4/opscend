"""Job functions shared by the arq worker and the inline queue.

Each takes the arq-style `ctx` first so the same callable works in both.
"""

import functools
import logging
from typing import Any

from app.chat.orchestrator import run_chat_reply
from app.chat.service import expire_stale_replies
from app.core.config import get_settings
from app.core.db import current_sandbox, use_sandbox
from app.demo import sandbox as demo_sandbox
from app.demo.seed import refresh_public_demo
from app.incidents.health import run_health_checks
from app.ingest import normalizer, poller
from app.investigator.orchestrator import run_investigation
from app.investigator.service import expire_stale_investigations
from app.notifications.email import deliver_pending
from app.services.retention import prune_old_data

log = logging.getLogger(__name__)


async def process_event(ctx: dict[str, Any], event_id: str) -> None:
    await normalizer.process_raw_event(event_id)


async def investigate(ctx: dict[str, Any], investigation_id: str) -> None:
    await run_investigation(investigation_id)


async def chat_reply(ctx: dict[str, Any], message_id: str) -> None:
    await run_chat_reply(message_id)


async def expire_chat_replies(ctx: dict[str, Any]) -> None:
    await expire_stale_replies()


async def expire_investigations(ctx: dict[str, Any]) -> None:
    await expire_stale_investigations()


async def prune(ctx: dict[str, Any]) -> None:
    await prune_old_data()


async def sync_integration(
    ctx: dict[str, Any], integration_id: str, backfill: list[str] | None = None
) -> None:
    await poller.sync_integration(integration_id, backfill)


async def reconcile(ctx: dict[str, Any]) -> None:
    await poller.reconcile()


async def health_checks(ctx: dict[str, Any]) -> None:
    await run_health_checks()


async def refresh_demo(ctx: dict[str, Any]) -> None:
    await refresh_public_demo()


async def deliver_notifications(ctx: dict[str, Any]) -> None:
    await deliver_pending()


# In the public demo these look after every visitor's sandbox, not only the shared data.
PER_SANDBOX = {"reconcile", "health_checks", "expire_chat_replies", "expire_investigations"}


def _sandboxed(job: Any) -> Any:
    """Run a job in the demo sandbox it was enqueued from (`sandbox=`, set by the queue).

    A periodic job arrives with no sandbox: in the public demo it then runs once for the
    shared data and once for each sandbox in use.
    """

    @functools.wraps(job)
    async def run(ctx: dict[str, Any], *args: Any, sandbox: str | None = None) -> None:
        if sandbox is not None:
            with use_sandbox(sandbox):
                await job(ctx, *args)
            return
        await job(ctx, *args)
        if current_sandbox() is None and job.__name__ in PER_SANDBOX and _public_demo():
            for name in await demo_sandbox.active():
                try:
                    with use_sandbox(name):
                        await job(ctx, *args)
                except Exception:  # one visitor's sandbox must not stop the others
                    log.exception("%s failed in sandbox %s", job.__name__, name)

    return run


def _public_demo() -> bool:
    return get_settings().public_demo


process_event = _sandboxed(process_event)
investigate = _sandboxed(investigate)
chat_reply = _sandboxed(chat_reply)
sync_integration = _sandboxed(sync_integration)
reconcile = _sandboxed(reconcile)
health_checks = _sandboxed(health_checks)
expire_chat_replies = _sandboxed(expire_chat_replies)
expire_investigations = _sandboxed(expire_investigations)

JOBS = {
    job.__name__: job
    for job in (
        process_event,
        investigate,
        chat_reply,
        sync_integration,
        reconcile,
        health_checks,
        deliver_notifications,
        expire_chat_replies,
        expire_investigations,
        prune,
        refresh_demo,
    )
}


def periodic_jobs() -> dict[str, int]:
    """Job name → interval in seconds, for the inline queue's timers."""
    settings = get_settings()
    jobs = {"refresh_demo": 300} if settings.public_demo else {}
    return {
        **jobs,
        "reconcile": max(30, settings.poll_interval_seconds),
        "health_checks": max(30, settings.health_interval_seconds),
        "deliver_notifications": 15,
        "expire_chat_replies": 60,
        "expire_investigations": 60,
        "prune": 3600,
    }
