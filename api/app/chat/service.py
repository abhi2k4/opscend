"""Asking a question: the checks and bookkeeping before the `chat_reply` job is queued."""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.queue import get_queue
from app.core.time import utcnow
from app.models import ChatMessage, ChatSession

NOT_CONFIGURED = "Ask Opscend needs an AI model. {hint}, then restart the API."
MAX_QUESTION_CHARS = 4000
MAX_TITLE_CHARS = 80
# A queued reply no worker has started after this long was dropped (worker down, or
# running an older version without the `chat_reply` job). A running one past the
# worker's own job timeout was killed.
PENDING_TIMEOUT = timedelta(minutes=2)


def job_timeout() -> timedelta:
    """How long one investigation or answer may run: a slow local model needs longer."""
    return timedelta(seconds=max(300.0, 6 * get_settings().ai_timeout_seconds))


RUNNING_TIMEOUT = timedelta(minutes=6)
NOT_PICKED_UP = (
    "No worker picked this question up. Check that the worker is running and on the "
    "same version as the API (docker compose up -d --build worker), then ask again."
)
TIMED_OUT = "The answer took too long and was stopped. Ask again."


async def ask(
    session: AsyncSession, chat: ChatSession | None, question: str, owner: str | None = None
) -> ChatSession:
    """Add a question (to a new conversation when `chat` is None) and queue its answer.

    Raises HTTP 409 when no LLM key is configured or the previous answer is still
    being written, and 422 for an empty or overlong question.
    """
    settings = get_settings()
    if not settings.ai_configured:
        raise HTTPException(409, NOT_CONFIGURED.format(hint=settings.ai_missing))
    question = question.strip()
    if not question:
        raise HTTPException(422, "Ask a question first.")
    if len(question) > MAX_QUESTION_CHARS:
        raise HTTPException(422, f"Keep questions under {MAX_QUESTION_CHARS} characters.")

    if chat is None:
        title = " ".join(question.split())
        if len(title) > MAX_TITLE_CHARS:
            title = title[: MAX_TITLE_CHARS - 1].rstrip() + "…"
        chat = ChatSession(title=title, owner=owner)
        session.add(chat)
        await session.flush()
        await session.refresh(chat, ["messages"])
    elif any(m.status in ("pending", "running") for m in chat.messages):
        raise HTTPException(409, "Wait for the current answer to finish.")

    index = len(chat.messages)
    session.add(ChatMessage(session_id=chat.id, index=index, role="user", content=question))
    reply = ChatMessage(
        session_id=chat.id,
        index=index + 1,
        role="assistant",
        status="pending",
        model=settings.ai_model_name,
    )
    session.add(reply)
    chat.updated_at = utcnow()
    await session.commit()
    await session.refresh(chat, ["messages"])
    await get_queue().enqueue("chat_reply", reply.id)
    return chat


async def expire_stale_replies() -> int:
    """Job: fail replies whose job was lost, so a conversation never stays blocked."""
    now = utcnow()
    count = 0
    async with session_scope() as session:
        for status, timeout, error in (
            ("pending", PENDING_TIMEOUT, NOT_PICKED_UP),
            ("running", max(RUNNING_TIMEOUT, job_timeout() + timedelta(minutes=1)), TIMED_OUT),
        ):
            result = await session.execute(
                update(ChatMessage)
                .where(ChatMessage.status == status, ChatMessage.created_at < now - timeout)
                .values(status="failed", error=error, finished_at=now)
            )
            count += result.rowcount or 0
        await session.commit()
    return count
