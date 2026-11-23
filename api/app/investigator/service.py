"""Starting investigations: the checks and bookkeeping before the job is queued."""

import logging
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.queue import get_queue
from app.core.time import utcnow
from app.models import Deployment, Incident, Investigation

log = logging.getLogger(__name__)

NOT_CONFIGURED = (
    "The AI investigator is not configured. Set GROQ_API_KEY in .env "
    "(free key at https://console.groq.com/keys) and restart the API."
)


async def start_investigation(
    session: AsyncSession,
    *,
    deployment: Deployment | None = None,
    incident_id: str | None = None,
    service_name: str | None = None,
) -> Investigation:
    """Create a queued investigation and enqueue its job.

    Raises HTTP 409 when no LLM key is configured. If one is already queued or
    running for the same target it is returned instead of starting a second.
    """
    settings = get_settings()
    if not settings.ai_configured:
        raise HTTPException(409, NOT_CONFIGURED)

    target = (
        Investigation.deployment_id == deployment.id
        if deployment is not None
        else Investigation.incident_id == incident_id
    )
    active = await session.scalar(
        select(Investigation)
        .where(target, Investigation.status.in_(("queued", "running")))
        .limit(1)
    )
    if active is not None:
        return active

    investigation = Investigation(
        deployment_id=deployment.id if deployment else None,
        incident_id=incident_id,
        service_name=deployment.service.name if deployment else service_name,
        model=settings.ai_model_name,
    )
    session.add(investigation)
    await session.commit()
    await session.refresh(investigation, ["steps"])
    await get_queue().enqueue("investigate", investigation.id)
    return investigation


async def auto_investigate(session: AsyncSession, incident: Incident) -> Investigation | None:
    """Investigate a freshly opened deploy incident without waiting for a click.

    Does nothing when it is switched off, no LLM key is set, the deploy already has
    an investigation, or today's cap is used up (the cap counts every investigation
    of the last 24 hours, so a burst of failures cannot drain the LLM quota).
    """
    settings = get_settings()
    if not (settings.auto_investigate and settings.ai_configured and incident.deployment_id):
        return None
    deployment = await session.get(Deployment, incident.deployment_id)
    if deployment is None:
        return None
    already = await session.scalar(
        select(Investigation.id).where(Investigation.deployment_id == deployment.id).limit(1)
    )
    if already is not None:
        return None
    recent = await session.scalar(
        select(func.count(Investigation.id)).where(
            Investigation.created_at >= utcnow() - timedelta(hours=24)
        )
    )
    # The cap protects an LLM quota; a simulated run uses none.
    if not settings.ai_simulated and (recent or 0) >= settings.auto_investigate_daily_limit:
        log.info("auto-investigation skipped for %s: daily limit reached", incident.id)
        return None
    return await start_investigation(session, deployment=deployment, incident_id=incident.id)
