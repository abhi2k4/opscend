"""The uptime checker: one HTTP GET per service with a health URL."""

import logging
import random
import time
from datetime import timedelta

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.core.time import utcnow
from app.incidents import rules
from app.models import HealthCheck, Integration, Service

log = logging.getLogger(__name__)

CHECK_TIMEOUT = httpx.Timeout(10.0)
RETENTION = timedelta(days=7)


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
                    .where(Service.health_url.is_not(None))
                )
            ).all()
            for service, is_demo in rows:
                result = _synthetic() if is_demo else await probe(client, service.health_url)
                await record_check(session, service, result)
            await session.execute(
                delete(HealthCheck).where(HealthCheck.checked_at < utcnow() - RETENTION)
            )
            await session.commit()
            return len(rows)
    finally:
        if owns_client:
            await client.aclose()
