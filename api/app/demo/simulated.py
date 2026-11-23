"""A scripted stand-in for the model, for the public demo.

`SimulatedLLM` speaks the same interface as the real client, so the investigator and
Ask Opscend run unchanged: it asks for the real read-only tools, and builds its report
or answer from what they returned. Nothing here calls a model, and the UI says so.

It only understands the demo: the scripted failures (`diagnoses.py`) and a fixed set of
question types. Anything else gets an honest "this is a simulation" answer.
"""

import asyncio
import itertools
import json
import re
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.investigator.llm import LLMResponse, ToolCall

from .diagnoses import DIAGNOSES, Diagnosis

MODEL_NAME = "simulated"
REPORT_TOOL = "submit_report"

_ids = itertools.count(1)
Call = tuple[str, dict[str, Any]]

LOG_LINE = re.compile(r"^\[(log_[0-9a-f]+)\] \S+ (\w+)\s+(.*)$", re.MULTILINE)
# search_logs prints the date and the log kind as well.
FOUND_LINE = re.compile(
    r"^\[(log_[0-9a-f]+)\] \S+ \S+ (?:build|runtime) (\w+)\s+(.*)$", re.MULTILINE
)
CHART = re.compile(r"\[chart:[^\]\s]+\]")
SELF_HOST = (
    "Run Opscend on your own machine with a Groq key to ask anything "
    "(three commands, see the setup guide)."
)


class SimulatedLLM:
    model = MODEL_NAME

    def __init__(self, delay: float | None = None) -> None:
        self._delay = get_settings().simulated_delay_seconds if delay is None else delay

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any],
    ) -> LLMResponse:
        if self._delay:
            await asyncio.sleep(self._delay)  # a model takes a moment; so does the trace
        offered = {spec["function"]["name"] for spec in tools}
        if REPORT_TOOL in offered:
            return _investigate(messages, forced=offered == {REPORT_TOOL})
        return _chat(messages, forced=tool_choice == "none")


# ───────────────────────────── shared helpers


def _respond(content: str, calls: list[Call] | None = None) -> LLMResponse:
    tool_calls = [
        ToolCall(id=f"sim_{next(_ids)}", name=name, arguments=args) for name, args in calls or []
    ]
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in tool_calls
        ]
    return LLMResponse(content=content, tool_calls=tool_calls, tokens=0, message=message)


def _results(messages: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any], str]]:
    """Every finished tool call in `messages` as (name, arguments, output), in order."""
    asked: dict[str, tuple[str, dict[str, Any]]] = {}
    out = []
    for message in messages:
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except ValueError:
                arguments = {}
            asked[raw.get("id", "")] = (function.get("name", ""), arguments)
        if message.get("role") == "tool":
            name, arguments = asked.get(message.get("tool_call_id", ""), ("", {}))
            out.append((name, arguments, str(message.get("content") or "")))
    return out


def _json(output: str) -> Any:
    """The first JSON value in a tool output (they lead with a headline, then JSON)."""
    starts = [i for i in (output.find("["), output.find("{")) if i >= 0]
    # A log id like "[log_ab12]" is not JSON; raw_decode simply fails on those.
    for start in sorted(starts):
        try:
            return json.JSONDecoder().raw_decode(output[start:])[0]
        except ValueError:
            continue
    return None


def _chart(output: str) -> str:
    marker = CHART.search(output)
    return f"\n\n{marker.group(0)}" if marker else ""


def _first(results: list[tuple[str, dict[str, Any], str]], name: str, **where: Any) -> str | None:
    for tool, arguments, output in results:
        if tool == name and all(arguments.get(k) == v for k, v in where.items()):
            return output
    return None


def _diagnosis(text: str) -> Diagnosis | None:
    return next((d for message, d in DIAGNOSES.items() if message in text), None)


def _error_lines(text: str) -> list[tuple[str, str]]:
    return [(ref, msg) for ref, level, msg in LOG_LINE.findall(text) if level == "ERROR"]


