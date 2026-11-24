"""Incident open/resolve rules, exercised through the normalizer and the health checker."""

import asyncio
from datetime import timedelta

import httpx
import respx
from sqlalchemy import select

from app.core.db import session_scope
from app.core.time import utcnow
from app.incidents import health, rules
from app.incidents.health import run_health_checks
from app.ingest.normalizer import apply_batch
from app.integrations.base import DeploymentIn, NormalizedBatch
from app.models import Deployment, HealthCheck, Incident, Investigation
from tests.conftest import _clear_caches, drain_jobs, make_deployment, make_service

PROJECT = "prj_QmT4wq1storefront"


def deploy(external_id: str, status: str, minutes_ago: float) -> NormalizedBatch:
    started = utcnow() - timedelta(minutes=minutes_ago)
    finished = started + timedelta(seconds=30) if status in ("ready", "failed") else None
    return NormalizedBatch(
        deployments=[
            DeploymentIn(
                service_external_id=PROJECT,
                external_id=external_id,
                status=status,
                commit_sha="9f2c1e7a44d0b6c3a1f5e8d27b90c4a6e3d1f052",
                started_at=started,
                finished_at=finished,
            )
        ]
    )


async def incidents(session) -> list[Incident]:
    session.expire_all()
    return list((await session.scalars(select(Incident).order_by(Incident.opened_at))).all())


async def test_failed_deploy_opens_one_incident_and_replays_are_idempotent(database):
    async with session_scope() as session:
        await make_service(session)
        for _ in range(3):
            await apply_batch(session, "vercel", deploy("dpl_1", "failed", 5))
        [incident] = await incidents(session)
        deployment = await session.scalar(select(Deployment))
        assert incident.trigger == "deploy_failed"
        assert incident.status == "open"
        assert incident.deployment_id == deployment.id
        assert incident.title == "Deploy failed on storefront-web at 9f2c1e7"


async def test_only_one_open_incident_per_service(database):
    async with session_scope() as session:
        await make_service(session)
        await apply_batch(session, "vercel", deploy("dpl_1", "failed", 5))
        await apply_batch(session, "vercel", deploy("dpl_2", "failed", 3))
        assert len(await incidents(session)) == 1


async def test_each_service_gets_its_own_incident(database):
    async with session_scope() as session:
        await make_service(session)
        await make_service(session, name="docs", external_id="prj_docs")
        await apply_batch(session, "vercel", deploy("dpl_1", "failed", 5))
        other = deploy("dpl_9", "failed", 4)
        other.deployments[0].service_external_id = "prj_docs"
        await apply_batch(session, "vercel", other)
        assert {i.service.name for i in await incidents(session)} == {"storefront-web", "docs"}


async def test_later_ready_deploy_resolves_the_incident(database):
    async with session_scope() as session:
        await make_service(session)
        await apply_batch(session, "vercel", deploy("dpl_1", "failed", 5))
        await apply_batch(session, "vercel", deploy("dpl_2", "building", 2))
        assert (await incidents(session))[0].status == "open"  # not fixed until it is ready
        await apply_batch(session, "vercel", deploy("dpl_2", "ready", 2))
        [incident] = await incidents(session)
        assert incident.status == "resolved"
        assert incident.resolved_at is not None
        assert incident.open_slot is None


async def test_an_older_ready_deploy_does_not_resolve(database):
    async with session_scope() as session:
        await make_service(session)
        await apply_batch(session, "vercel", deploy("dpl_2", "failed", 5))
        await apply_batch(session, "vercel", deploy("dpl_1", "ready", 30))  # late, older event
        assert (await incidents(session))[0].status == "open"


async def test_a_superseded_failure_opens_nothing(database):
    """Backfilling history must not page anyone about a failure that was already fixed."""
    async with session_scope() as session:
        await make_service(session)
        await apply_batch(session, "vercel", deploy("dpl_2", "ready", 10))
        await apply_batch(session, "vercel", deploy("dpl_1", "failed", 60))
        assert await incidents(session) == []


