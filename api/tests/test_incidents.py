"""Incident open/resolve rules, exercised through the normalizer and the health checker."""

from datetime import timedelta

import httpx
import respx
from sqlalchemy import select

from app.core.db import session_scope
from app.core.time import utcnow
from app.incidents.health import run_health_checks
from app.ingest.normalizer import apply_batch
from app.integrations.base import DeploymentIn, NormalizedBatch
from app.models import Deployment, HealthCheck, Incident
from tests.conftest import make_service

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

    route = respx.get(url).respond(503)
    async with httpx.AsyncClient() as http:
        assert await run_health_checks(http) == 1  # only the service with a URL
        async with session_scope() as session:
            assert await incidents(session) == []  # one failure is a blip

        await run_health_checks(http)
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
