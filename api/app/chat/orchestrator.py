"""Answering one chat message.

model turn → tool calls → model turn → … → a plain-text answer. Tool calls are
recorded on the assistant message as they finish, so the UI can show progress while
it polls. The loop is bounded by the same tool-call cap and token budget as an
investigation; once either is hit the model must answer with what it has.
"""

import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.time import utcnow
from app.investigator.llm import LLMClient, LLMError, build_llm
from app.models import ChatMessage, ChatSession, Service

from . import citations
from .prompts import SYSTEM_PROMPT, context_prompt
from .tools import CHAT_TOOL_SPECS, ChatLedger, ChatTools

log = logging.getLogger(__name__)

MAX_TURNS = 10
HISTORY_MESSAGES = 12
HISTORY_CHARS = 4000
SUMMARY_CHARS = 300
BUDGET_NOTE = "Tool budget exhausted. Answer now with what you have."


class ChatFailed(Exception):
    """The model could not produce an answer."""


async def run_chat_reply(message_id: str, llm: LLMClient | None = None) -> None:
    """Job: fill in one pending assistant message (or record why it failed)."""
    async with session_scope() as session:
        message = await session.get(ChatMessage, message_id)
        if message is None or message.status != "pending":
            return
        message.status = "running"
        await session.commit()

        answer: tuple[str, list[dict[str, Any]]] | None = None
        error: str | None = None
        try:
            turn = _Turn(session, message, llm or build_llm())
            answer = await turn.execute()
        except (ChatFailed, LLMError) as exc:
            error = str(exc)
        except Exception as exc:
            log.exception("chat reply %s crashed", message_id)
            error = f"internal error: {type(exc).__name__}"

        await session.rollback()
        message = await session.get(ChatMessage, message_id)
        if message is None:  # the conversation was deleted while it ran
            return
        if answer is not None:
            message.content, message.citations = answer
        message.status = "done" if answer else "failed"
        message.error = error
        message.steps = [
            {**step, "status": "error"} if step["status"] == "running" else step
            for step in message.steps
        ]
        message.finished_at = utcnow()
        chat = await session.get(ChatSession, message.session_id)
        if chat is not None:
            chat.tokens_used += message.tokens
            chat.updated_at = utcnow()
        await session.commit()


class _Turn:
    def __init__(self, session: AsyncSession, message: ChatMessage, llm: LLMClient) -> None:
        self.session = session
        self.message = message
        self.llm = llm
        self.ledger = ChatLedger()
        self.tools = ChatTools(session, self.ledger)
        self.settings = get_settings()
        self.tool_calls = 0
        message.model = llm.model

    async def _context(self) -> list[dict[str, Any]]:
        services = list((await self.session.scalars(select(Service).order_by(Service.name))).all())
        self.ledger.services.update(s.id for s in services)
        earlier = (
            await self.session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.session_id == self.message.session_id,
                    ChatMessage.index < self.message.index,
                )
                .order_by(ChatMessage.index)
            )
        ).all()
        history: list[dict[str, Any]] = []
        for item in earlier:
            if item.role == "assistant":
                if item.status != "done":
                    continue
                for citation in item.citations:
                    self.ledger.seed(citation)
            history.append({"role": item.role, "content": item.content[:HISTORY_CHARS]})
        if not history or history[-1]["role"] != "user":
            raise ChatFailed("there is no question to answer")
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": context_prompt(utcnow(), services)},
            *history[-HISTORY_MESSAGES:],
        ]

    def _over_budget(self) -> bool:
        return (
            self.tool_calls >= self.settings.ai_max_tool_calls
            or self.message.tokens >= self.settings.ai_token_budget
        )

    async def execute(self) -> tuple[str, list[dict[str, Any]]]:
        messages = await self._context()
        retried = False
        for turn in range(MAX_TURNS):
            forced = self._over_budget() or turn == MAX_TURNS - 1
            try:
                response = await self.llm.complete(
                    messages, CHAT_TOOL_SPECS, "none" if forced else "auto"
                )
            except LLMError as exc:
                if exc.retryable and not retried:
                    retried = True
                    continue
                raise
            self.message.tokens += response.tokens
            await self.session.commit()

            if not response.tool_calls or forced:
                content = (response.content or "").strip()
                if not content:
                    raise ChatFailed("the model returned an empty answer")
                return await citations.resolve(self.session, content, self.ledger)

            messages.append(response.message)
            for call in response.tool_calls:
                if self.tool_calls >= self.settings.ai_max_tool_calls:
                    content = BUDGET_NOTE
                else:
                    content = await self._tool_step(call.name, call.arguments)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
        raise ChatFailed("the model did not answer within its turn limit")

    async def _tool_step(self, name: str, arguments: dict[str, Any]) -> str:
        self.tool_calls += 1
        index = len(self.message.steps)
        self.message.steps = [
            *self.message.steps,
            {
                "name": name,
                "input": arguments,
                "status": "running",
                "summary": None,
                "duration_ms": None,
            },
        ]
        await self.session.commit()
        started = time.perf_counter()
        output = await self.tools.call(name, arguments)
        steps = list(self.message.steps)
        steps[index] = {
            **steps[index],
            "status": "error" if output.startswith("error:") else "ok",
            "summary": _summarize(output),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        self.message.steps = steps
        await self.session.commit()
        return output


def _summarize(output: str) -> str:
    """The first line of a tool result, for the step list (the model gets the full text)."""
    first = output.strip().splitlines()[0] if output.strip() else ""
    if first in ("[", "{"):
        return "returned structured results"
    return first[:SUMMARY_CHARS]
