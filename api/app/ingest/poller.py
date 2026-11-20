"""The polling reconciler: catches whatever webhooks missed.

Poll results take the same road as webhooks: each new deployment state or commit
becomes a `raw_event` (source "poll") and is then normalized, so a state already
seen costs one dedup lookup and nothing else.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.core.time import utcnow
from app.integrations.base import (
    CommitSource,
    NormalizedBatch,
    ProviderAdapter,
    ProviderError,
    RawEventIn,
    ResourceUnavailableError,
    ServiceIn,
)
from app.integrations.connect import adapter_for, service_ref
from app.models import Integration, Service
from app.notifications import service as notifications
from app.schemas import Capability

from .normalizer import process_raw_event, reprocess_pending
from .store import record_event

log = logging.getLogger(__name__)

FIRST_SYNC_WINDOW = timedelta(days=7)
RESYNC_OVERLAP = timedelta(hours=6)


async def sync_integration(integration_id: str) -> None:
    """Job: pull services, deployments and commits for one integration."""
    async with session_scope() as session:
        integration = await session.get(Integration, integration_id)
        if integration is None:
            return
        if integration.is_demo:
            integration.last_synced_at = utcnow()
            await session.commit()
            return
        adapter = adapter_for(integration)
        try:
            skipped = await _sync(session, integration, adapter)
            status, detail = "connected", _skipped_note(skipped)
        except ProviderError as exc:
            await session.rollback()
            status, detail = "error", str(exc)
        finally:
            await adapter.aclose()
        integration = await session.get(Integration, integration_id)
        if integration is not None:
            if status == "error":
                integration.sync_failures += 1
                # Alert on a streak, not on a single network blip, and only once per streak.
                if integration.sync_failures == notifications.SYNC_FAILURES_TO_ALERT:
                    await notifications.integration_error(
                        session, integration, detail or "unknown error"
                    )
            else:
                integration.sync_failures = 0
                integration.last_synced_at = utcnow()
            integration.status, integration.status_detail = status, detail
            await session.commit()


_reconciling = asyncio.Lock()


async def reconcile() -> None:
    """Job (cron): replay events whose job was lost, then sync every real integration."""
    if _reconciling.locked():
        # The previous run is still going (a slow provider): overlapping runs would
        # double every poll and every alert, so this tick is skipped.
        return
    async with _reconciling:
        await _reconcile()


async def _reconcile() -> None:
    await reprocess_pending()
    async with session_scope() as session:
        ids = (
            await session.scalars(select(Integration.id).where(Integration.is_demo.is_(False)))
        ).all()
    for integration_id in ids:
        try:
            await sync_integration(integration_id)
        except Exception:  # one broken integration must not stop the others
            log.exception("sync failed for integration %s", integration_id)


def _skipped_note(skipped: list[str]) -> str | None:
    if not skipped:
        return None
    shown = ", ".join(skipped[:3]) + (f" and {len(skipped) - 3} more" if len(skipped) > 3 else "")
    return f"Connected, but this token cannot read {len(skipped)} linked repo(s): {shown}"


async def _sync(
    session: AsyncSession, integration: Integration, adapter: ProviderAdapter
) -> list[str]:
    """Sync one integration. Returns the resources that were skipped as unreadable."""
    since = (
        integration.last_synced_at - RESYNC_OVERLAP
        if integration.last_synced_at
        else utcnow() - FIRST_SYNC_WINDOW
    )
    provider, integration_id = integration.provider, integration.id
    capabilities = set(integration.capabilities)
    events: list[RawEventIn] = []
    skipped: list[str] = []

    if Capability.LIST_SERVICES in capabilities:
        await _upsert_services(session, integration, await adapter.list_services())
    if Capability.LIST_DEPLOYS in capabilities:
        services = (
            await session.scalars(select(Service).where(Service.integration_id == integration_id))
        ).all()
        for service in services:
            deployments = await adapter.list_deployments(service_ref(service), since)
            # Newest first: during a backfill an old failure then sees its successor
            # and opens no incident (see incidents/rules.py).
            for deployment in sorted(deployments, key=lambda d: d.started_at, reverse=True):
                events.append(
                    RawEventIn(
                        provider=provider,
                        event_type="poll.deployment",
                        dedup_key=f"{provider}:poll:{deployment.external_id}:{deployment.status}",
                        payload=NormalizedBatch(deployments=[deployment]).model_dump(mode="json"),
                    )
                )
    if Capability.COMMITS in capabilities and isinstance(adapter, CommitSource):
        for repo in await _repos(session, adapter):
            try:
                commits = await adapter.list_commits(repo, since)
            except ResourceUnavailableError:
                # One private or empty repo must not fail the whole integration.
                skipped.append(repo)
                continue
            for commit in commits:
                events.append(
                    RawEventIn(
                        provider=provider,
                        event_type="poll.commit",
                        dedup_key=f"{provider}:poll:commit:{repo}:{commit.sha}",
                        payload=NormalizedBatch(commits=[commit]).model_dump(mode="json"),
                    )
                )

    for event in events:
        row = await record_event(session, event, source="poll", keep_duplicate=False)
        if row is not None:
            await process_raw_event(row.id)
    return skipped


async def _repos(session: AsyncSession, adapter: CommitSource) -> list[str]:
    """Repos to watch: the adapter's own list plus every repo a service is linked to."""
    linked = (
        await session.scalars(
            select(Service.repo)
            .join(Integration, Integration.id == Service.integration_id)
            # Demo services point at repos that do not exist on GitHub.
            .where(Service.repo.is_not(None), Integration.is_demo.is_(False))
            .distinct()
        )
    ).all()
    return sorted({*await adapter.list_repos(), *linked})


async def _upsert_services(
    session: AsyncSession, integration: Integration, incoming: list[ServiceIn]
) -> None:
    existing = {
        service.external_id: service
        for service in await session.scalars(
            select(Service).where(Service.provider == integration.provider)
        )
    }
    for item in incoming:
        service = existing.get(item.external_id)
        if service is None:
            session.add(
                Service(
                    integration_id=integration.id,
                    provider=integration.provider,
                    **item.model_dump(),
                )
            )
            continue
        service.integration_id = integration.id
        service.name, service.meta = item.name, item.meta
        service.repo = item.repo or service.repo
        service.health_url = service.health_url or item.health_url
    await session.commit()
