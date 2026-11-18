"""Investigations and incidents."""

from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from app import models, schemas
from app.incidents import rules
from app.investigator.service import start_investigation
from app.services.presenters import incident_out, investigation_out

from .deps import SessionDep, get_or_404

router = APIRouter(tags=["investigations"])


@router.get("/investigations")
async def list_investigations(
    session: SessionDep, limit: int = Query(50, ge=1, le=200)
) -> list[schemas.Investigation]:
    rows = await session.scalars(
        select(models.Investigation).order_by(models.Investigation.created_at.desc()).limit(limit)
    )
    return [investigation_out(row) for row in rows.all()]


@router.get("/investigations/{investigation_id}")
async def get_investigation(investigation_id: str, session: SessionDep) -> schemas.Investigation:
    return investigation_out(await get_or_404(session, models.Investigation, investigation_id))


@router.get("/incidents")
async def list_incidents(
    session: SessionDep,
    status: Literal["open", "resolved"] | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[schemas.Incident]:
    query = select(models.Incident).order_by(models.Incident.opened_at.desc()).limit(limit)
    if status:
        query = query.where(models.Incident.status == status)
    return [await incident_out(session, row) for row in (await session.scalars(query)).all()]


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str, session: SessionDep) -> schemas.Incident:
    return await incident_out(session, await get_or_404(session, models.Incident, incident_id))


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(incident_id: str, session: SessionDep) -> schemas.Incident:
    incident = await get_or_404(session, models.Incident, incident_id)
    if incident.status == "open":
        rules.resolve(incident)
        await session.commit()
    return await incident_out(session, incident)


@router.post("/incidents/{incident_id}/investigate")
async def investigate_incident(incident_id: str, session: SessionDep) -> schemas.Investigation:
    incident = await get_or_404(session, models.Incident, incident_id)
    deployment = (
        await session.get(models.Deployment, incident.deployment_id)
        if incident.deployment_id
        else None
    )
    investigation = await start_investigation(
        session,
        deployment=deployment,
        incident_id=incident.id,
        service_name=incident.service.name,
    )
    return investigation_out(investigation)
