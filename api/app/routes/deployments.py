"""Deployments: list, detail, logs, diff, and starting an investigation."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app import models, schemas
from app.integrations.base import ProviderError
from app.investigator.service import start_investigation
from app.services import changes, diffs, logs
from app.services.presenters import (
    deployment_out,
    find_commit,
    investigation_out,
    latest_investigation_id,
    monitored_service_ids,
    service_out,
)

from .deps import SessionDep, get_or_404

router = APIRouter(prefix="/deployments", tags=["deployments"])


@router.get("")
async def list_deployments(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=500),
    status: schemas.DeployStatus | None = None,
    provider: str | None = None,
) -> list[schemas.Deployment]:
    query = (
        select(models.Deployment)
        .where(models.Deployment.service_id.in_(monitored_service_ids()))
        .order_by(models.Deployment.started_at.desc())
        .limit(limit)
    )
    if status:
        query = query.where(models.Deployment.status == status)
    if provider:
        query = query.where(models.Deployment.provider == provider)
    return [deployment_out(row) for row in (await session.scalars(query)).all()]


@router.get("/{deployment_id}")
async def get_deployment(deployment_id: str, session: SessionDep) -> schemas.DeploymentDetail:
    deployment = await get_or_404(session, models.Deployment, deployment_id)
    integration = await session.get(models.Integration, deployment.service.integration_id)
    commit = await find_commit(session, deployment.commit_sha)
    incident_id = await session.scalar(
        select(models.Incident.id)
        .where(models.Incident.deployment_id == deployment.id)
        .order_by(models.Incident.opened_at.desc())
        .limit(1)
    )
    return schemas.DeploymentDetail(
        **deployment_out(deployment).model_dump(),
        service=await service_out(session, deployment.service),
        commit=schemas.Commit.model_validate(commit) if commit else None,
        capabilities=integration.capabilities if integration else [],
        incident_id=incident_id,
        investigation_id=await latest_investigation_id(session, deployment_id=deployment.id),
    )


@router.get("/{deployment_id}/logs")
async def get_logs(
    deployment_id: str,
    session: SessionDep,
    kind: schemas.LogKind = "build",
    limit: int = Query(500, ge=1, le=2000),
) -> list[schemas.LogLine]:
    deployment = await get_or_404(session, models.Deployment, deployment_id)
    try:
        rows = await logs.get_logs(session, deployment, kind, limit)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return [schemas.LogLine.model_validate(row) for row in rows]


@router.get("/{deployment_id}/diff")
async def get_diff(deployment_id: str, session: SessionDep) -> schemas.CommitDiff:
    deployment = await get_or_404(session, models.Deployment, deployment_id)
    if not deployment.commit_sha:
        raise HTTPException(404, "This deployment has no commit")
    try:
        diff = await diffs.get_commit_diff(session, deployment.commit_sha, deployment.service.repo)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    if diff is None:
        raise HTTPException(404, "No diff available for this commit (connect GitHub to fetch it)")
    return diff


@router.get("/{deployment_id}/changes")
async def get_changes(deployment_id: str, session: SessionDep) -> schemas.DeploymentChanges:
    """Commits, files and timing that separate this deploy from the last one that went live."""
    deployment = await get_or_404(session, models.Deployment, deployment_id)
    return await changes.get_changes(session, deployment)


@router.post("/{deployment_id}/investigate")
async def investigate(deployment_id: str, session: SessionDep) -> schemas.Investigation:
    deployment = await get_or_404(session, models.Deployment, deployment_id)
    incident_id = await session.scalar(
        select(models.Incident.id).where(models.Incident.deployment_id == deployment.id).limit(1)
    )
    investigation = await start_investigation(
        session, deployment=deployment, incident_id=incident_id
    )
    return investigation_out(investigation)