# ───────────────────────────── investigator

NOT_SCRIPTED = (
    "This demo uses a scripted stand-in for the model, and it only recognises the scripted "
    "failures from the Chaos lab. On your own install, with a Groq key, the investigator "
    "reasons about any failure."
)


def _investigate(messages: list[dict[str, Any]], *, forced: bool) -> LLMResponse:
    task = next((str(m["content"]) for m in messages if m["role"] == "user"), "")
    deployment = re.search(r"deployment_id: (\S+)", task)
    commit = re.search(r"commit ([0-9a-f]{7,40})", task)
    service = re.search(r"service_id: (\S+)", task)
    results = _results(messages)
    asked = {name for name, _, _ in results}

    if not forced and not results:
        if deployment:
            ref = deployment.group(1)
            return _respond(
                "Reading the deployment and both of its logs.",
                [
                    ("get_deployment", {"deployment_id": ref}),
                    ("get_logs", {"deployment_id": ref, "kind": "build"}),
                    ("get_logs", {"deployment_id": ref, "kind": "runtime"}),
                ],
            )
        if service:
            return _respond(
                "No deployment is attached, so checking health and recent deploys.",
                [
                    ("get_health_history", {"service_id": service.group(1)}),
                    ("list_recent_deploys", {}),
                ],
            )
    if not forced and commit and "get_commit_diff" not in asked and "get_deployment" in asked:
        return _respond(
            "The logs show where it failed. Reading the commit to see what changed.",
            [("get_commit_diff", {"sha": commit.group(1)})],
        )
    report = _report(
        results,
        deployment.group(1) if deployment else None,
        commit.group(1) if commit else None,
    )
    return _respond("Enough evidence to report.", [(REPORT_TOOL, report)])


def _report(
    results: list[tuple[str, dict[str, Any], str]], deployment_id: str | None, sha: str | None
) -> dict[str, Any]:
    everything = "\n".join(output for _, _, output in results)
    logs = "\n".join(output for name, _, output in results if name == "get_logs")
    diff = _first(results, "get_commit_diff") or ""
    diagnosis = _diagnosis(everything)
    lines = LOG_LINE.findall(logs)

    if diagnosis is None:
        errors = _error_lines(logs)[:3]
        return {
            "inconclusive": True,
            "likely_cause": (
                f"The first error in the logs is: {errors[0][1]}" if errors else NOT_SCRIPTED
            ),
            "confidence": "low",
            "summary": "Not one of the scripted demo failures",
            "evidence": [{"type": "log", "ref": ref, "quote": msg} for ref, msg in errors],
            "missing": NOT_SCRIPTED,
        }

    evidence: list[dict[str, str]] = []
    for fragment in diagnosis.log_fragments:
        hit = next(((ref, msg) for ref, _, msg in lines if fragment in msg), None)
        if hit:
            evidence.append({"type": "log", "ref": hit[0], "quote": hit[1]})
    has_diff = bool(sha) and diagnosis.diff_quote in diff
    if has_diff:
        evidence.append({"type": "commit", "ref": sha or "", "quote": diagnosis.diff_quote})
    if deployment_id:
        evidence.append({"type": "deploy", "ref": deployment_id, "quote": diagnosis.deploy_quote})
    return {
        "inconclusive": False,
        "likely_cause": diagnosis.likely_cause.replace("{short}", (sha or "the latest commit")[:7]),
        "confidence": diagnosis.confidence,
        "summary": diagnosis.summary,
        "culprit_commit_sha": sha if has_diff else None,
        "evidence": evidence,
        "suggested_fix": diagnosis.suggested_fix,
    }


# ───────────────────────────── chat

Results = list[tuple[str, dict[str, Any], str]]
Handler = Callable[[str, Results], "list[Call] | str"]