async def test_resolved_failure_does_not_reopen_and_a_new_failure_opens_a_new_incident(database):
    async with session_scope() as session:
        await make_service(session)
        await apply_batch(session, "vercel", deploy("dpl_1", "failed", 9))
        await apply_batch(session, "vercel", deploy("dpl_2", "ready", 6))
        await apply_batch(session, "vercel", deploy("dpl_1", "failed", 9))  # replayed webhook
        assert [i.status for i in await incidents(session)] == ["resolved"]
        await apply_batch(session, "vercel", deploy("dpl_3", "failed", 1))
        assert [i.status for i in await incidents(session)] == ["resolved", "open"]


async def test_canceled_deploy_opens_nothing_and_status_never_moves_backwards(database):
    async with session_scope() as session:
        await make_service(session)
        await apply_batch(session, "vercel", deploy("dpl_1", "canceled", 5))
        await apply_batch(session, "vercel", deploy("dpl_2", "ready", 3))
        await apply_batch(session, "vercel", deploy("dpl_2", "building", 4))  # out of order
        assert await incidents(session) == []
        latest = await session.scalar(select(Deployment).where(Deployment.external_id == "dpl_2"))
        assert latest.status == "ready"
        assert latest.finished_at is not None


@respx.mock
async def test_health_incident_needs_two_failures_and_resolves_when_healthy(database):
    url = "https://storefront.example.test/health"
    async with session_scope() as session:
        await make_service(session, health_url=url)
        await make_service(session, name="no-url", external_id="prj_none")

    route = respx.get(url).respond(200)
    async with httpx.AsyncClient() as http:
        assert await run_health_checks(http) == 1  # only the service with a URL
        route.mock(return_value=httpx.Response(503))
        await run_health_checks(http)
        async with session_scope() as session:
            assert await incidents(session) == []  # one failure is a blip

        await run_health_checks(http)
        async with session_scope() as session:
            [incident] = await incidents(session)
            assert (incident.trigger, incident.status) == ("health_check_failed", "open")
            assert incident.deployment_id is None

        route.mock(side_effect=httpx.ConnectError("refused"))
        await run_health_checks(http)
        async with session_scope() as session:
            assert len(await incidents(session)) == 1
            last = await session.scalar(
                select(HealthCheck).order_by(HealthCheck.checked_at.desc()).limit(1)
            )
            assert (last.ok, last.status_code) == (False, None)

        route.mock(return_value=httpx.Response(200))
        await run_health_checks(http)
        async with session_scope() as session:
            [incident] = await incidents(session)
            assert incident.status == "resolved"


@respx.mock
async def test_health_failure_does_not_displace_an_open_deploy_incident(database):
    url = "https://storefront.example.test/health"
    respx.get(url).respond(500)
    async with session_scope() as session:
        await make_service(session, health_url=url)
        await apply_batch(session, "vercel", deploy("dpl_1", "failed", 5))
    async with httpx.AsyncClient() as http:
        await run_health_checks(http)
        await run_health_checks(http)
    async with session_scope() as session:
        [incident] = await incidents(session)
        assert incident.trigger == "deploy_failed"


@respx.mock
async def test_health_probes_run_in_parallel_up_to_the_limit(database, monkeypatch):
    """One slow service must not hold up the others, and the limit caps open requests."""
    monkeypatch.setattr(health, "MAX_CONCURRENT_PROBES", 2)
    in_flight = peak = 0

    async def slow(request):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return httpx.Response(200)

    async with session_scope() as session:
        for n in range(5):
            url = f"https://svc{n}.example.test/health"
            respx.get(url).mock(side_effect=slow)
            await make_service(session, name=f"svc{n}", external_id=f"prj_{n}", health_url=url)
    async with httpx.AsyncClient() as http:
        assert await run_health_checks(http) == 5
    assert peak == 2
    async with session_scope() as session:
        assert len((await session.scalars(select(HealthCheck))).all()) == 5


