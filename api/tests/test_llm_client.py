"""The OpenAI-compatible client against recorded-style Groq responses."""

import json

import httpx
import pytest
import respx

from app.investigator import llm as llm_module
from app.investigator.llm import LLMError, OpenAICompatibleClient
from tests.conftest import load_fixture

URL = "https://api.groq.com/openai/v1/chat/completions"
KEY = "gsk_test_key_do_not_leak"


def client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient("https://api.groq.com/openai/v1/", KEY, "llama-3.3-70b-versatile")


@respx.mock
async def test_parses_tool_calls_and_usage():
    route = respx.post(URL).respond(json=load_fixture("groq_tool_call.json"))
    tools = [{"type": "function", "function": {"name": "get_logs", "parameters": {}}}]
    response = await client().complete([{"role": "user", "content": "hi"}], tools, "auto")

    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "llama-3.3-70b-versatile"
    assert sent["tool_choice"] == "auto" and sent["tools"] == tools
    assert route.calls.last.request.headers["authorization"] == f"Bearer {KEY}"

    assert response.tokens == 853
    assert [(c.id, c.name) for c in response.tool_calls] == [
        ("call_a1", "get_logs"),
        ("call_a2", "get_deployment"),
    ]
    assert response.tool_calls[0].arguments == {"deployment_id": "dep-1", "kind": "runtime"}
    assert response.tool_calls[1].arguments == {}  # malformed JSON arguments degrade to empty
    assert response.message["role"] == "assistant" and len(response.message["tool_calls"]) == 2


@respx.mock
async def test_rate_limit_is_retried_then_reported(monkeypatch):
    waits: list[float] = []

    async def no_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(llm_module.asyncio, "sleep", no_sleep)
    limited = httpx.Response(
        429,
        headers={"retry-after": "3"},
        json={"error": {"message": "Rate limit reached for model", "code": "rate_limit_exceeded"}},
    )
    route = respx.post(URL).mock(
        side_effect=[limited, httpx.Response(200, json=load_fixture("groq_tool_call.json"))]
    )
    assert (await client().complete([], [], "auto")).tokens == 853
    assert waits == [3.0] and route.call_count == 2

    respx.post(URL).mock(return_value=limited)
    with pytest.raises(LLMError, match="rate limit") as error:
        await client().complete([], [], "auto")
    assert not error.value.retryable
    assert KEY not in str(error.value)


@respx.mock
async def test_long_rate_limit_waits_fail_fast():
    respx.post(URL).respond(
        429, headers={"retry-after": "600"}, json={"error": {"message": "daily"}}
    )
    with pytest.raises(LLMError, match="rate limit"):
        await client().complete([], [], "auto")


@respx.mock
async def test_errors_are_classified():
    respx.post(URL).respond(401, json={"error": {"message": "Invalid API Key"}})
    with pytest.raises(LLMError, match="GROQ_API_KEY") as unauthorized:
        await client().complete([], [], "auto")
    assert not unauthorized.value.retryable

    respx.post(URL).respond(
        400, json={"error": {"message": "Failed to call a function", "code": "tool_use_failed"}}
    )
    with pytest.raises(LLMError, match="Failed to call a function") as bad_call:
        await client().complete([], [], "auto")
    assert bad_call.value.retryable

    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(LLMError, match="ReadTimeout") as timeout:
        await client().complete([], [], "auto")
    assert timeout.value.retryable

    respx.post(URL).respond(200, json={"choices": []})
    with pytest.raises(LLMError, match="unexpected response"):
        await client().complete([], [], "auto")