CAN_ANSWER = (
    "- Which services had failed deploys this week?\n"
    "- Why did the last failed deploy fail?\n"
    "- What's the failure rate and recovery time per service?\n"
    "- How have deploys been going over time?\n"
    "- Are any services unhealthy right now?\n"
    "- Search the logs for STRIPE_WEBHOOK_SECRET\n"
    "- What did the most recent commits change?\n"
    "- Are there open incidents?"
)
GREETING = (
    "Hi. I answer questions about the deploys, logs, commits and incidents on this demo "
    "instance, and I link every fact to where it came from. Try one of these:\n\n" + CAN_ANSWER
)
FALLBACK = (
    "This public demo runs a scripted stand-in for the model, so I can only answer a fixed "
    "set of questions about the sample data. These work:\n\n" + CAN_ANSWER + "\n\n" + SELF_HOST
)
READ_ONLY = (
    "Ask Opscend is read-only: it has no tools that change anything. Roll back, redeploy or "
    "change variables in the provider's own dashboard or CLI. For a failed deploy I can tell "
    'you why it failed: ask "why did the last failed deploy fail?"'
)


def _short(iso: str | None) -> str:
    return (iso or "")[:16].replace("T", " ") + " UTC" if iso else "unknown time"


def _failed(_question: str, results: Results) -> list[Call] | str:
    found = _first(results, "search_deployments")
    if found is None:
        return [("search_deployments", {"status": "failed", "since_hours": 168})]
    rows = _json(found) or []
    if not rows:
        return "No deploys failed in the last 7 days."
    lines = [
        f"- **{row['service']}** on {row['provider']}, {_short(row.get('started_at'))}, "
        f"commit `{(row.get('commit_sha') or 'unknown')[:7]}` [deploy:{row['deployment_id']}]"
        for row in rows[:8]
    ]
    services = sorted({row["service"] for row in rows})
    return (
        f"{len(rows)} deploy(s) failed in the last 7 days, on {', '.join(services)}:\n\n"
        + "\n".join(lines)
        + '\n\nAsk "why did the last failed deploy fail?" for the cause of the newest one.'
    )


def _why(_question: str, results: Results) -> list[Call] | str:
    found = _first(results, "search_deployments")
    if found is None:
        return [("search_deployments", {"status": "failed", "limit": 1})]
    rows = _json(found) or []
    if not rows:
        return "No failed deploy is on record, so there is nothing to explain."
    row = rows[0]
    ref, sha = row["deployment_id"], row.get("commit_sha")
    runtime = _first(results, "get_logs", deployment_id=ref, kind="runtime")
    build = _first(results, "get_logs", deployment_id=ref, kind="build")
    if runtime is None or build is None:
        return [
            ("get_logs", {"deployment_id": ref, "kind": "runtime"}),
            ("get_logs", {"deployment_id": ref, "kind": "build"}),
        ]
    logs = f"{runtime}\n{build}"
    head = (
        f"The latest failed deploy is **{row['service']}** on {row['provider']} "
        f"({_short(row.get('started_at'))}) [deploy:{ref}]."
    )
    diagnosis = _diagnosis(found)
    if diagnosis is None:
        errors = _error_lines(logs)[:2]
        if not errors:
            return f"{head} Its stored logs contain no error lines, so I cannot name a cause."
        quoted = "\n".join(f"- `{msg.strip()[:160]}` [log:{ref_}]" for ref_, msg in errors)
        return f"{head} The first errors in its logs:\n\n{quoted}"
    lines = LOG_LINE.findall(logs)
    cited = []
    for fragment in diagnosis.log_fragments[:2]:
        hit = next(((log, msg) for log, _, msg in lines if fragment in msg), None)
        if hit:
            cited.append(f"- `{hit[1].strip()[:160]}` [log:{hit[0]}]")
    cause = diagnosis.likely_cause.replace("{short}", (sha or "the latest commit")[:7])
    commit = f" [commit:{sha}]" if sha else ""
    return (
        f"{head}\n\n{cause}{commit}\n\n"
        + ("The log lines that show it:\n\n" + "\n".join(cited) + "\n\n" if cited else "")
        + f"**Suggested fix:** {diagnosis.suggested_fix}"
    )


