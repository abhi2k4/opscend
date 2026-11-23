"""Ask Opscend: conversations with the read-only chat assistant."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select

from app import models, schemas
from app.chat.service import ask
from app.core.public_demo import paced, visitor_id

from .deps import SessionDep, get_or_404

router = APIRouter(prefix="/chat", tags=["chat"])


def _session_out(chat: models.ChatSession) -> schemas.ChatSession:
    return schemas.ChatSession(
        id=chat.id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        tokens_used=chat.tokens_used,
        messages=[schemas.ChatMessage.model_validate(m) for m in chat.messages],
    )


async def _mine(session: SessionDep, request: Request, session_id: str) -> models.ChatSession:
    """A conversation the caller may see: in the public demo, only their own."""
    chat = await get_or_404(session, models.ChatSession, session_id)
    visitor = visitor_id(request)
    if visitor is not None and chat.owner != visitor:
        raise HTTPException(404, "ChatSession not found")
    return chat


@router.get("/sessions")
async def list_sessions(
    session: SessionDep, request: Request, limit: int = Query(50, ge=1, le=200)
) -> list[schemas.ChatSessionSummary]:
    query = select(models.ChatSession).order_by(models.ChatSession.updated_at.desc()).limit(limit)
    visitor = visitor_id(request)
    if visitor is not None:
        query = query.where(models.ChatSession.owner == visitor)
    rows = await session.scalars(query)
    return [schemas.ChatSessionSummary.model_validate(row) for row in rows.all()]


@router.post("/sessions", status_code=201, dependencies=[Depends(paced("chat", 2))])
async def start_session(
    body: schemas.ChatAskRequest, session: SessionDep, request: Request
) -> schemas.ChatSession:
    return _session_out(await ask(session, None, body.content, visitor_id(request)))


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str, session: SessionDep, request: Request
) -> schemas.ChatSession:
    return _session_out(await _mine(session, request, session_id))


@router.post("/sessions/{session_id}/messages", dependencies=[Depends(paced("chat", 2))])
async def ask_followup(
    session_id: str, body: schemas.ChatAskRequest, session: SessionDep, request: Request
) -> schemas.ChatSession:
    chat = await _mine(session, request, session_id)
    return _session_out(await ask(session, chat, body.content))


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, session: SessionDep, request: Request) -> Response:
    await session.delete(await _mine(session, request, session_id))
    await session.commit()
    return Response(status_code=204)
