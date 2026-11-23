"""The public demo: open to anyone, nothing real connected, the model simulated."""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select

from app.core import public_demo
from app.core.db import session_scope
from app.core.time import utcnow
from app.demo import seed
from app.models import Commit, CommitDiff, Deployment, Integration, Investigation, RawEvent
from tests.conftest import ADMIN, _clear_caches, drain_jobs, make_service, running_app

SCENARIOS = ["bad-env-var", "syntax-error", "failing-migration", "dependency-bump", "timeout"]


@pytest.fixture
async def public(env) -> AsyncIterator[httpx.AsyncClient]:
    """A visitor of the public demo: no login, no key, no waiting for the script."""
    env.setenv("OPSCEND_PUBLIC_DEMO", "1")
    env.setenv("OPSCEND_AI_SIMULATED_DELAY", "0")
    # Even with a key present, the public demo must not use it.
    env.setenv("GROQ_API_KEY", "gsk_would_cost_money")
    _clear_caches()
    public_demo._last.clear()
    async with running_app() as client:
        yield client


async def ask(client: httpx.AsyncClient, question: str) -> dict:
    public_demo._last.clear()  # the pacing is tested on its own
    created = await client.post("/api/chat/sessions", json={"content": question})
    assert created.status_code == 201, created.text
    await drain_jobs()
    reply = (await client.get(f"/api/chat/sessions/{created.json()['id']}")).json()["messages"][-1]
    assert reply["status"] == "done", reply
    return reply


async def test_a_visitor_needs_no_login_and_sees_the_seeded_demo(public):
    system = (await public.get("/api/system")).json()
    assert system["public_demo"] and system["demo_mode"]
    assert system["ai"] == {
        "provider": "demo",
        "model": "simulated",
        "configured": True,
        "simulated": True,
    }
    assert (await public.get("/api/auth/me")).json()["email"] == "demo visitor"
    overview = (await public.get("/api/overview")).json()
    assert overview["stats"]["services"] == 3 and overview["stats"]["open_incidents"] == 1
    # The seeded report is labelled as simulated too.
    seeded = (await public.get("/api/investigations")).json()[0]
    assert seeded["model"] == "simulated"


async def test_nothing_real_can_be_connected_or_reached(public):
    integration = (await public.get("/api/integrations")).json()[0]
    service = (await public.get("/api/services")).json()[0]
    blocked = [
        await public.post("/api/integrations", json={"provider": "vercel", "token": "x"}),
        await public.post(f"/api/integrations/{integration['id']}/test"),
        await public.post(f"/api/integrations/{integration['id']}/sync"),
        await public.delete(f"/api/integrations/{integration['id']}"),
        await public.patch(f"/api/services/{service['id']}", json={"health_url": "http://x.y"}),
        await public.post("/api/webhooks/vercel", content=b"{}"),
        await public.post("/api/notifications/test-email"),
        await public.post("/api/auth/login", json=ADMIN),
    ]
    assert [r.status_code for r in blocked] == [403] * len(blocked)
    assert "docker compose up" in blocked[0].json()["detail"]
    assert len((await public.get("/api/integrations")).json()) == 3
    # Harmless preferences still work, so the console can be tried hands-on.
    pinned = await public.patch(f"/api/services/{service['id']}", json={"pinned": True})
    assert pinned.status_code == 200 and pinned.json()["pinned"] is True


@pytest.mark.parametrize("scenario_id", SCENARIOS)
async def test_a_broken_deploy_is_investigated_by_the_script(public, scenario_id):
    broken = await public.post("/api/demo/break", json={"scenario_id": scenario_id})
    assert broken.status_code == 200, broken.text
    await drain_jobs()

    incident = (await public.get(f"/api/incidents/{broken.json()['incident_id']}")).json()
    assert incident["investigation_id"], "the investigation starts by itself"
    run = (await public.get(f"/api/investigations/{incident['investigation_id']}")).json()
    assert (run["status"], run["model"], run["tokens_used"]) == ("completed", "simulated", 0)
    report = run["report"]
    assert report["inconclusive"] is False
    assert report["confidence"] == ("medium" if scenario_id == "timeout" else "high")
    assert report["culprit_commit_sha"] and report["suggested_fix"]
    # Three log lines, the commit and the deploy: all verified against the tools' output.
    kinds = [item["type"] for item in report["evidence"]]
    assert kinds == ["log", "log", "log", "commit", "deploy"], kinds
    steps = [step["name"] for step in run["steps"] if step["type"] == "tool"]
    assert steps == ["get_deployment", "get_logs", "get_logs", "get_commit_diff"]


