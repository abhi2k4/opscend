"""Webhook intake and the raw event inspector."""

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app import models, schemas
from app.core.queue import get_queue
from app.ingest.webhooks import UnknownProviderError, receive_webhook
from app.integrations.base import WebhookVerificationError

from .deps import SessionDep

log = logging.getLogger(__name__)

public_router = APIRouter(tags=["webhooks"])
router = APIRouter(tags=["events"])

MAX_BODY_BYTES = 5 * 1024 * 1024


@public_router.post("/webhooks/{provider}", status_code=202)
async def webhook(provider: str, request: Request, session: SessionDep) -> schemas.Accepted:
    """Verify, store, enqueue, return. All real work happens in the job."""
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(413, "Webhook body too large")
    try:
        events = await receive_webhook(session, provider, dict(request.headers), body)
    except UnknownProviderError:
        raise HTTPException(404, f"No connected {provider} integration accepts webhooks") from None
    except WebhookVerificationError as exc:
        log.warning("rejected %s webhook: %s", provider, exc)
        raise HTTPException(401, "Webhook signature verification failed") from None
    queue = get_queue()
    fresh = [event for event in events if not event.duplicate]
    for event in fresh:
        await queue.enqueue("process_event", event.id)
    return schemas.Accepted(accepted=len(fresh), duplicates=len(events) - len(fresh))


@router.get("/events")
async def list_events(
    session: SessionDep, limit: int = Query(50, ge=1, le=500)
) -> list[schemas.RawEvent]:
    rows = await session.scalars(
        select(models.RawEvent).order_by(models.RawEvent.received_at.desc()).limit(limit)
    )
    return [schemas.RawEvent.model_validate(row) for row in rows.all()]