async def test_an_old_failure_is_history_not_an_incident(database, monkeypatch):
    """A months-old failed deploy that arrives in a backfill must not page anyone."""
    monkeypatch.setattr(rules, "INCIDENT_MAX_AGE", timedelta(hours=24))
    async with session_scope() as session:
        service = await make_service(session)
        stale = await make_deployment(session, service, status="failed", minutes_ago=60 * 30)
        assert await rules.on_deployment(session, stale) is None
        recent = await make_deployment(session, service, status="failed", minutes_ago=30)
        assert await rules.on_deployment(session, recent) is not None


@respx.mock
async def test_a_service_that_was_never_healthy_is_down_but_not_an_incident(database):
    url = "https://dead-project.example.test/"
    async with session_scope() as session:
        await make_service(session, health_url=url)
    respx.get(url).respond(404)
    async with httpx.AsyncClient() as http:
        for _ in range(4):
            await run_health_checks(http)
    async with session_scope() as session:
        assert await incidents(session) == []
        assert (await session.scalars(select(HealthCheck))).all()[-1].ok is False


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ automatic investigation


def _with_ai(env, **settings: str) -> None:
    """Configure a (fake) LLM key and stub the model with one that reports straight away."""
    from app.core import queue as queue_module
    from app.investigator import orchestrator
    from app.main import JOBS
    from tests.test_investigator import FakeLLM, report, turn

    env.setenv("GROQ_API_KEY", "gsk_fake_key_for_tests")
    for key, value in settings.items():
        env.setenv(key, value)
    _clear_caches()
    # These tests drive the normalizer directly, so there is no app to start the queue.
    env.setattr(queue_module, "_queue", queue_module.InlineQueue(JOBS))
    env.setattr(
        orchestrator,
        "build_llm",
        lambda: FakeLLM(lambda request: turn(report(inconclusive=True, culprit_commit_sha=None))),
    )


async def _investigations(session) -> list[Investigation]:
    session.expire_all()
    return list((await session.scalars(select(Investigation))).all())


async def test_a_failed_deploy_is_investigated_without_a_click(database, env):
    _with_ai(env)
    async with session_scope() as session:
        await make_service(session)
        for _ in range(2):  # a replayed event must not start a second run
            await apply_batch(session, "vercel", deploy("dpl_1", "failed", 5))
        await drain_jobs()
        [incident] = await incidents(session)
        incident_id, deployment_id = incident.id, incident.deployment_id
        [investigation] = await _investigations(session)
        assert investigation.incident_id == incident_id
        assert investigation.deployment_id == deployment_id
        assert investigation.status == "completed"


async def test_automatic_investigation_needs_a_key_and_can_be_switched_off(database, env):
    async with session_scope() as session:  # no key configured
        await make_service(session)
        await apply_batch(session, "vercel", deploy("dpl_1", "failed", 5))
        assert len(await incidents(session)) == 1
        assert await _investigations(session) == []

    _with_ai(env, OPSCEND_AUTO_INVESTIGATE="0")
    async with session_scope() as session:
        await apply_batch(session, "vercel", deploy("dpl_2", "ready", 4))
        await apply_batch(session, "vercel", deploy("dpl_3", "failed", 3))
        await drain_jobs()
        assert len(await incidents(session)) == 2
        assert await _investigations(session) == []


async def test_automatic_investigation_stops_at_the_daily_limit(database, env):
    _with_ai(env, OPSCEND_AUTO_INVESTIGATE_DAILY_LIMIT="1")
    async with session_scope() as session:
        await make_service(session)
        await apply_batch(session, "vercel", deploy("dpl_1", "failed", 5))
        await apply_batch(session, "vercel", deploy("dpl_2", "ready", 4))
        await apply_batch(session, "vercel", deploy("dpl_3", "failed", 3))
        await drain_jobs()
        assert len(await incidents(session)) == 2
        assert len(await _investigations(session)) == 1