def _stats(_question: str, results: Results) -> list[Call] | str:
    found = _first(results, "deploy_stats")
    if found is None:
        return [("deploy_stats", {"since_hours": 168})]
    rows = _json(found) or []
    if not rows:
        return "No deploys were recorded in the last 7 days."
    lines = []
    for row in rows:
        recovery = row.get("mean_time_to_recovery_minutes")
        lines.append(
            f"- **{row['service']}**: {row['total']} deploys, {row['failed']} failed "
            f"({row['failure_rate'] * 100:.1f}%), "
            + (f"recovered in {recovery:.0f} min on average" if recovery else "no recovery yet")
            + f" [service:{row['service_id']}]"
        )
    return "Over the last 7 days:\n\n" + "\n".join(lines) + _chart(found)


def _trend(_question: str, results: Results) -> list[Call] | str:
    found = _first(results, "deploy_trend")
    if found is None:
        return [("deploy_trend", {"since_hours": 168})]
    headline = found.strip().splitlines()[0].rstrip(":")
    busy = [line for line in found.splitlines() if ": " in line and "none" not in line][1:]
    days = "\n".join(f"- {line}" for line in busy if not line.startswith("Chart"))
    return f"{headline}.\n\n{days}{_chart(found)}"


def _health(_question: str, results: Results) -> list[Call] | str:
    found = _first(results, "health_stats")
    if found is None:
        return [("health_stats", {"since_hours": 168})]
    rows = _json(found) or []
    if not rows:
        return "No health checks are recorded yet."
    down = [row["service"] for row in rows if row.get("down_now")]
    lead = (
        f"{', '.join(down)} is failing its health check right now."
        if down
        else "Every service is passing its health check right now."
    )
    lines = [
        f"- **{row['service']}**: {row['uptime_percent']}% up, p95 response "
        f"{row.get('p95_latency_ms')} ms, {row['outages']} outage(s) [service:{row['service_id']}]"
        for row in rows
    ]
    return f"{lead} Over the last 7 days:\n\n" + "\n".join(lines) + _chart(found)


SEARCH = re.compile(
    r"(?:search|grep|look|find)\b.*?\b(?:for|containing|with|mentioning)\s+[\"'`]?(.+?)[\"'`]?[?.!]*$",
    re.IGNORECASE,
)


def _logs(question: str, results: Results) -> list[Call] | str:
    match = SEARCH.search(question.strip())
    query = (match.group(1) if match else "error").strip()[:80]
    found = _first(results, "search_logs")
    if found is None:
        return [("search_logs", {"query": query, "since_hours": 168})]
    lines = FOUND_LINE.findall(found)
    if not lines:
        return (
            f"No stored log line contains `{query}` in the last 7 days. "
            "Try `STRIPE_WEBHOOK_SECRET` or `Healthcheck` on the sample data."
        )
    shown = "\n".join(f"- `{msg.strip()[:150]}` [log:{ref}]" for ref, _, msg in lines[:6])
    more = f"\n\n{len(lines) - 6} more line(s) match." if len(lines) > 6 else ""
    return f"{len(lines)} log line(s) contain `{query}`:\n\n{shown}{more}"


COMMIT = re.compile(r"^([0-9a-f]{40}) (\S+) (\S+ \S+) (.+?): (.*)$", re.MULTILINE)


def _commits(_question: str, results: Results) -> list[Call] | str:
    found = _first(results, "list_commits")
    if found is None:
        return [("list_commits", {"limit": 6})]
    rows = COMMIT.findall(found)[:6]
    if not rows:
        return "No commits are recorded yet."
    lines = [
        f"- {message} ({author}, {when} UTC) [commit:{sha}]"
        for sha, _, when, author, message in rows
    ]
    return "The most recent commits, newest first:\n\n" + "\n".join(lines)


