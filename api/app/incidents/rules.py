"""When incidents open and resolve.

- A failed deploy opens an incident, unless a newer deploy of the service exists.
- Two consecutive failed health checks open an incident.
- At most one incident is open per service; the rest is deduplicated.
- A deploy incident resolves when a later deploy of the service is ready;
  a health incident resolves on the next passing check.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.models import Deployment, HealthCheck, Incident, Service
from app.notifications import service as notifications

DEPLOY_FAILED = "deploy_failed"
HEALTH_FAILED = "health_check_failed"
FAILURES_TO_OPEN = 2


async def open_incident_for(session: AsyncSession, service_id: str) -> Incident | None:
    return await session.scalar(select(Incident).where(Incident.open_slot == service_id))


async def _open(
    session: AsyncSession,
    service: Service,
    *,
    trigger: str,
    dedup_key: str,
    title: str,
    deployment_id: str | None = None,
) -> Incident | None:
    if await open_incident_for(session, service.id) is not None:
        return None
    if await session.scalar(select(Incident.id).where(Incident.dedup_key == dedup_key)):
        return None
    incident = Incident(
        service_id=service.id,
        trigger=trigger,
        title=title,
        dedup_key=dedup_key,
        open_slot=service.id,
        deployment_id=deployment_id,
    )
    incident.service = service
    try:
        async with session.begin_nested():
            session.add(incident)
    except IntegrityError:  # another worker opened it first
        return None
    notifications.incident_opened(session, incident)
    return incident


def resolve(incident: Incident) -> None:
    incident.status = "resolved"
    incident.open_slot = None
    incident.resolved_at = incident.resolved_at or utcnow()


async def on_deployment(session: AsyncSession, deployment: Deployment) -> Incident | None:
    """Apply the deploy rules after a deployment was created or changed."""
    if deployment.status == "failed":
        newer = await session.scalar(
            select(Deployment.id)
            .where(
                Deployment.service_id == deployment.service_id,
                Deployment.started_at > deployment.started_at,
            )
            .limit(1)
        )
        if newer is not None:
            return None
        sha = f" at {deployment.commit_sha[:7]}" if deployment.commit_sha else ""
        return await _open(
            session,
            deployment.service,
            trigger=DEPLOY_FAILED,
            dedup_key=f"deploy:{deployment.id}",
            title=f"Deploy failed on {deployment.service.name}{sha}",
            deployment_id=deployment.id,
        )

    if deployment.status == "ready":
        incident = await open_incident_for(session, deployment.service_id)
        if incident is None or incident.trigger != DEPLOY_FAILED:
            return None
        failed = (
            await session.get(Deployment, incident.deployment_id)
            if incident.deployment_id
            else None
        )
        if failed is None or (
            failed.id != deployment.id and failed.started_at <= deployment.started_at
        ):
            resolve(incident)
            notifications.incident_resolved(session, incident)
            await session.flush()
    return None


async def on_health_check(
    session: AsyncSession, service: Service, check: HealthCheck
) -> Incident | None:
    """Apply the health rules after a new check was recorded for the service."""
    if check.ok:
        incident = await open_incident_for(session, service.id)
        if incident is not None and incident.trigger == HEALTH_FAILED:
            resolve(incident)
            notifications.incident_resolved(session, incident)
            await session.flush()
        return None

    recent = (
        await session.scalars(
            select(HealthCheck)
            .where(HealthCheck.service_id == service.id)
            .order_by(HealthCheck.checked_at.desc())
            .limit(FAILURES_TO_OPEN)
        )
    ).all()
    if len(recent) < FAILURES_TO_OPEN or any(item.ok for item in recent):
        return None
    return await _open(
        session,
        service,
        trigger=HEALTH_FAILED,
        dedup_key=f"health:{check.id}",
        title=f"{service.name} is failing health checks",
    )
