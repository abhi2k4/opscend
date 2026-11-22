"""Ask Opscend: the query tools, citation checks, the answer loop and the HTTP API."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import schemas
from app.chat import citations
from app.chat.orchestrator import BUDGET_NOTE, run_chat_reply
from app.chat.service import NOT_PICKED_UP, expire_stale_replies
from app.chat.tools import CHAT_TOOL_SPECS, ChatLedger, ChatTools
from app.core.db import session_scope
from app.core.time import utcnow
from app.integrations.base import LogLineIn
from app.investigator.llm import LLMResponse
from app.investigator.tools import TOOL_SPECS
from app.models import ChatMessage, ChatSession, Commit, HealthCheck, Incident, LogLine
from app.services.logs import to_rows
from app.services.retention import prune_old_data
from tests.conftest import ADMIN, SECRET_TOKEN, drain_jobs, make_deployment, make_service
from tests.test_investigator import INJECTION, FakeLLM, turn

SHA = "bb083918c9be1579a96112ac2a5779ee95256c89"


def answer(text: str, tokens: int = 50) -> LLMResponse:
    return LLMResponse(
        content=text, tool_calls=[], tokens=tokens, message={"role": "assistant", "content": text}
    )


async def world() -> dict[str, str]:
    """Two services: an API with a failure then a recovery, and a healthy web app."""
    async with session_scope() as session:
        api = await make_service(
            session, provider="railway", name="storefront-api", external_id="svc-api"
        )
        web = await make_service(session, name="storefront-web", external_id="prj-web")
        await make_deployment(session, api, status="ready", minutes_ago=300, sha="a" * 40)
        failed = await make_deployment(session, api, status="failed", minutes_ago=120, sha=SHA)
        fixed = await make_deployment(session, api, status="ready", minutes_ago=60, sha="c" * 40)
        old = await make_deployment(
            session, api, status="failed", minutes_ago=60 * 24 * 40, sha="d" * 40
        )
        web_ok = await make_deployment(session, web, status="ready", minutes_ago=30, sha="e" * 40)
        start = failed.started_at
        session.add_all(
            to_rows(
                failed.id,
                "runtime",
                [
                    LogLineIn(ts=start, level="info", message="Starting Container"),
                    LogLineIn(
                        ts=start + timedelta(seconds=1),
                        level="error",
                        message="Error: connect ECONNREFUSED 10.0.0.4:5432 (100% of retries)",
                    ),
                    LogLineIn(ts=start + timedelta(seconds=2), level="error", message=INJECTION),
                ],
            )
        )
        session.add_all(
            to_rows(
                old.id,
                "build",
                [LogLineIn(ts=old.started_at, level="error", message="ECONNREFUSED long ago")],
            )
        )
        session.add(
            Commit(
                repo="acme/storefront",
                sha=SHA,
                message="feat(db): move to the new Postgres host",
                author="Priya Nair",
                committed_at=utcnow() - timedelta(minutes=125),
            )
        )
        incident = Incident(
            service_id=api.id,
            trigger="deploy_failed",
            status="resolved",
            title="storefront-api deploy failed",
            dedup_key=f"deploy:{failed.id}",
            deployment_id=failed.id,
            opened_at=failed.started_at,
            resolved_at=fixed.finished_at,
        )
        session.add(incident)
        session.add(
            HealthCheck(
                service_id=web.id, status_code=200, latency_ms=80, ok=True, checked_at=utcnow()
            )
        )
        await session.commit()
        return {
            "api": api.id,
            "web": web.id,
            "failed": failed.id,
            "fixed": fixed.id,
            "old": old.id,
            "web_ok": web_ok.id,
            "incident": incident.id,
        }


@pytest.fixture
async def t(database):
    async with session_scope() as session:
        yield ChatTools(session, ChatLedger())


# ───────────────────────────── tools


async def test_chat_tools_are_read_only_and_extend_the_investigators(t):
    names = {spec["function"]["name"] for spec in CHAT_TOOL_SPECS}
    assert {spec["function"]["name"] for spec in TOOL_SPECS} < names
    assert names - {spec["function"]["name"] for spec in TOOL_SPECS} == {
        "list_services",
        "search_deployments",
        "search_logs",
        "list_incidents",
        "list_commits",
        "deploy_stats",
        "deploy_trend",
    }
    public = {
        name
        for cls in ChatTools.__mro__
        if cls is not object
        for name in vars(cls)
        if not name.startswith("_") and callable(getattr(ChatTools, name))
    }
    assert public == names | {"call"}
    assert (await t.call("delete_service", {})).startswith("error: unknown tool")


async def test_search_deployments_filters_by_service_name_status_and_window(t):
    ids = await world()
    out = await t.call("search_deployments", {"service": "API", "status": "failed"})
    assert ids["failed"] in out and ids["fixed"] not in out
    assert ids["old"] not in out  # outside the default 7-day window
    assert ids["failed"] in t.ledger.deploys and SHA in t.ledger.commits
    assert "<untrusted_data" in out  # commit messages are wrapped

    wide = await t.call("search_deployments", {"service": "storefront-api", "since_hours": 2000})
    assert ids["old"] in wide
    assert (await t.call("search_deployments", {"service": None, "provider": "vercel"})).count(
        '"deployment_id"'
    ) == 1
    missing = await t.call("search_deployments", {"service": "billing"})
    assert missing.startswith("error: no service matches") and "storefront-web" in missing


async def test_search_logs_spans_deployments_escapes_wildcards_and_wraps_text(t):
    ids = await world()
    out = await t.call("search_logs", {"query": "econnrefused"})
    assert "1 matching line(s) across 1 deployment(s)" in out  # the 40-day-old one is excluded
    [log_id] = [ref for ref, (dep, _) in t.ledger.logs.items() if dep == ids["failed"]]
    assert f"[{log_id}]" in out and ids["failed"] in t.ledger.deploys

    assert "100% of retries" in await t.call("search_logs", {"query": "100%"})
    assert "No stored log lines" in await t.call("search_logs", {"query": "0%_"})
    assert (await t.call("search_logs", {"query": "x"})).startswith("error:")

    injected = await t.call("search_logs", {"query": "IGNORE ALL"})
    body = injected.split("<untrusted_data", 1)[1]
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in body and "<\\/untrusted_data>" in body
    long_ago = await t.call("search_logs", {"query": "long ago", "since_hours": "2000"})
    assert ids["old"] in long_ago


async def test_incidents_commits_services_and_stats(t):
    ids = await world()

    incidents = json.loads(await t.call("list_incidents", {"service": "storefront-api"}))
    assert [i["incident_id"] for i in incidents] == [ids["incident"]]
    assert ids["incident"] in t.ledger.incidents and ids["failed"] in t.ledger.deploys
    assert await t.call("list_incidents", {"status": "open"}) == "No incidents match those filters."

    commits = await t.call("list_commits", {"query": "postgres", "author": "priya"})
    assert SHA in commits and SHA in t.ledger.commits

    services = json.loads(await t.call("list_services", {}))
    by_name = {s["name"]: s for s in services}
    assert by_name["storefront-web"]["health"]["ok"] is True
    assert by_name["storefront-api"]["latest_deploy"]["deployment_id"] == ids["fixed"]

    stats = await t.call("deploy_stats", {"service": "storefront-api"})
    [api] = json.loads(stats.split("\n", 1)[1])
    assert api["total"] == 3 and api["failed"] == 1 and api["failure_rate"] == 0.333
    # failed started 120 min ago; the fix finished 60 min ago + 90 s
    assert api["mean_time_to_recovery_minutes"] == 61.5
    assert api["last_failure"]["deployment_id"] == ids["failed"]
    assert api["avg_build_seconds"] == 90.0


# ───────────────────────────── citations


async def test_citations_keep_verified_ids_and_drop_invented_ones(t):
    ids = await world()
    await t.call("search_logs", {"query": "ECONNREFUSED"})
    await t.call("list_incidents", {})
    [log_id] = list(t.ledger.logs)
    text = (
        f"It failed [deploy:{ids['failed']}] because of `ECONNREFUSED` [log:{log_id}], "
        f"opened [incident:{ids['incident']}], from [commit:{SHA[:7]}] on "
        f"[service:{ids['api']}]. Also [deploy:made-up-id] and [log:log_0000000000]."
    )
    async with session_scope() as session:
        cleaned, cited, _ = await citations.resolve(session, text, t.ledger)
    assert "made-up-id" not in cleaned and "log_0000000000" not in cleaned
    assert cleaned.endswith("Also and.")
    assert f"[commit:{SHA}]" in cleaned  # canonicalized to the full sha
    by_type = {c["type"]: c for c in cited}
    assert set(by_type) == {"deploy", "log", "incident", "commit", "service"}
    assert by_type["deploy"]["label"] == "storefront-api · failed · bb08391"
    assert by_type["log"]["deployment_id"] == ids["failed"]
    assert "ECONNREFUSED" in by_type["log"]["detail"]
    assert by_type["commit"]["url"] == f"https://github.com/acme/storefront/commit/{SHA}"
    assert by_type["service"]["label"] == "storefront-api"


async def test_citations_repair_common_model_slips(t):
    await world()
    await t.call("search_logs", {"query": "ECONNREFUSED"})
    [log_id] = list(t.ledger.logs)
    deploy_id = next(iter(t.ledger.deploys))
    odd_hyphens = deploy_id.replace("-", "\u2011")
    text = (
        f"Crashed [{log_id}] twice [{log_id}, log_0000000000] in 【deploy:{odd_hyphens}】; "
        f"see [log:{log_id}; deploy:{deploy_id}]. Rate 6%\u202f[deploy_stats:0] [deploy_stats]. "
        "Kept: [build, runtime] and [x]."
    )
    async with session_scope() as session:
        cleaned, cited, _ = await citations.resolve(session, text, t.ledger)
    assert cleaned == (
        f"Crashed [log:{log_id}] twice [log:{log_id}] in [deploy:{deploy_id}]; "
        f"see [log:{log_id}] [deploy:{deploy_id}]. Rate 6%. Kept: [build, runtime] and [x]."
    )
    assert [c["ref"] for c in cited] == [log_id, deploy_id]


# ───────────────────────────── the answer loop


async def pending_question(question: str, session_id: str | None = None) -> str:
    async with session_scope() as session:
        if session_id is None:
            chat = ChatSession(title=question)
            session.add(chat)
            await session.flush()
            index = 0
        else:
            chat = await session.get(ChatSession, session_id)
            index = len(chat.messages)
        session.add(ChatMessage(session_id=chat.id, index=index, role="user", content=question))
        reply = ChatMessage(session_id=chat.id, index=index + 1, role="assistant", status="pending")
        session.add(reply)
        await session.commit()
        return reply.id


async def reply(message_id: str) -> ChatMessage:
    async with session_scope() as session:
        return await session.get(ChatMessage, message_id)


async def test_reply_uses_tools_then_answers_with_verified_citations(database):
    ids = await world()
    message_id = await pending_question("Why did the API fail?")

    def first(request):
        system = request["messages"][1]["content"]
        assert "storefront-api" in system and "<untrusted_data" in system
        return turn(("search_deployments", {"service": "storefront-api", "status": "failed"}))

    llm = FakeLLM(
        first,
        answer(f"It failed on a DB host change [deploy:{ids['failed']}] [deploy:invented]."),
    )
    await run_chat_reply(message_id, llm)

    message = await reply(message_id)
    assert message.status == "done" and message.error is None
    assert message.content == f"It failed on a DB host change [deploy:{ids['failed']}]."
    assert [c["ref"] for c in message.citations] == [ids["failed"]]
    assert [(s["name"], s["status"]) for s in message.steps] == [("search_deployments", "ok")]
    assert message.tokens == 150 and message.model == "fake-model"
    assert llm.requests[0]["tool_choice"] == "auto"
    assert SECRET_TOKEN not in json.dumps([r["messages"] for r in llm.requests])
    async with session_scope() as session:
        chat = await session.get(ChatSession, message.session_id)
        assert chat.tokens_used == 150


async def test_follow_up_sees_history_and_may_cite_earlier_ids(database):
    ids = await world()
    first_id = await pending_question("What failed?")
    await run_chat_reply(
        first_id,
        FakeLLM(
            turn(("search_deployments", {"status": "failed"})),
            answer(f"This one [deploy:{ids['failed']}]."),
        ),
    )
    session_id = (await reply(first_id)).session_id
    second_id = await pending_question("And when was it fixed?", session_id)
    llm = FakeLLM(answer(f"Right after [deploy:{ids['failed']}]."))
    await run_chat_reply(second_id, llm)

    history = [m for m in llm.requests[0]["messages"] if m["role"] != "system"]
    assert [m["role"] for m in history] == ["user", "assistant", "user"]
    assert (await reply(second_id)).citations[0]["ref"] == ids["failed"]


async def test_tool_budget_forces_an_answer(database, env):
    from app.core.config import get_settings

    await world()
    env.setenv("OPSCEND_AI_MAX_TOOL_CALLS", "2")
    get_settings.cache_clear()
    message_id = await pending_question("Dig deep")

    def play(request):
        if request["tool_choice"] == "none":
            return answer("Here is what I found.")
        return turn(("list_services", {}), ("list_incidents", {}), ("deploy_stats", {}))

    llm = FakeLLM(play)
    await run_chat_reply(message_id, llm)
    message = await reply(message_id)
    assert message.status == "done" and message.content == "Here is what I found."
    assert len(message.steps) == 2
    assert BUDGET_NOTE in llm.tool_outputs()
    assert llm.requests[-1]["tool_choice"] == "none"


async def test_empty_answer_fails_the_message_and_records_why(database):
    message_id = await pending_question("Hello?")
    await run_chat_reply(message_id, FakeLLM(answer("   ")))
    message = await reply(message_id)
    assert message.status == "failed" and "empty answer" in message.error
    await run_chat_reply(message_id, FakeLLM(answer("late")))  # only pending messages run
    assert (await reply(message_id)).status == "failed"


async def test_lost_jobs_are_failed_so_the_conversation_unblocks(database):
    fresh = await pending_question("Just asked")
    lost = await pending_question("Asked while the worker was down")
    stuck = await pending_question("Crashed mid-answer")
    async with session_scope() as session:
        (await session.get(ChatMessage, lost)).created_at = utcnow() - timedelta(minutes=3)
        crashed = await session.get(ChatMessage, stuck)
        crashed.status, crashed.created_at = "running", utcnow() - timedelta(minutes=7)
        await session.commit()

    assert await expire_stale_replies() == 2
    assert (await reply(fresh)).status == "pending"
    assert (await reply(lost)).status == "failed" and (await reply(lost)).error == NOT_PICKED_UP
    assert (await reply(stuck)).status == "failed"


# ───────────────────────────── retention


async def test_prune_deletes_old_logs_and_checks_only(database):
    ids = await world()
    counts = await prune_old_data()
    assert counts == {"log_line": 1, "health_check": 0}
    async with session_scope() as session:
        kept = (await session.scalars(select(LogLine.deployment_id))).all()
    assert set(kept) == {ids["failed"]}


async def test_retention_zero_keeps_everything(database, env):
    from app.core.config import get_settings

    await world()
    env.setenv("OPSCEND_RETENTION_DAYS", "0")
    get_settings.cache_clear()
    assert await prune_old_data() == {}


# ───────────────────────────── HTTP API


async def test_asking_without_a_key_is_refused(client):
    response = await client.post("/api/chat/sessions", json={"content": "hi"})
    assert response.status_code == 409 and "GROQ_API_KEY" in response.json()["detail"]
    assert (await client.get("/api/chat/sessions")).json() == []


@pytest.fixture
async def chat_client(env):
    from app.chat import orchestrator
    from tests.conftest import _clear_caches, running_app

    env.setenv("GROQ_API_KEY", "gsk_fake_key_for_tests")
    _clear_caches()
    answers = iter(["Two services are connected.", "Still two."])
    env.setattr(orchestrator, "build_llm", lambda: FakeLLM(answer(next(answers))))
    async with running_app() as client:
        assert (await client.post("/api/auth/login", json=ADMIN)).status_code == 200
        yield client


async def test_conversation_round_trip(chat_client):
    client = chat_client
    created = await client.post("/api/chat/sessions", json={"content": "  How many services?  "})
    assert created.status_code == 201
    chat = created.json()
    assert chat["title"] == "How many services?"
    assert [(m["role"], m["status"]) for m in chat["messages"]] == [
        ("user", "done"),
        ("assistant", "pending"),
    ]
    busy = await client.post(f"/api/chat/sessions/{chat['id']}/messages", json={"content": "?"})
    assert busy.status_code == 409

    await drain_jobs()
    chat = (await client.get(f"/api/chat/sessions/{chat['id']}")).json()
    assert chat["messages"][1]["status"] == "done"
    assert chat["messages"][1]["content"] == "Two services are connected."

    followup = await client.post(
        f"/api/chat/sessions/{chat['id']}/messages", json={"content": "And now?"}
    )
    assert [m["index"] for m in followup.json()["messages"]] == [0, 1, 2, 3]
    await drain_jobs()
    chat = (await client.get(f"/api/chat/sessions/{chat['id']}")).json()
    assert chat["messages"][3]["content"] == "Still two."
    assert chat["tokens_used"] == 100

    [summary] = (await client.get("/api/chat/sessions")).json()
    assert summary["id"] == chat["id"] and "messages" not in summary
    assert (await client.post("/api/chat/sessions", json={"content": ""})).status_code == 422
    assert (await client.delete(f"/api/chat/sessions/{chat['id']}")).status_code == 204
    assert (await client.get(f"/api/chat/sessions/{chat['id']}")).status_code == 404


def test_optional_tool_parameters_accept_null():
    """Models send null for filters they do not use; the provider rejects it unless the schema allows it."""
    for spec in CHAT_TOOL_SPECS:
        parameters = spec["function"]["parameters"]
        for name, schema in parameters["properties"].items():
            optional = name not in parameters["required"]
            assert ("null" in schema["type"]) is optional, (spec["function"]["name"], name)
            if optional and "enum" in schema:
                assert None in schema["enum"]


def test_the_prompt_tells_the_model_to_read_intent_before_using_tools():
    from app.chat.prompts import SYSTEM_PROMPT

    assert "First decide what the message is asking for" in SYSTEM_PROMPT
    assert "call no tools" in SYSTEM_PROMPT


# ───────────────────────────── charts


async def test_tools_build_charts_from_stored_data(t):
    await world()
    stats = await t.call("deploy_stats", {"since_hours": 24})
    assert "Chart ready" in stats
    [(chart_id, chart)] = t.ledger.charts.items()
    assert f"[chart:{chart_id}]" in stats
    assert (chart["kind"], chart["unit"]) == ("bars", "deploys")
    assert chart["categories"] == ["storefront-api", "storefront-web"]
    series = {item["name"]: item["values"] for item in chart["series"]}
    # API: one failure then a recovery (plus an older ready deploy); web: one ready deploy.
    assert series == {"Ready": [2.0, 1.0], "Failed": [1.0, 0.0]}  # the empty "Other" is dropped

    trend = await t.call("deploy_trend", {"service": "storefront-api", "since_hours": 24})
    assert "Deploys per hour" in trend and "Chart ready" in trend
    hourly = list(t.ledger.charts.values())[1]
    assert hourly["title"] == "Deploys per hour for storefront-api"
    assert len(hourly["categories"]) in (25, 26)
    assert sum(sum(item["values"]) for item in hourly["series"]) == 3

    daily = await t.call("deploy_trend", {"since_hours": 24 * 60})
    assert "Deploys per day" in daily
    assert len(list(t.ledger.charts.values())[2]["categories"]) in (61, 62)

    assert "no service matches" in await t.call("deploy_trend", {"service": "billing"})
    assert len(t.ledger.charts) == 3


async def test_a_chart_needs_more_than_one_point(t):
    assert t.ledger.add_chart("bars", "One bar", "deploys", ["a"], [("Ready", "ok", [3.0])]) == ""
    assert (
        t.ledger.add_chart("bars", "Empty", "deploys", ["a", "b"], [("Ready", "ok", [0, 0])]) == ""
    )
    assert t.ledger.charts == {}


async def test_only_charts_a_tool_built_survive_and_each_appears_once(t):
    await world()
    await t.call("deploy_stats", {"since_hours": 24})
    [chart_id] = t.ledger.charts
    text = (
        f"Deploys were mostly fine. [chart:{chart_id}] The API failed once. "
        f"[chart:chart_9invented] Again: [chart:{chart_id}]."
    )
    async with session_scope() as session:
        cleaned, _, charts = await citations.resolve(session, text, t.ledger)
    assert [chart["id"] for chart in charts] == [chart_id]
    assert (
        cleaned
        == f"Deploys were mostly fine.\n\n[chart:{chart_id}]\n\nThe API failed once. Again:."
    )
    assert "invented" not in cleaned


async def test_reply_stores_its_chart_and_history_drops_the_marker(database):
    await world()
    first_id = await pending_question("How have deploys been going?")
    seen: dict[str, str] = {}

    def conclude(request):
        tool_output = request["messages"][-1]["content"]
        seen["id"] = tool_output.split("[chart:")[1].split("]")[0]
        return answer(f"Mostly green, one failure.\n\n[chart:{seen['id']}]")

    await run_chat_reply(first_id, FakeLLM(turn(("deploy_trend", {"since_hours": 24})), conclude))
    message = await reply(first_id)
    assert message.status == "done"
    assert [chart["id"] for chart in message.charts] == [seen["id"]]
    assert message.charts[0]["kind"] == "bars"
    assert schemas.ChatMessage.model_validate(message).charts[0].series[0].tone == "ok"

    follow_up = await pending_question("And yesterday?", session_id=message.session_id)
    llm = FakeLLM(answer("Same picture."))
    await run_chat_reply(follow_up, llm)
    history = json.dumps(llm.requests[0]["messages"][2:])  # after the two system messages
    assert "Mostly green" in history and "[chart:" not in history
    assert (await reply(follow_up)).charts == []