async def test_a_failure_the_script_does_not_know_is_reported_as_inconclusive(public):
    broken = (await public.post("/api/demo/break", json={"scenario_id": "syntax-error"})).json()
    await drain_jobs()
    async with session_scope() as session:
        deployment = await session.get(Deployment, broken["deployment_id"])
        rows = [
            deployment,
            await session.scalar(select(Commit).where(Commit.sha == deployment.commit_sha)),
            await session.scalar(select(CommitDiff).where(CommitDiff.sha == deployment.commit_sha)),
        ]
        deployment.commit_message = "chore: something nobody scripted"
        rows[1].message = rows[2].message = deployment.commit_message
        await session.commit()
    public_demo._last.clear()
    started = await public.post(f"/api/deployments/{broken['deployment_id']}/investigate")
    assert started.status_code == 200, started.text
    await drain_jobs()
    report = (await public.get(f"/api/investigations/{started.json()['id']}")).json()["report"]
    assert report["inconclusive"] is True and report["confidence"] == "low"
    assert "scripted" in report["missing"]
    assert report["evidence"] and all(item["type"] == "log" for item in report["evidence"])


async def test_chat_answers_the_demo_questions_with_verified_citations(public):
    why = await ask(public, "Why did the last failed deploy fail?")
    assert "STRIPE_WEBHOOK_SECRET" in why["content"]
    assert {c["type"] for c in why["citations"]} == {"deploy", "log", "commit"}
    assert [s["name"] for s in why["steps"]] == ["search_deployments", "get_logs", "get_logs"]

    failed = await ask(public, "Which services had failed deploys this week?")
    assert "storefront-api" in failed["content"] and len(failed["citations"]) == 2

    stats = await ask(public, "What's the failure rate and recovery time per service?")
    assert len(stats["charts"]) == 1 and "[chart:" in stats["content"]

    trend = await ask(public, "How have deploys been going over time?")
    assert trend["charts"][0]["title"] == "Deploys per day"

    logs = await ask(public, "Search the logs for STRIPE_WEBHOOK_SECRET")
    assert logs["citations"] and all(c["type"] == "log" for c in logs["citations"])

    health = await ask(public, "Are any services unhealthy right now?")
    assert "passing its health check" in health["content"] and health["charts"]

    commits = await ask(public, "What did the most recent commits change?")
    assert [c["type"] for c in commits["citations"]] == ["commit"] * 6


async def test_chat_is_honest_about_what_it_cannot_do(public):
    hello = await ask(public, "hiee")
    assert hello["steps"] == [] and "Try one of these" in hello["content"]

    other = await ask(public, "write me a poem about kubernetes")
    assert other["steps"] == [] and "scripted stand-in" in other["content"]

    rollback = await ask(public, "roll back storefront-api")
    assert rollback["steps"] == [] and "read-only" in rollback["content"]


