"""Build API schemas from ORM rows (the read side shared by routes and the investigator)."""

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.core.time import duration_ms, utcnow
from app.incidents.memory import LOOKBACK

HEALTH_HISTORY = 24


def monitored_service_ids() -> Select[tuple[str]]:
    """Subquery of the services the user has left monitoring on for.

    Everything the console lists is narrowed with it, so a service that was turned
    off disappears from every view while its history stays in the database.
    """
    return select(models.Service.id).where(models.Service.monitored.is_(True))


async def service_out(session: AsyncSession, service: models.Service) -> schemas.Service:
    checks = (
        await session.scalars(
            select(models.HealthCheck)
            .where(models.HealthCheck.service_id == service.id)
            .order_by(models.HealthCheck.checked_at.desc())
            .limit(HEALTH_HISTORY)
        )
    ).all()
    last_deploy = await session.scalar(
        select(models.Deployment)
        .where(models.Deployment.service_id == service.id)
        .order_by(models.Deployment.started_at.desc())
        .limit(1)
    )
    latest = checks[0] if checks else None
    return schemas.Service(
        id=service.id,
        integration_id=service.integration_id,
        provider=service.provider,
        external_id=service.external_id,
        name=service.name,
        repo=service.repo,
        health_url=service.health_url or None,
        health="unknown" if latest is None else ("up" if latest.ok else "down"),
        latency_ms=latest.latency_ms if latest else None,
        health_history=[schemas.HealthPoint.model_validate(c) for c in reversed(checks)],
        last_deploy_status=last_deploy.status if last_deploy else None,
        last_deploy_at=last_deploy.started_at if last_deploy else None,
        pinned=bool(service.pinned),
        muted=bool(service.muted),
        monitored=bool(service.monitored),
    )


def deployment_out(deployment: models.Deployment) -> schemas.Deployment:
    return schemas.Deployment(
        id=deployment.id,
        service_id=deployment.service_id,
        service_name=deployment.service.name,
        provider=deployment.provider,
        external_id=deployment.external_id,
        status=deployment.status,
        commit_sha=deployment.commit_sha,
        commit_message=deployment.commit_message,
        commit_author=deployment.commit_author,
        branch=deployment.branch,
        environment=deployment.environment,
        started_at=deployment.started_at,
        finished_at=deployment.finished_at,
        duration_ms=duration_ms(deployment.started_at, deployment.finished_at),
        url=deployment.url,
    )


async def latest_investigation_id(
    session: AsyncSession, *, deployment_id: str | None = None, incident_id: str | None = None
) -> str | None:
    conditions = []
    if deployment_id:
        conditions.append(models.Investigation.deployment_id == deployment_id)
    if incident_id:
        conditions.append(models.Investigation.incident_id == incident_id)
    if not conditions:
        return None
    return await session.scalar(
        select(models.Investigation.id)
        .where(or_(*conditions))
        .order_by(models.Investigation.created_at.desc())
        .limit(1)
    )


async def incident_out(session: AsyncSession, incident: models.Incident) -> schemas.Incident:
    return schemas.Incident(
        id=incident.id,
        service_id=incident.service_id,
        service_name=incident.service.name,
        provider=incident.service.provider,
        trigger=incident.trigger,
        status=incident.status,
        title=incident.title,
        deployment_id=incident.deployment_id,
        investigation_id=await latest_investigation_id(
            session, deployment_id=incident.deployment_id, incident_id=incident.id
        ),
        opened_at=incident.opened_at,
        resolved_at=incident.resolved_at,
        times_seen=await _times_seen(session, incident),
        resolved_by_deployment_id=incident.resolved_by_deployment_id,
        fix_kind=incident.fix_kind,
    )


async def _times_seen(session: AsyncSession, incident: models.Incident) -> int:
    if not incident.signature:
        return 1
    count = await session.scalar(
        select(func.count()).where(
            models.Incident.signature == incident.signature,
            models.Incident.opened_at >= utcnow() - LOOKBACK,
        )
    )
    return max(1, count or 0)


def investigation_out(investigation: models.Investigation) -> schemas.Investigation:
    return schemas.Investigation(
        id=investigation.id,
        deployment_id=investigation.deployment_id,
        incident_id=investigation.incident_id,
        service_name=investigation.service_name,
        status=investigation.status,
        error=investigation.error,
        model=investigation.model,
        tokens_used=investigation.tokens_used,
        duration_ms=duration_ms(investigation.created_at, investigation.finished_at),
        created_at=investigation.created_at,
        finished_at=investigation.finished_at,
        report=investigation.report,
        feedback=(
            schemas.InvestigationFeedback(
                rating=investigation.feedback_rating,
                note=investigation.feedback_note,
                at=investigation.feedback_at,
            )
            if investigation.feedback_rating and investigation.feedback_at
            else None
        ),
        steps=[schemas.InvestigationStep.model_validate(step) for step in investigation.steps],
    )


async def find_commit(session: AsyncSession, sha: str | None) -> models.Commit | None:
    if not sha:
        return None
    return await session.scalar(select(models.Commit).where(models.Commit.sha == sha).limit(1))
