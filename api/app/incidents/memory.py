"""Incident memory: has this failure happened before, and what made it go away?

Each incident gets a fingerprint of its error (fingerprint.py). Past incidents with the
same fingerprint, the same kind of error, or a similar error text are its matches, and
a resolved match says which deploy resolved it (rules.py records that).

A match is a hint for the reader and the investigator, never evidence about the
current failure: the current deploy's own logs decide.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.core.time import utcnow
from app.incidents import fingerprint
from app.integrations.base import ProviderError
from app.models import Deployment, Incident
from app.services import logs

log = logging.getLogger(__name__)

LOOKBACK = timedelta(days=180)
MAX_CANDIDATES = 500
# Below this word overlap of the headlines, two errors are different errors. The demo's
# CACHE_URL and STRIPE_WEBHOOK_SECRET headlines overlap by 0.71, its unrelated ones by
# less than 0.15.
MIN_TEXT_SIMILARITY = 0.5
# How many incidents without a fingerprint one run of the job looks at, and for how
# long it keeps trying (a provider that is down must not be asked forever).
BATCH = 20
RETRY_WINDOW = timedelta(days=2)

MatchKind = Literal["signature", "family", "text"]
FixKind = Literal["redeploy", "rollback", "code_change"]


@dataclass(frozen=True)
class Match:
    incident: Incident
    kind: MatchKind  # same error, same kind of error, or similar text
    score: float


async def classify_fix(
    session: AsyncSession, failed: Deployment, fix: Deployment
) -> FixKind | None:
    """How the deploy that resolved an incident differs from the one that failed."""
    if not failed.commit_sha or not fix.commit_sha:
        return None
    if fix.commit_sha == failed.commit_sha:
        return "redeploy"  # same code: the cause was config, infra or a flake
    went_back = await session.scalar(
        select(Deployment.id)
        .where(
            Deployment.service_id == fix.service_id,
            Deployment.status == "ready",
            Deployment.commit_sha == fix.commit_sha,
            Deployment.started_at < failed.started_at,
        )
        .limit(1)
    )
    return "rollback" if went_back else "code_change"


async def remember(session: AsyncSession, incident: Incident) -> bool:
    """Store the fingerprint of a deploy incident from its logs. True when stored.

    Idempotent: an incident that was already looked at is left alone. Health incidents
    are fingerprinted when they open (rules.py), they have no logs.
    """
    if incident.signature is not None or incident.deployment_id is None:
        return False
    deployment = await session.get(Deployment, incident.deployment_id)
    if deployment is None:
        return False
    lines = []
    for kind in ("build", "runtime"):
        try:
            lines += [
                (row.level, row.message) for row in await logs.get_logs(session, deployment, kind)
            ]
        except ProviderError as exc:  # no logs now: leave it for the next run
            log.info("no %s logs for %s yet: %s", kind, deployment.id, exc)
            return False
    found = fingerprint.from_logs(lines)
    # "" marks "looked, nothing usable", so the job does not fetch the logs again.
    incident.signature = found.signature if found else ""
    incident.family = found.family if found else ""
    incident.error_text = found.error_text if found else None
    await session.commit()
    return found is not None


async def remember_pending() -> int:
    """Job: fingerprint recent deploy incidents that have none yet. Returns how many."""
    async with session_scope() as session:
        pending = (
            await session.scalars(
                select(Incident)
                .where(
                    Incident.signature.is_(None),
                    Incident.deployment_id.is_not(None),
                    Incident.opened_at >= utcnow() - RETRY_WINDOW,
                )
                .order_by(Incident.opened_at.desc())
                .limit(BATCH)
            )
        ).all()
        stored = 0
        for incident in pending:
            try:
                stored += await remember(session, incident)
            except Exception:  # one incident's logs must not stop the others
                log.exception("could not fingerprint incident %s", incident.id)
                await session.rollback()
        return stored


def _score(incident: Incident, other: Incident) -> tuple[MatchKind, float] | None:
    if other.signature == incident.signature:
        kind, score = "signature", 1.0
    elif other.family == incident.family:
        kind, score = "family", 0.8
    else:
        overlap = fingerprint.similarity(incident.error_text or "", other.error_text or "")
        if overlap < MIN_TEXT_SIMILARITY:
            return None
        kind, score = "text", 0.6 * overlap
    if other.service_id == incident.service_id:
        score += 0.05  # the same service failing the same way is the stronger hint
    return kind, round(score, 3)


async def similar(session: AsyncSession, incident: Incident, limit: int = 5) -> list[Match]:
    """Earlier incidents that look like this one, best first."""
    if not incident.signature:
        return []
    candidates = (
        await session.scalars(
            select(Incident)
            .where(
                Incident.id != incident.id,
                Incident.opened_at < incident.opened_at,
                Incident.opened_at >= incident.opened_at - LOOKBACK,
                Incident.signature.is_not(None),
                Incident.signature != "",
            )
            .order_by(Incident.opened_at.desc())
            .limit(MAX_CANDIDATES)
        )
    ).all()
    matches = []
    for other in candidates:
        scored = _score(incident, other)
        if scored is not None:
            matches.append(Match(other, *scored))
    # Best score first, the most recent first among equals (sorted() is stable).
    matches.sort(key=lambda match: match.score, reverse=True)
    return matches[:limit]
