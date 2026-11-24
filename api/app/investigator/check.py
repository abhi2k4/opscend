"""`make check-ai`: is the configured model reachable, and can it call tools?

Opscend only works with a model that supports tool calling, and with a self-hosted
server that is the usual thing to go wrong. This runs one real round trip through the
same client the investigator uses: the model is asked to call a tool, gets the result,
and has to answer from it.
"""

import asyncio
import sys
import time

import httpx

from app.core.config import get_settings
from app.investigator.llm import LLMError, build_llm

TOOL = {
    "type": "function",
    "function": {
        "name": "get_deploy_status",
        "description": "Look up the status of a deployment by id.",
        "parameters": {
            "type": "object",
            "properties": {"deployment_id": {"type": "string"}},
            "required": ["deployment_id"],
        },
    },
}
QUESTION = "What is the status of deployment dep-42? Use the tool to find out."
RESULT = "deployment dep-42: status=failed, reason=missing env var CACHE_URL"


async def _served_models(base_url: str, key: str | None) -> list[str] | None:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{base_url}/models", headers=headers)
        return [str(m.get("id")) for m in response.json().get("data", [])]
    except (httpx.HTTPError, ValueError, AttributeError):
        return None


def is_served(model: str, served: list[str]) -> bool:
    """Ollama lists `name:latest` for a model the API also accepts as plain `name`."""
    return model in served or (":" not in model and f"{model}:latest" in served)


async def run() -> int:
    settings = get_settings()
    if settings.ai_simulated:
        print(
            "The model is simulated (OPSCEND_AI_SIMULATED / OPSCEND_PUBLIC_DEMO): nothing to check."
        )
        return 0
    if settings.ai_missing:
        print(f"FAIL  not configured. {settings.ai_missing}.")
        return 1
    kind = "self-hosted" if settings.ai_self_hosted else "hosted"
    print(f"provider  {settings.ai_provider} ({kind})")
    print(f"endpoint  {settings.ai_base_url}")
    print(f"model     {settings.ai_model}")

    served = await _served_models(settings.ai_base_url, settings.ai_key)
    if served is None:
        print("WARN  the endpoint did not list its models (GET /models); trying the model anyway")
    elif not is_served(settings.ai_model, served):
        listed = ", ".join(served) or "(empty)"
        print(f"WARN  {settings.ai_model!r} is not in the server's model list: {listed}")

    llm = build_llm()
    messages = [
        {"role": "system", "content": "You answer questions about deployments using tools."},
        {"role": "user", "content": QUESTION},
    ]
    try:
        started = time.perf_counter()
        first = await llm.complete(messages, [TOOL], "auto")
        took = time.perf_counter() - started
        call = next((c for c in first.tool_calls if c.name == "get_deploy_status"), None)
        if call is None:
            print(f"FAIL  the model answered in text instead of calling the tool ({took:.1f}s).")
            print("      Opscend needs a tool-calling model. On Ollama, pick one tagged 'tools'")
            print("      (for example qwen3, qwen2.5, llama3.1, mistral-nemo).")
            return 1
        if call.arguments.get("deployment_id") != "dep-42":
            print(f"WARN  the tool call had unexpected arguments: {call.arguments}")
        print(f"ok    tool call in {took:.1f}s")

        messages += [first.message, {"role": "tool", "tool_call_id": call.id, "content": RESULT}]
        started = time.perf_counter()
        final = await llm.complete(messages, [TOOL], "none")
        took = time.perf_counter() - started
    except LLMError as exc:
        print(f"FAIL  {exc}")
        return 1
    answer = (final.content or "").strip()
    if "CACHE_URL" not in answer and "failed" not in answer.lower():
        print(f"FAIL  the model did not use the tool result. It said: {answer[:200]!r}")
        if settings.ai_self_hosted:
            print("      An empty or cut-off answer often means the context window is too small")
            print("      (Ollama: set OLLAMA_CONTEXT_LENGTH=16384 or higher on the server).")
        return 1
    print(f"ok    answer from the tool result in {took:.1f}s")
    print(f"PASS  {settings.ai_model} works with Opscend.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
