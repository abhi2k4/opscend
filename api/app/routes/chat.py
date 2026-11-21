"""Ask Opscend: conversations with the read-only chat assistant."""

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from app import models, schemas
from app.chat.service import ask

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


@router.get("/sessions")
async def list_sessions(
    session: SessionDep, limit: int = Query(50, ge=1, le=200)
) -> list[schemas.ChatSessionSummary]:
    rows = await session.scalars(
        select(models.ChatSession).order_by(models.ChatSession.updated_at.desc()).limit(limit)
    )
    return [schemas.ChatSessionSummary.model_validate(row) for row in rows.all()]


@router.post("/sessions", status_code=201)
async def start_session(body: schemas.ChatAskRequest, session: SessionDep) -> schemas.ChatSession:
    return _session_out(await ask(session, None, body.content))


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, session: SessionDep) -> schemas.ChatSession:
    return _session_out(await get_or_404(session, models.ChatSession, session_id))


@router.post("/sessions/{session_id}/messages")
async def ask_followup(
    session_id: str, body: schemas.ChatAskRequest, session: SessionDep
) -> schemas.ChatSession:
    chat = await get_or_404(session, models.ChatSession, session_id)
    return _session_out(await ask(session, chat, body.content))


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, session: SessionDep) -> Response:
    await session.delete(await get_or_404(session, models.ChatSession, session_id))
    await session.commit()
    return Response(status_code=204)
