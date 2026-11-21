"""Overview, services and the merged timeline."""

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app import models, schemas
from app.core.time import utcnow
from app.services.presenters import deployment_out, incident_out, service_out

from .deps import SessionDep, get_or_404

router = APIRouter(tags=["overview"])


async def _services(session: SessionDep) -> list[schemas.Service]:
    rows = await session.scalars(select(models.Service).order_by(models.Service.name))
    return [await service_out(session, row) for row in rows.all()]


@router.get("/services")
async def list_services(session: SessionDep) -> list[schemas.Service]:
    return await _services(session)


class ServiceUpdate(BaseModel):
    health_url: str | None


@router.patch("/services/{service_id}")
async def update_service(
    service_id: str, body: ServiceUpdate, session: SessionDep
) -> schemas.Service:
    """Set the URL the uptime checker probes for this service.

    A URL turns checks on for that address. An empty string turns them off and keeps
    them off. `null` goes back to automatic: the provider's own URL on the next sync.
    """
    service = await get_or_404(session, models.Service, service_id)
    if body.health_url is None:
        service.health_url = None
    else:
        url = body.health_url.strip()
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(422, "The health URL must start with http:// or https://")
        service.health_url = url
    await session.commit()
    return await service_out(session, service)


@router.get("/overview")
async def overview(session: SessionDep) -> schemas.Overview:
    now = utcnow()
    day_ago = now - timedelta(hours=24)
    services = await _services(session)

    recent = (
        await session.scalars(
            select(models.Deployment)
            .where(models.Deployment.started_at >= day_ago)
            .order_by(models.Deployment.started_at.desc())
        )
    ).all()
    first_hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    buckets = [
        schemas.ActivityBucket(hour=first_hour + timedelta(hours=i), ready=0, failed=0)
        for i in range(24)
    ]
    for deployment in recent:
        index = int((deployment.started_at - first_hour).total_seconds() // 3600)
        if 0 <= index < 24 and deployment.status in ("ready", "failed"):
            bucket = buckets[index]
            setattr(bucket, deployment.status, getattr(bucket, deployment.status) + 1)

    open_incidents = (
        await session.scalars(
            select(models.Incident)
            .where(models.Incident.status == "open")
            .order_by(models.Incident.opened_at.desc())
        )
    ).all()
    latest = (
        await session.scalars(
            select(models.Deployment).order_by(models.Deployment.started_at.desc()).limit(20)
        )
    ).all()
    investigations = await session.scalar(select(func.count(models.Investigation.id)))

    return schemas.Overview(
        stats=schemas.OverviewStats(
            services=len(services),
            services_down=sum(1 for service in services if service.health == "down"),
            deploys_24h=len(recent),
            failed_24h=sum(1 for deployment in recent if deployment.status == "failed"),
            open_incidents=len(open_incidents),
            investigations=investigations or 0,
        ),
        services=services,
        incidents=[await incident_out(session, incident) for incident in open_incidents],
        deployments=[deployment_out(deployment) for deployment in latest],
        activity=buckets,
    )


@router.get("/timeline")
async def timeline(
    session: SessionDep,
    limit: int = Query(100, ge=1, le=500),
    provider: str | None = None,
    status: schemas.DeployStatus | None = None,
    service_id: str | None = None,
) -> list[schemas.TimelineItem]:
    """Deployments, GitHub commits and incidents on one axis, newest first.

    `status` is a deploy status, so it narrows the timeline to deployments.
    """
    provider, service = provider or None, None
    if service_id:
        service = await get_or_404(session, models.Service, service_id)
    items: list[schemas.DeploymentItem | schemas.CommitItem | schemas.IncidentItem] = []

    query = select(models.Deployment).order_by(models.Deployment.started_at.desc()).limit(limit)
    if provider:
        query = query.where(models.Deployment.provider == provider)
    if status:
        query = query.where(models.Deployment.status == status)
    if service:
        query = query.where(models.Deployment.service_id == service.id)
    for deployment in (await session.scalars(query)).all():
        items.append(
            schemas.DeploymentItem(
                id=deployment.id,
                at=deployment.started_at,
                provider=deployment.provider,
                deployment=deployment_out(deployment),
            )
        )

    if not status and provider in (None, "github"):
        query = select(models.Commit).order_by(models.Commit.committed_at.desc()).limit(limit)
        if service:
            query = query.where(models.Commit.repo == service.repo)
        for commit in (await session.scalars(query)).all():
            items.append(
                schemas.CommitItem(
                    id=commit.id,
                    at=commit.committed_at,
                    commit=schemas.Commit.model_validate(commit),
                )
            )

    if not status and provider != "github":
        query = select(models.Incident).order_by(models.Incident.opened_at.desc()).limit(limit)
        if service:
            query = query.where(models.Incident.service_id == service.id)
        if provider:
            query = query.join(models.Service).where(models.Service.provider == provider)
        for incident in (await session.scalars(query)).all():
            items.append(
                schemas.IncidentItem(
                    id=incident.id,
                    at=incident.opened_at,
                    provider=incident.service.provider,
                    incident=await incident_out(session, incident),
                )
            )

    items.sort(key=lambda item: item.at, reverse=True)
    return items[:limit]
