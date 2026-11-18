"""Starting investigations: the checks and bookkeeping before the job is queued."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.queue import get_queue
from app.models import Deployment, Investigation

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
        model=settings.ai_model,
    )
    session.add(investigation)
    await session.commit()
    await session.refresh(investigation, ["steps"])
    await get_queue().enqueue("investigate", investigation.id)
    return investigation
