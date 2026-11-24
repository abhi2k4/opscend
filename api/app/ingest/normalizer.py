"""Turn stored raw events into deployments and commits, idempotently."""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.core.queue import get_queue
from app.core.time import utcnow
from app.incidents import rules
from app.integrations.base import CommitIn, DeploymentIn, NormalizedBatch
from app.integrations.registry import get_adapter_class
from app.investigator.service import auto_investigate
from app.models import Commit, Deployment, Incident, RawEvent, Service

log = logging.getLogger(__name__)

POLL_PREFIX = "poll."
TERMINAL = ("ready", "failed", "canceled")
_RANK = {"queued": 0, "building": 1, "ready": 2, "failed": 2, "canceled": 2}

# One normalization at a time per process keeps select-then-insert upserts simple;
# the unique constraints plus one retry cover a second worker process.
_lock = asyncio.Lock()


def batch_for(event: RawEvent) -> NormalizedBatch:
    """Poll results are stored already normalized; webhooks go through their adapter."""
    if event.event_type.startswith(POLL_PREFIX):
        return NormalizedBatch.model_validate(event.payload)
    adapter_cls = get_adapter_class(event.provider)
    if adapter_cls is None:
        return NormalizedBatch()
    return adapter_cls.normalize(event.event_type, event.payload)


async def process_raw_event(event_id: str) -> None:
    """Job: normalize one raw event. Safe to run more than once for the same event."""
    async with _lock, session_scope() as session:
        event = await session.get(RawEvent, event_id)
        if event is None or event.duplicate or event.processed_at is not None:
            return
        provider, error = event.provider, None
        try:
            batch = batch_for(event)
            try:
                await apply_batch(session, provider, batch)
            except IntegrityError:
                await session.rollback()
                await apply_batch(session, provider, batch)
        except Exception as exc:  # a bad payload must not poison the queue
            await session.rollback()
            log.exception("failed to normalize raw event %s", event_id)
            error = f"{type(exc).__name__}: {exc}"[:500]
        event = await session.get(RawEvent, event_id)
        if event is not None:
            event.processed_at = utcnow()
            event.error = error
            await session.commit()


async def apply_batch(session: AsyncSession, provider: str, batch: NormalizedBatch) -> None:
    for commit in batch.commits:
        await _upsert_commit(session, commit)
    opened: list[Incident] = []
    for incoming in sorted(batch.deployments, key=lambda d: d.started_at):
        deployment = await _upsert_deployment(session, provider, incoming)
        if deployment is not None:
            incident = await rules.on_deployment(session, deployment)
            if incident is not None:
                opened.append(incident)
    await session.commit()
    # Only once the incident is stored: the jobs read it from the database.
    for incident in opened:
        try:
            await auto_investigate(session, incident)
        except Exception:  # an investigation that cannot start must not fail ingestion
            log.exception("could not start an automatic investigation for %s", incident.id)
    if opened:
        try:  # fingerprint the new incidents' errors (incidents/memory.py)
            await get_queue().enqueue("remember_incidents")
        except Exception:  # the periodic run picks them up later
            log.exception("could not start remembering %d incidents", len(opened))


async def _upsert_commit(session: AsyncSession, incoming: CommitIn) -> None:
    exists = await session.scalar(
        select(Commit.id).where(Commit.repo == incoming.repo, Commit.sha == incoming.sha)
    )
    if exists is None:
        session.add(Commit(**incoming.model_dump()))
        await session.flush()


async def _upsert_deployment(
    session: AsyncSession, provider: str, incoming: DeploymentIn
) -> Deployment | None:
    service = await session.scalar(
        select(Service).where(
            Service.provider == provider, Service.external_id == incoming.service_external_id
        )
    )
    if service is None:
        log.info("skipping %s deployment for an unknown service", provider)
        return None
    if not service.monitored:
        # The user turned monitoring off for it: webhooks keep arriving, nothing is stored.
        return None

    deployment = await session.scalar(
        select(Deployment).where(
            Deployment.provider == provider, Deployment.external_id == incoming.external_id
        )
    )
    fields = incoming.model_dump(exclude={"service_external_id", "external_id"})
    if deployment is None:
        deployment = Deployment(
            service_id=service.id, provider=provider, external_id=incoming.external_id, **fields
        )
        deployment.service = service
        session.add(deployment)
    else:
        _merge(deployment, incoming)
    if deployment.status in TERMINAL and deployment.finished_at is None:
        deployment.finished_at = utcnow()
    await session.flush()
    return deployment


def _merge(deployment: Deployment, incoming: DeploymentIn) -> None:
    """Update in place without ever moving a deployment backwards.

    Webhooks can arrive out of order and carry only the event time, so the earliest
    start wins, a finished deploy never returns to building, and known commit
    details are not blanked by a sparser payload.
    """
    if _RANK[incoming.status] >= _RANK[deployment.status]:
        deployment.status = incoming.status
    deployment.started_at = min(deployment.started_at, incoming.started_at)
    if incoming.finished_at is not None and deployment.status == incoming.status:
        deployment.finished_at = deployment.finished_at or incoming.finished_at
    if deployment.status not in TERMINAL:
        deployment.finished_at = None
    for name in ("commit_sha", "commit_message", "commit_author", "branch", "environment", "url"):
        if (value := getattr(incoming, name)) is not None:
            setattr(deployment, name, value)


async def reprocess_pending(older_than: timedelta = timedelta(minutes=1)) -> int:
    """Normalize stored events whose job never ran (e.g. the process died after storing)."""
    async with session_scope() as session:
        ids = (
            await session.scalars(
                select(RawEvent.id)
                .where(
                    RawEvent.processed_at.is_(None),
                    RawEvent.duplicate.is_(False),
                    RawEvent.received_at < utcnow() - older_than,
                )
                .order_by(RawEvent.received_at)
                .limit(200)
            )
        ).all()
    for event_id in ids:
        await process_raw_event(event_id)
    return len(ids)
