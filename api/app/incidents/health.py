"""The uptime checker: one HTTP GET per service with a health URL."""

import asyncio
import logging
import random
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.incidents import rules
from app.models import HealthCheck, Integration, Service

log = logging.getLogger(__name__)

CHECK_TIMEOUT = httpx.Timeout(10.0)
# Probes run in parallel, so a few slow services cannot push a run past the next tick.
MAX_CONCURRENT_PROBES = 10


async def probe(client: httpx.AsyncClient, url: str) -> tuple[int | None, int | None, bool]:
    """Return (status_code, latency_ms, ok). Any 2xx/3xx answer counts as healthy."""
    started = time.perf_counter()
    try:
        response = await client.get(url, follow_redirects=True)
    except httpx.HTTPError:
        return None, None, False
    latency = int((time.perf_counter() - started) * 1000)
    return response.status_code, latency, response.status_code < 400


def _synthetic() -> tuple[int | None, int | None, bool]:
    """Demo services have no real endpoint, so their checks are simulated as healthy."""
    return 200, random.randint(70, 180), True


async def record_check(
    session: AsyncSession, service: Service, result: tuple[int | None, int | None, bool]
) -> HealthCheck:
    status_code, latency_ms, ok = result
    check = HealthCheck(
        service_id=service.id, status_code=status_code, latency_ms=latency_ms, ok=ok
    )
    session.add(check)
    await session.flush()
    await rules.on_health_check(session, service, check)
    await session.commit()
    return check


async def run_health_checks(client: httpx.AsyncClient | None = None) -> int:
    """Job: check every service that has a health URL. Returns the number checked."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=CHECK_TIMEOUT)
    try:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(Service, Integration.is_demo)
                    .join(Integration, Integration.id == Service.integration_id)
                    # NULL = no URL known, "" = checks turned off for this service.
                    .where(
                        Service.health_url.is_not(None),
                        Service.health_url != "",
                        Service.monitored.is_(True),
                    )
                )
            ).all()
            limit = asyncio.Semaphore(MAX_CONCURRENT_PROBES)

            async def check(url: str, is_demo: bool) -> tuple[int | None, int | None, bool]:
                if is_demo:
                    return _synthetic()
                async with limit:
                    return await probe(client, url)

            # The probes never touch the database. The results are recorded one by one
            # afterwards, because an AsyncSession must not be shared between tasks.
            # Old checks are pruned by services/retention.py (OPSCEND_RETENTION_DAYS).
            results = await asyncio.gather(
                *(check(service.health_url, is_demo) for service, is_demo in rows)
            )
            for (service, _), result in zip(rows, results, strict=True):
                await record_check(session, service, result)
            return len(rows)
    finally:
        if owns_client:
            await client.aclose()
