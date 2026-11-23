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


@respx.mock
async def test_a_reply_cut_off_at_the_output_limit_is_an_error():
    """A truncated tool call must not reach the caller as a call with empty arguments."""
    cut_call = {"name": "submit_report", "arguments": '{"inconclusive": false, "likely_ca'}
    message = {"role": "assistant", "content": None, "tool_calls": [{"function": cut_call}]}
    respx.post(URL).respond(json={"choices": [{"finish_reason": "length", "message": message}]})
    with pytest.raises(LLMError, match="OPSCEND_AI_MAX_OUTPUT_TOKENS") as cut_off:
        await client().complete([], [], "auto")
    assert "1000 tokens" in str(cut_off.value)
    assert not cut_off.value.retryable


# --- self-hosted model servers (Ollama, LM Studio, llama.cpp, vLLM) -------------------

LOCAL = "http://localhost:11434/v1/chat/completions"


def local(**options) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        "http://localhost:11434/v1", None, "qwen3:8b", self_hosted=True, **options
    )


def completion(message: dict) -> dict:
    return {"choices": [{"message": message}], "usage": {"total_tokens": 42}}


@respx.mock
async def test_a_local_server_needs_no_key_and_gets_its_own_limits():
    route = respx.post(LOCAL).respond(json=completion({"role": "assistant", "content": "hi"}))
    tools = [{"type": "function", "function": {"name": "get_logs", "parameters": {}}}]
    await local(max_tokens=4000).complete([{"role": "user", "content": "hi"}], tools, "auto")
    request = route.calls.last.request
    assert "authorization" not in request.headers
    sent = json.loads(request.content)
    assert sent["max_tokens"] == 4000 and sent["tools"] == tools and sent["tool_choice"] == "auto"


@respx.mock
async def test_a_forced_text_answer_offers_a_local_model_no_tools():
    """Local servers often ignore tool_choice, so "none" must not leave tools on offer."""
    route = respx.post(LOCAL).respond(json=completion({"role": "assistant", "content": "done"}))
    tools = [{"type": "function", "function": {"name": "get_logs", "parameters": {}}}]
    assert (await local().complete([], tools, "none")).content == "done"
    sent = json.loads(route.calls.last.request.content)
    assert "tools" not in sent and "tool_choice" not in sent


@respx.mock
async def test_local_model_quirks_are_normalised():
    message = {
        "role": "assistant",
        "content": "<think>The user wants logs.\nI should call get_logs.</think>\n\n",
        "tool_calls": [
            # Arguments as an object and no id, as some servers send them.
            {"function": {"name": "get_logs", "arguments": {"deployment_id": "dep-1"}}},
            {"id": "abc", "type": "function", "function": {"name": "x", "arguments": "{}"}},
        ],
    }
    respx.post(LOCAL).respond(json=completion(message))
    response = await local().complete([], [{"type": "function", "function": {"name": "x"}}], "auto")
    assert response.content == ""
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [
        ("call_0", "get_logs", {"deployment_id": "dep-1"}),
        ("abc", "x", {}),
    ]
    # What goes back into the conversation is the standard form every server accepts.
    replayed = response.message["tool_calls"]
    assert replayed[0]["id"] == "call_0" and replayed[0]["type"] == "function"
    assert json.loads(replayed[0]["function"]["arguments"]) == {"deployment_id": "dep-1"}
    assert "<think>" not in response.message["content"]

    respx.post(LOCAL).respond(
        json=completion({"role": "assistant", "content": "<think>hmm</think>The build failed."})
    )
    assert (await local().complete([], [], "auto")).content == "The build failed."


@respx.mock
async def test_an_unreachable_local_server_says_where_it_looked():
    respx.post(LOCAL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(LLMError, match=r"localhost:11434.*host\.docker\.internal") as caught:
        await local().complete([], [], "auto")
    assert caught.value.retryable


def test_provider_presets_and_what_is_missing(env):
    from app.core.config import get_settings

    def settings(**values: str):
        for key in (
            "GROQ_API_KEY",
            "OPSCEND_AI_PROVIDER",
            "OPSCEND_AI_MODEL",
            "OPSCEND_AI_BASE_URL",
            "OPSCEND_AI_API_KEY",
        ):
            env.setenv(key, values.get(key, ""))
        get_settings.cache_clear()
        return get_settings()

    groq = settings()
    assert not groq.ai_configured and "GROQ_API_KEY" in groq.ai_missing
    assert groq.ai_base_url == "https://api.groq.com/openai/v1" and not groq.ai_self_hosted
    assert groq.ai_model == "openai/gpt-oss-120b" and groq.ai_timeout_seconds == 60

    groq = settings(GROQ_API_KEY="gsk_x")
    assert groq.ai_configured and groq.ai_key == "gsk_x" and groq.ai_max_output_tokens == 1000

    ollama = settings(OPSCEND_AI_PROVIDER="Ollama")
    assert ollama.ai_base_url == "http://localhost:11434/v1" and ollama.ai_self_hosted
    assert not ollama.ai_configured and "OPSCEND_AI_MODEL" in ollama.ai_missing

    ollama = settings(OPSCEND_AI_PROVIDER="ollama", OPSCEND_AI_MODEL="qwen3:8b")
    assert ollama.ai_configured and ollama.ai_key is None  # no key needed
    assert ollama.ai_timeout_seconds == 300 and ollama.ai_max_output_tokens == 4000

    vllm = settings(OPSCEND_AI_PROVIDER="vllm", OPSCEND_AI_MODEL="Qwen/Qwen2.5-7B-Instruct")
    assert not vllm.ai_configured and "OPSCEND_AI_BASE_URL" in vllm.ai_missing
    vllm = settings(
        OPSCEND_AI_PROVIDER="vllm",
        OPSCEND_AI_MODEL="Qwen/Qwen2.5-7B-Instruct",
        OPSCEND_AI_BASE_URL="http://gpu-box:8000/v1/",
        OPSCEND_AI_API_KEY="token-abc",
    )
    assert vllm.ai_configured and vllm.ai_base_url == "http://gpu-box:8000/v1"
    assert vllm.ai_key == "token-abc"


async def test_the_api_reports_a_self_hosted_model_and_runs_without_a_key(env):
    from tests.conftest import ADMIN, _clear_caches, running_app

    env.setenv("OPSCEND_AI_PROVIDER", "ollama")
    env.setenv("OPSCEND_AI_MODEL", "qwen3:8b")
    env.setenv("OPSCEND_DEMO", "1")
    _clear_caches()
    async with running_app() as api:
        assert (await api.post("/api/auth/login", json=ADMIN)).status_code == 200
        assert (await api.get("/api/system")).json()["ai"] == {
            "provider": "ollama",
            "model": "qwen3:8b",
            "configured": True,
            "simulated": False,
            "self_hosted": True,
        }
        # No GROQ_API_KEY anywhere, and a question is still accepted.
        asked = await api.post("/api/chat/sessions", json={"content": "hello"})
        assert asked.status_code == 201, asked.text
