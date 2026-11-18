"""Job functions shared by the arq worker and the inline queue.

Each takes the arq-style `ctx` first so the same callable works in both.
"""

from typing import Any

from app.core.config import get_settings
from app.incidents.health import run_health_checks
from app.ingest import normalizer, poller
from app.investigator.orchestrator import run_investigation


async def process_event(ctx: dict[str, Any], event_id: str) -> None:
    await normalizer.process_raw_event(event_id)


async def investigate(ctx: dict[str, Any], investigation_id: str) -> None:
    await run_investigation(investigation_id)


async def sync_integration(ctx: dict[str, Any], integration_id: str) -> None:
    await poller.sync_integration(integration_id)


async def reconcile(ctx: dict[str, Any]) -> None:
    await poller.reconcile()


async def health_checks(ctx: dict[str, Any]) -> None:
    await run_health_checks()


JOBS = {
    job.__name__: job
    for job in (process_event, investigate, sync_integration, reconcile, health_checks)
}


def periodic_jobs() -> dict[str, int]:
    """Job name → interval in seconds, for the inline queue's timers."""
    settings = get_settings()
    return {
        "reconcile": max(30, settings.poll_interval_seconds),
        "health_checks": max(30, settings.health_interval_seconds),
    }
