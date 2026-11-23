"""A minimal chat-completions client for any OpenAI-compatible API.

Groq by default; the same client talks to a model server you run yourself (Ollama,
LM Studio, llama.cpp, vLLM). Those differ from a hosted API in a few ways that are
handled here: no key, slow answers, `<think>` blocks in the text, tool-call arguments
sent as an object, missing tool-call ids, and `tool_choice` being ignored.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60.0
# Per-minute limits clear within a minute; anything longer is a daily cap, so fail fast.
MAX_RATE_LIMIT_WAIT = 65.0
# Counts against the provider's tokens-per-minute limit on every request, so keep it tight.
MAX_COMPLETION_TOKENS = 1000
# Reasoning that "thinking" models (qwen3, deepseek-r1, ...) write into the answer text.
THINKING = re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL | re.IGNORECASE)


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
        api_key: str | None,
        model: str,
        *,
        client: httpx.AsyncClient | None = None,
        rate_limit_retries: int = 4,
        self_hosted: bool = False,
        timeout: float = REQUEST_TIMEOUT,
        max_tokens: int = MAX_COMPLETION_TOKENS,
    ) -> None:
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._url = f"{self._base_url}/chat/completions"
        self._api_key = api_key
        self._client = client
        self._rate_limit_retries = rate_limit_retries
        self._self_hosted = self_hosted
        self._timeout = httpx.Timeout(timeout, connect=10.0)
        self._max_tokens = max_tokens

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any],
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": self._max_tokens,
        }
        if self._self_hosted and tool_choice == "none":
            # Several local servers ignore tool_choice, so "answer in text now" is only
            # reliable when no tools are offered at all.
            pass
        elif tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            for attempt in range(self._rate_limit_retries + 1):
                try:
                    response = await client.post(self._url, json=body, headers=headers)
                except httpx.HTTPError as exc:
                    raise LLMError(self._unreachable(type(exc).__name__), retryable=True) from exc
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

    def _unreachable(self, why: str) -> str:
        if not self._self_hosted:
            return f"could not reach the model API: {why}"
        return (
            f"could not reach the model server at {self._base_url}: {why}. Check that it is "
            "running and has the model loaded; from Docker, use host.docker.internal "
            "instead of localhost. Slow hardware may need a higher OPSCEND_AI_TIMEOUT_SECONDS"
        )


def build_llm() -> LLMClient:
    settings = get_settings()
    if settings.ai_simulated:
        from app.demo.simulated import SimulatedLLM  # imported late: it imports this module

        return SimulatedLLM()
    if settings.ai_missing:
        raise LLMError(f"no AI model is configured. {settings.ai_missing}")
    return OpenAICompatibleClient(
        settings.ai_base_url,
        settings.ai_key,
        settings.ai_model,
        self_hosted=settings.ai_self_hosted,
        timeout=settings.ai_timeout_seconds,
        max_tokens=settings.ai_max_output_tokens,
    )


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
        raise LLMError(
            "the model API rejected the API key (check GROQ_API_KEY, or OPSCEND_AI_API_KEY "
            "for another endpoint)"
        )
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
    replay = []  # the calls as they go back into the conversation: ids set, arguments a string
    for index, raw in enumerate(message.get("tool_calls") or []):
        function = raw.get("function") or {}
        arguments = function.get("arguments")
        if not isinstance(arguments, dict):  # the standard form: a JSON string
            try:
                arguments = json.loads(arguments or "{}")
            except (ValueError, TypeError):
                arguments = {}
        call = ToolCall(
            id=raw.get("id") or f"call_{index}",
            name=function.get("name", ""),
            arguments=arguments if isinstance(arguments, dict) else {},
        )
        calls.append(call)
        sent = function.get("arguments")
        replay.append(
            {
                **raw,
                "id": call.id,
                "type": raw.get("type") or "function",
                "function": {
                    **function,
                    "arguments": sent if isinstance(sent, str) else json.dumps(call.arguments),
                },
            }
        )
    content = message.get("content")
    if isinstance(content, str) and "<think>" in content.lower():
        content = THINKING.sub("", content).strip()
    assistant: dict[str, Any] = {"role": "assistant", "content": content or ""}
    if replay:
        assistant["tool_calls"] = replay
    return LLMResponse(
        content=content,
        tool_calls=calls,
        tokens=int((data.get("usage") or {}).get("total_tokens") or 0),
        message=assistant,
    )
