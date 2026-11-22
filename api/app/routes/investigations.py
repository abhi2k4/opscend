"""Investigations and incidents."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app import models, schemas
from app.core.time import utcnow
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


@router.get("/investigations/stats")
async def investigation_stats(session: SessionDep) -> schemas.InvestigationStats:
    """Counts of finished reports and of the verdicts readers gave them."""
    rows = (
        await session.execute(
            select(models.Investigation.report, models.Investigation.feedback_rating).where(
                models.Investigation.status == "completed"
            )
        )
    ).all()
    ratings = [rating for _, rating in rows if rating]
    return schemas.InvestigationStats(
        completed=len(rows),
        inconclusive=sum(1 for report, _ in rows if (report or {}).get("inconclusive")),
        rated=len(ratings),
        helpful=ratings.count("up"),
        not_helpful=ratings.count("down"),
    )


@router.get("/investigations/{investigation_id}")
async def get_investigation(investigation_id: str, session: SessionDep) -> schemas.Investigation:
    return investigation_out(await get_or_404(session, models.Investigation, investigation_id))


@router.put("/investigations/{investigation_id}/feedback")
async def rate_investigation(
    investigation_id: str, body: schemas.InvestigationFeedbackIn, session: SessionDep
) -> schemas.Investigation:
    """Record whether the report was right. Sending `rating: null` clears it."""
    investigation = await get_or_404(session, models.Investigation, investigation_id)
    if investigation.status != "completed":
        raise HTTPException(409, "Only a finished report can be rated")
    note = (body.note or "").strip() or None
    investigation.feedback_rating = body.rating
    investigation.feedback_note = note if body.rating else None
    investigation.feedback_at = utcnow() if body.rating else None
    await session.commit()
    return investigation_out(investigation)


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
