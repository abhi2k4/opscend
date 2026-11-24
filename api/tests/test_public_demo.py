"""The public demo: open to anyone, nothing real connected, the model simulated."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy import select

from app.core import db, public_demo, security
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.time import utcnow
from app.demo import sandbox, seed
from app.models import (
    Commit,
    CommitDiff,
    DemoSandbox,
    Deployment,
    Integration,
    Investigation,
    User,
)
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
        await client.get("/api/system")  # the first response carries the visitor cookie
        await client.get("/api/system")  # the second one starts the private copy
        yield client


def mine(client: httpx.AsyncClient):  # noqa: ANN201
    """Database access to this visitor's private copy: `with mine(client): ...`."""
    return db.use_sandbox(sandbox.name_for(client.cookies[public_demo.VISITOR_COOKIE]))


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
        "self_hosted": False,
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
    with mine(public):
        session_ctx = session_scope()
    async with session_ctx as session:
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


@asynccontextmanager
async def other_visitor(public: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    """A second browser on the same app."""
    async with httpx.AsyncClient(transport=public._transport, base_url="http://test") as other:
        await other.get("/api/system")
        await other.get("/api/system")
        yield other


async def test_each_visitor_explores_a_private_copy(public):
    async with other_visitor(public) as other:
        before = (await other.get("/api/overview")).json()
        services = (await public.get("/api/services")).json()
        # Same ids as the shared data, so a page loaded before the cookie arrived still works.
        assert [s["id"] for s in (await other.get("/api/services")).json()] == [
            s["id"] for s in services
        ]

        broken = await public.post("/api/demo/break", json={"scenario_id": "syntax-error"})
        assert broken.status_code == 200, broken.text
        await drain_jobs()
        muted = await public.patch(f"/api/services/{services[0]['id']}", json={"muted": True})
        assert muted.status_code == 200, muted.text

        mine_now = (await public.get("/api/overview")).json()
        assert mine_now["stats"]["open_incidents"] == before["stats"]["open_incidents"] + 1
        assert len((await public.get("/api/investigations")).json()) == 2
        # The other visitor, and the shared data new visitors start from, saw none of it.
        assert (await other.get("/api/overview")).json()["stats"] == before["stats"]
        assert len((await other.get("/api/investigations")).json()) == 1
        missing = await other.get(f"/api/deployments/{broken.json()['deployment_id']}")
        assert missing.status_code == 404
        assert not any(s["muted"] for s in (await other.get("/api/services")).json())
        async with session_scope() as session:
            assert len((await session.scalars(select(Investigation))).all()) == 1

        # Reset only rebuilds the copy of the visitor who pressed it.
        public_demo._last.clear()
        assert (
            await other.post("/api/demo/break", json={"scenario_id": "syntax-error"})
        ).status_code == 200
        await drain_jobs()
        assert (await public.post("/api/demo/reset")).status_code == 200
        assert (await public.get("/api/overview")).json()["stats"]["open_incidents"] == 1
        assert (await other.get("/api/overview")).json()["stats"]["open_incidents"] == 2


async def test_a_client_without_the_cookie_reads_shared_data_and_changes_nothing(public):
    async with httpx.AsyncClient(transport=public._transport, base_url="http://test") as bare:
        refused = await bare.post("/api/demo/break", json={"scenario_id": "timeout"})
        assert refused.status_code == 409 and "cookies" in refused.json()["detail"]
        bare.cookies.clear()
        assert (await bare.get("/api/overview")).json()["stats"]["services"] == 3
    async with session_scope() as session:
        assert len((await session.scalars(select(DemoSandbox))).all()) == 1  # only `public`


async def test_idle_and_surplus_sandboxes_are_deleted(public, env):
    async def sandboxes() -> list[str]:
        async with session_scope() as session:
            return list((await session.scalars(select(DemoSandbox.id))).all())

    first = await sandboxes()
    folder = db.sandbox_dir()
    assert len(first) == 1 and (folder / f"{first[0]}.db").exists()

    env.setenv("OPSCEND_PUBLIC_DEMO_MAX_SESSIONS", "1")
    # Reload the settings only. Clearing the engine caches too would orphan the first
    # sandbox's open SQLite connection, and Windows refuses to delete an open file.
    get_settings.cache_clear()
    async with other_visitor(public) as other:
        assert (await other.get("/api/overview")).status_code == 200
        second = await sandboxes()
        assert len(second) == 1 and second != first  # the older one made room
        assert not (folder / f"{first[0]}.db").exists()

        assert await seed.refresh_public_demo() is False  # in use: kept
        async with session_scope() as session:
            row = await session.get(DemoSandbox, second[0])
            row.last_seen_at -= seed.timedelta(hours=3)
            await session.commit()
        assert await seed.refresh_public_demo() is False
        assert await sandboxes() == []
        # Coming back later simply starts a fresh copy.
        assert (await other.get("/api/overview")).json()["stats"]["open_incidents"] == 1
        assert len(await sandboxes()) == 1


async def test_stale_shared_sample_data_is_rebuilt(public, env):
    async def seeded_ids() -> set[str]:
        async with session_scope() as session:
            return set((await session.scalars(select(Integration.id))).all())

    before = await seeded_ids()
    assert await seed.refresh_public_demo() is False  # freshly seeded
    async with session_scope() as session:
        for integration in (await session.scalars(select(Integration))).all():
            integration.created_at -= seed.timedelta(hours=3)
        await session.commit()

    env.setenv("OPSCEND_PUBLIC_DEMO_REFRESH_MINUTES", "0")
    _clear_caches()
    assert await seed.refresh_public_demo() is False  # 0 turns it off

    env.setenv("OPSCEND_PUBLIC_DEMO_REFRESH_MINUTES", "120")
    _clear_caches()
    assert await seed.refresh_public_demo() is True
    assert not (await seeded_ids() & before)
    # A visitor in the middle of something keeps the copy they were working in.
    mine_ids = {i["id"] for i in (await public.get("/api/integrations")).json()}
    assert mine_ids == before


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


async def test_a_leftover_login_cookie_is_ignored(public):
    """Someone who signed in before the site became a demo is a guest like everyone else."""
    async with session_scope() as session:
        admin = await session.scalar(select(User))
    public.cookies.set(security.SESSION_COOKIE, security.create_session_token(admin.id))
    me = await public.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "demo visitor"
    assert (await public.get("/api/overview")).status_code == 200
