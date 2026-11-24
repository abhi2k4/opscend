"""The uptime checker: one HTTP GET per service with a health URL."""

import asyncio
import ipaddress
import logging
import random
import socket
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
MAX_REDIRECTS = 5
# Cloud metadata endpoints outside the link-local range (Alibaba, AWS over IPv6).
METADATA_ADDRESSES = {
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("fd00:ec2::254"),
}


async def resolve(host: str) -> list[str]:
    """Every address `host` resolves to (an IP literal resolves to itself)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _forbidden(address: str) -> bool:
    """Addresses a health check must never reach: the cloud metadata service (it hands
    out the host's credentials) and ranges that are never a real service. Private and
    loopback addresses stay allowed: a self-hosted install checks its own network."""
    ip = ipaddress.ip_address(address.split("%")[0])  # drop an IPv6 zone id
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_link_local  # 169.254.169.254 and friends
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
        or ip in METADATA_ADDRESSES
    )


async def _blocked(url: httpx.URL) -> bool:
    try:
        addresses = await resolve(url.host)
    except (OSError, UnicodeError):
        return False  # unresolvable: the request itself fails and is recorded as down
    return any(_forbidden(address) for address in addresses)


async def probe(client: httpx.AsyncClient, url: str) -> tuple[int | None, int | None, bool]:
    """Return (status_code, latency_ms, ok). Any 2xx/3xx answer counts as healthy.

    Redirects are followed by hand so every hop is checked against `_forbidden`: a
    monitored site must not be able to send the checker to the metadata service. (A
    DNS answer that changes between the check and the request is not covered; the
    result is only a status code and a latency, never the response body.)
    """
    started = time.perf_counter()
    try:
        request = client.build_request("GET", url)
        for _ in range(MAX_REDIRECTS + 1):
            if await _blocked(request.url):
                log.warning("health check to %s refused: forbidden address", request.url.host)
                return None, None, False
            response = await client.send(request)
            if response.next_request is None:
                break
            request = response.next_request
        else:
            return None, None, False  # too many redirects
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