async def test_one_visitor_cannot_read_anothers_questions(public):
    mine = (await public.post("/api/chat/sessions", json={"content": "hi"})).json()
    await drain_jobs()
    assert [s["id"] for s in (await public.get("/api/chat/sessions")).json()] == [mine["id"]]

    transport = httpx.ASGITransport(app=public._transport.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        assert (await other.get("/api/chat/sessions")).json() == []
        assert (await other.get(f"/api/chat/sessions/{mine['id']}")).status_code == 404
        followup = await other.post(
            f"/api/chat/sessions/{mine['id']}/messages", json={"content": "hi"}
        )
        assert followup.status_code == 404
        assert (await other.delete(f"/api/chat/sessions/{mine['id']}")).status_code == 404


async def test_a_feedback_note_is_not_kept(public):
    run = (await public.get("/api/investigations")).json()[0]
    rated = await public.put(
        f"/api/investigations/{run['id']}/feedback", json={"rating": "down", "note": "rude words"}
    )
    assert rated.status_code == 200
    assert rated.json()["feedback"] == {
        "rating": "down",
        "note": None,
        "at": rated.json()["feedback"]["at"],
    }


async def test_actions_are_paced_per_visitor(public):
    first = await public.post("/api/demo/break", json={"scenario_id": "timeout"})
    again = await public.post("/api/demo/break", json={"scenario_id": "timeout"})
    assert (first.status_code, again.status_code) == (200, 429)
    assert "try again" in again.json()["detail"]


async def test_stale_sample_data_is_rebuilt_only_when_quiet(public, env):
    async def seeded_ids() -> set[str]:
        async with session_scope() as session:
            return set((await session.scalars(select(Integration.id))).all())

    before = await seeded_ids()
    assert await seed.refresh_public_demo() is False  # freshly seeded

    env.setenv("OPSCEND_PUBLIC_DEMO_REFRESH_MINUTES", "0")
    _clear_caches()
    assert await seed.refresh_public_demo() is False  # 0 turns it off

    env.setenv("OPSCEND_PUBLIC_DEMO_REFRESH_MINUTES", "120")
    _clear_caches()
    async with session_scope() as session:
        for integration in (await session.scalars(select(Integration))).all():
            integration.last_synced_at -= seed.timedelta(hours=3)
        await session.commit()
    await public.post("/api/demo/break", json={"scenario_id": "timeout"})
    await drain_jobs()
    assert await seed.refresh_public_demo() is False  # a visitor is in the middle of something
    assert await seeded_ids() == before

    async with session_scope() as session:
        for run in (await session.scalars(select(Investigation))).all():
            run.created_at -= seed.timedelta(hours=1)
        for event in (await session.scalars(select(RawEvent))).all():
            event.received_at -= seed.timedelta(hours=1)
        await session.commit()
    assert await seed.refresh_public_demo() is True
    assert not (await seeded_ids() & before)
    assert (await public.get("/api/overview")).json()["stats"]["open_incidents"] == 1


async def test_the_simulation_is_off_unless_asked_for(demo_client):
    system = (await demo_client.get("/api/system")).json()
    assert system["public_demo"] is False and system["ai"]["simulated"] is False
    deployment = (await demo_client.get("/api/deployments?status=failed")).json()[0]
    started = await demo_client.post(f"/api/deployments/{deployment['id']}/investigate")
    assert started.status_code == 409  # no key, no simulation: the usual hint


async def test_accounts_connected_before_it_went_public_are_removed(env):
    """A real install switched to OPSCEND_PUBLIC_DEMO must not show its data to guests."""
    # A normal install, demo off, with a real connection.
    async with running_app(), session_scope() as session:
        await make_service(session, name="my-real-app")
        session.add(
            Commit(
                repo="me/private",
                sha="a" * 40,
                message="secret work",
                author="me",
                committed_at=utcnow(),
            )
        )
        await session.commit()

    env.setenv("OPSCEND_PUBLIC_DEMO", "1")
    _clear_caches()
    public_demo._last.clear()
    async with running_app() as client:
        integrations = (await client.get("/api/integrations")).json()
        assert integrations and all(i["is_demo"] for i in integrations)
        names = [s["name"] for s in (await client.get("/api/services?scope=all")).json()]
        assert len(names) == 3 and "my-real-app" not in names
        async with session_scope() as session:
            assert await session.scalar(select(Commit).where(Commit.repo == "me/private")) is None
        broke = await client.post("/api/demo/break", json={"scenario_id": "bad-env-var"})
        assert broke.status_code == 200, broke.text
