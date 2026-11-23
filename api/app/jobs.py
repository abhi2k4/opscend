"""Job functions shared by the arq worker and the inline queue.

Each takes the arq-style `ctx` first so the same callable works in both.
"""

from typing import Any

from app.chat.orchestrator import run_chat_reply
from app.chat.service import expire_stale_replies
from app.core.config import get_settings
from app.demo.seed import refresh_public_demo
from app.incidents.health import run_health_checks
from app.ingest import normalizer, poller
from app.investigator.orchestrator import run_investigation
from app.notifications.email import deliver_pending
from app.services.retention import prune_old_data


async def process_event(ctx: dict[str, Any], event_id: str) -> None:
    await normalizer.process_raw_event(event_id)


async def investigate(ctx: dict[str, Any], investigation_id: str) -> None:
    await run_investigation(investigation_id)


async def chat_reply(ctx: dict[str, Any], message_id: str) -> None:
    await run_chat_reply(message_id)


async def expire_chat_replies(ctx: dict[str, Any]) -> None:
    await expire_stale_replies()


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
        "prune": 3600,
    }
