"""A minimal chat-completions client for any OpenAI-compatible API (Groq by default)."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
# Per-minute limits clear within a minute; anything longer is a daily cap, so fail fast.
MAX_RATE_LIMIT_WAIT = 65.0
# Counts against the provider's tokens-per-minute limit on every request, so keep it tight.
MAX_COMPLETION_TOKENS = 1000


class LLMError(Exception):
    """The model call failed. `retryable` marks failures worth one more attempt."""

    def __init__(
        self, message: str, *, retryable: bool = False, unknown_tool: str | None = None
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        # Set when the provider rejected a call to a tool that was not offered.
        self.unknown_tool = unknown_tool


# Groq validates tool names server-side and rejects the whole completion when the model
# invents one ("attempted to call tool 'search_incidents' which was not in request.tools").
UNKNOWN_TOOL = re.compile(r"attempted to call tool '([^']{1,80})' which was not in request\.tools")
MAX_TOOL_CORRECTIONS = 2


def unknown_tool_note(name: str, tools: list[dict[str, Any]]) -> str:
    """A correction for the model after it called a tool that does not exist."""
    names = ", ".join(spec["function"]["name"] for spec in tools)
    return (
        f"There is no tool named {name!r}; that call was rejected. Use only these tools: {names}."
    )


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    tokens: int
    # The assistant message exactly as it must be appended to the conversation.
    message: dict[str, Any] = field(default_factory=dict)


class LLMClient(Protocol):
    model: str

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any],
    ) -> LLMResponse: ...


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        client: httpx.AsyncClient | None = None,
        rate_limit_retries: int = 4,
    ) -> None:
        self.model = model
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._client = client
        self._rate_limit_retries = rate_limit_retries

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any],
    ) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": 0.1,
            "max_tokens": MAX_COMPLETION_TOKENS,
        }
        client = self._client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        try:
            for attempt in range(self._rate_limit_retries + 1):
                try:
                    response = await client.post(
                        self._url, json=body, headers={"Authorization": f"Bearer {self._api_key}"}
                    )
                except httpx.HTTPError as exc:
                    raise LLMError(
                        f"could not reach the model API: {type(exc).__name__}", retryable=True
                    ) from exc
                if response.status_code != 429:
                    return _parse(response)
                wait = _retry_after(response)
                if attempt == self._rate_limit_retries or wait > MAX_RATE_LIMIT_WAIT:
                    raise LLMError(f"model API rate limit reached: {_error_message(response)}")
                log.info("model API rate limited; retrying in %.1fs", wait)
                await asyncio.sleep(wait)
            raise LLMError("model API rate limit reached")
        finally:
            if self._client is None:
                await client.aclose()


def build_llm() -> LLMClient:
    settings = get_settings()
    if settings.ai_simulated:
        from app.demo.simulated import SimulatedLLM  # imported late: it imports this module

        return SimulatedLLM()
    if not settings.ai_configured:
        raise LLMError("GROQ_API_KEY is not set")
    return OpenAICompatibleClient(settings.ai_base_url, settings.groq_api_key, settings.ai_model)


def _retry_after(response: httpx.Response) -> float:
    try:
        return max(0.5, float(response.headers.get("retry-after", "2")))
    except ValueError:
        return 2.0


def _error_message(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
        return str(error.get("message") or error)[:300]
    except (ValueError, AttributeError):
        return f"HTTP {response.status_code}"


def _parse(response: httpx.Response) -> LLMResponse:
    if response.status_code == 401:
        raise LLMError("the model API rejected the API key (check GROQ_API_KEY)")
    if response.status_code >= 400:
        # Groq answers 400 `tool_use_failed` when the model emits a malformed call.
        detail = _error_message(response)
        unknown = UNKNOWN_TOOL.search(detail) if response.status_code == 400 else None
        raise LLMError(
            f"model API error (HTTP {response.status_code}): {detail}",
            retryable=response.status_code in (400, 500, 502, 503),
            unknown_tool=unknown.group(1) if unknown else None,
        )
    try:
        data = response.json()
        message = data["choices"][0]["message"]
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMError("model API returned an unexpected response", retryable=True) from exc

    calls = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except ValueError:
            arguments = {}
        calls.append(
            ToolCall(
                id=raw.get("id", ""),
                name=function.get("name", ""),
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        )
    assistant: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("tool_calls"):
        assistant["tool_calls"] = message["tool_calls"]
    return LLMResponse(
        content=message.get("content"),
        tool_calls=calls,
        tokens=int((data.get("usage") or {}).get("total_tokens") or 0),
        message=assistant,
    )
