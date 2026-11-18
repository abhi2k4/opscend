"""Deployment logs with stable ids.

Stored lines (demo data, or a finished deploy's cached logs) are served from the
database. Otherwise the provider is asked, and the answer is cached once the deploy
has finished, so evidence ids in a report keep pointing at the same lines.
"""

import hashlib
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import LogLineIn
from app.integrations.connect import adapter_for, deployment_ref
from app.models import Deployment, Integration, LogLine
from app.schemas import Capability, LogKind

_CAPABILITY = {"build": Capability.BUILD_LOGS, "runtime": Capability.RUNTIME_LOGS}
_FINISHED = ("ready", "failed", "canceled")


def to_rows(deployment_id: str, kind: str, lines: list[LogLineIn], start: int = 0) -> list[LogLine]:
    """Give lines deterministic ids: the same line always hashes to the same id."""
    seen: Counter[str] = Counter()
    rows = []
    for offset, line in enumerate(lines):
        basis = f"{deployment_id}|{kind}|{line.ts.isoformat()}|{line.message}"
        seen[basis] += 1
        digest = hashlib.sha1(f"{basis}|{seen[basis]}".encode()).hexdigest()[:10]  # noqa: S324
        rows.append(
            LogLine(
                id=f"log_{digest}",
                deployment_id=deployment_id,
                kind=kind,
                seq=start + offset,
                ts=line.ts,
                level=line.level,
                message=line.message,
            )
        )
    return rows


async def get_logs(
    session: AsyncSession, deployment: Deployment, kind: LogKind, limit: int = 500
) -> list[LogLine]:
    """Return up to `limit` most recent lines, oldest first. May raise `ProviderError`."""
    stored = (
        await session.scalars(
            select(LogLine)
            .where(LogLine.deployment_id == deployment.id, LogLine.kind == kind)
            .order_by(LogLine.seq.desc())
            .limit(limit)
        )
    ).all()
    if stored:
        return list(reversed(stored))

    integration = await session.get(Integration, deployment.service.integration_id)
    if (
        integration is None
        or integration.is_demo
        or _CAPABILITY[kind] not in integration.capabilities
    ):
        return []
    adapter = adapter_for(integration)
    try:
        fetched = await adapter.get_logs(deployment_ref(deployment), kind, limit)
    finally:
        await adapter.aclose()
    rows = to_rows(deployment.id, kind, fetched)
    if (
        rows
        and deployment.status in _FINISHED
        and (kind == "build" or deployment.status != "ready")
    ):
        # Runtime logs of a live deploy keep growing, so only settled logs are cached.
        session.add_all(rows)
        await session.commit()
    return rows