def _incidents(_question: str, results: Results) -> list[Call] | str:
    found = _first(results, "list_incidents")
    if found is None:
        return [("list_incidents", {"since_hours": 168})]
    rows = _json(found) or []
    if not rows:
        return "No incidents were opened in the last 7 days."
    opened = [row for row in rows if row["status"] == "open"]
    lines = [
        f"- {row['title']} ({row['status']}, opened {_short(row.get('opened_at'))}) "
        f"[incident:{row['incident_id']}]"
        for row in rows[:8]
    ]
    return f"{len(opened)} open incident(s), {len(rows)} in the last 7 days:\n\n" + "\n".join(lines)


def _services(_question: str, results: Results) -> list[Call] | str:
    found = _first(results, "list_services")
    if found is None:
        return [("list_services", {})]
    rows = _json(found) or []
    if not rows:
        return "No services are connected yet."
    lines = []
    for row in rows:
        latest = (row.get("latest_deploy") or {}).get("status", "no deploys")
        flag = ", open incident" if row.get("open_incident") else ""
        lines.append(
            f"- **{row['name']}** on {row['provider']}: latest deploy {latest}{flag} "
            f"[service:{row['service_id']}]"
        )
    return f"{len(rows)} services are monitored:\n\n" + "\n".join(lines)


SMALL_TALK = re.compile(
    r"^\W*(h+i+e*|hello+|hey+|yo|sup|thanks?( you)?|thx|ok(ay)?|cool|nice|great"
    r"|good (morning|evening))\b",
    re.IGNORECASE,
)
WRITES = re.compile(
    r"^\W*(please )?(roll ?back|redeploy|restart|delete|revert|deploy|rerun)\b", re.I
)

# First match wins, so the specific questions come before the broad ones.
INTENTS: tuple[tuple[re.Pattern[str], Handler], ...] = (
    (re.compile(r"\b(search|grep)\b|\blogs? (for|containing|with)\b", re.I), _logs),
    (re.compile(r"\b(why|cause|what went wrong|what broke|explain)\b", re.I), _why),
    (re.compile(r"\b(rate|recovery|mttr|stats?|statistics|compare|how often)\b", re.I), _stats),
    (
        re.compile(r"\b(health|healthy|unhealthy|uptime|down|latency|response time|slow)\b", re.I),
        _health,
    ),
    (
        re.compile(
            r"\b(trend|over time|per day|chart|graph|history|how many deploys?|going)\b", re.I
        ),
        _trend,
    ),
    (re.compile(r"\bfail(ed|ing|ure|ures|s)?\b|\bbroken?\b", re.I), _failed),
    (re.compile(r"\b(commits?|changed?|changes|shipped|pushed)\b", re.I), _commits),
    (re.compile(r"\b(incidents?|outages?|alerts?)\b", re.I), _incidents),
    (re.compile(r"\b(services?|projects?|connected|status|overview)\b", re.I), _services),
)


def _chat(messages: list[dict[str, Any]], *, forced: bool) -> LLMResponse:
    asked_at = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=0)
    question = str(messages[asked_at].get("content") or "")
    results = _results(messages[asked_at + 1 :])

    if not results:
        if WRITES.search(question):
            return _respond(READ_ONLY)
        if SMALL_TALK.search(question) and len(question.split()) <= 4:
            return _respond(GREETING)
        if re.search(r"\b(what can you|help|who are you|what do you do)\b", question, re.I):
            return _respond(GREETING)
    handler = next((h for pattern, h in INTENTS if pattern.search(question)), None)
    if handler is None:
        return _respond(FALLBACK)
    step = handler(question, results)
    if isinstance(step, str):
        return _respond(step)
    if forced:
        return _respond(FALLBACK)
    return _respond("", step)
