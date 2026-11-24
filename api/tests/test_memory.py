"""Incident memory: fingerprints, the deploy that resolved an incident, similar incidents."""

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.core import db
from app.core.config import API_DIR
from app.core.db import session_scope
from app.core.time import utcnow
from app.demo.scenarios import SCENARIOS_BY_ID, STRIPE_ENV
from app.incidents import fingerprint, memory, rules
from app.integrations.base import LogLineIn
from app.models import Incident
from app.services.logs import to_rows
from tests.conftest import make_deployment, make_service


def scenario_lines(scenario) -> list[tuple[str, str]]:  # noqa: ANN001
    return [
        (level, message) for _, level, message in (*scenario.build_logs, *scenario.runtime_logs)
    ]


# ───────────────────────────── fingerprints (pure)


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("bad-env-var", "Error: Missing required environment variable CACHE_URL"),
        ("syntax-error", "Parsing ecmascript source code failed"),
        ("failing-migration", 'error: column "customer_id" does not exist'),
        ("dependency-bump", "TypeError: bullmq_1.QueueScheduler is not a constructor"),
        ("timeout", "Healthcheck timed out after 300s: no response on port 8080"),
    ],
)
def test_the_headline_is_the_line_that_names_the_failure(scenario, expected):
    """Not the first error line: that is a bare path, a caret or a generic wrapper."""
    assert fingerprint.headline(scenario_lines(SCENARIOS_BY_ID[scenario])) == expected


def test_run_to_run_details_do_not_change_the_signature():
    def sign(message: str) -> str:
        return fingerprint.from_logs([("error", message)]).signature

    assert sign("Error: connect ECONNREFUSED 10.0.3.7:5432 at 2026-11-20T10:00:01Z") == sign(
        "Error: connect ECONNREFUSED 10.0.9.1:6543 at 2026-11-24T08:12:55.120Z"
    )
    assert sign("Healthcheck timed out after 300s: no response on port 8080") == sign(
        "Healthcheck timed out after 120s: no response on port 3000"
    )
    assert sign("Cannot find module '/app/dist/a1b2c3d4e5.js'") == sign(
        "Cannot find module '/app/dist/ffee99887766.js'"
    )
    # The name in the error is what it is about, so it stays.
    assert sign("TypeError: x is not a function") != sign("TypeError: y is not a function")


def test_a_different_missing_variable_is_the_same_family_not_the_same_error():
    stripe = fingerprint.from_logs(scenario_lines(STRIPE_ENV))
    cache = fingerprint.from_logs(scenario_lines(SCENARIOS_BY_ID["bad-env-var"]))
    assert stripe.signature != cache.signature
    assert stripe.family == cache.family
    assert fingerprint.similarity(stripe.error_text, cache.error_text) >= memory.MIN_TEXT_SIMILARITY


def test_unrelated_errors_are_not_similar():
    texts = [
        fingerprint.from_logs(scenario_lines(scenario)).error_text
        for scenario in SCENARIOS_BY_ID.values()
    ]
    for i, a in enumerate(texts):
        for b in texts[i + 1 :]:
            assert fingerprint.similarity(a, b) < memory.MIN_TEXT_SIMILARITY


def test_logs_without_a_message_give_no_fingerprint():
    assert fingerprint.from_logs([]) is None
    assert fingerprint.from_logs([("error", "    at main (/app/x.js:1:1)"), ("error", "^")]) is None


def test_a_health_fingerprint_belongs_to_one_service():
    a = fingerprint.from_health_check("svc_a", 503)
    assert a == fingerprint.from_health_check("svc_a", 502)  # the same class of answer
    assert a != fingerprint.from_health_check("svc_b", 503)
    assert a != fingerprint.from_health_check("svc_a", None)


# ───────────────────────────── what resolved an incident


@pytest.mark.parametrize(
    ("fix_sha", "expected"),
    [("bad", "redeploy"), ("good", "rollback"), ("new", "code_change")],
)
async def test_the_deploy_that_resolved_an_incident_is_recorded(database, fix_sha, expected):
    sha = {"good": "a" * 40, "bad": "b" * 40, "new": "c" * 40}
    async with session_scope() as session:
        service = await make_service(session)
        await make_deployment(session, service, status="ready", minutes_ago=60, sha=sha["good"])
        failed = await make_deployment(
            session, service, status="failed", minutes_ago=30, sha=sha["bad"]
        )
        incident = await rules.on_deployment(session, failed)
        await session.commit()
        fix = await make_deployment(
            session, service, status="ready", minutes_ago=5, sha=sha[fix_sha]
        )
        await rules.on_deployment(session, fix)
        await session.commit()
        await session.refresh(incident)
        assert incident.status == "resolved"
        assert (incident.resolved_by_deployment_id, incident.fix_kind) == (fix.id, expected)


# ───────────────────────────── remembering and matching


async def open_failure(
    session, service, lines: list[tuple[str, str]], minutes_ago: float
) -> Incident:  # noqa: ANN001
    failed = await make_deployment(
        session, service, status="failed", minutes_ago=minutes_ago, external_id=f"dpl_{minutes_ago}"
    )
    now = utcnow()
    build = [LogLineIn(ts=now, level="info", message="Build completed")]
    runtime = [LogLineIn(ts=now, level=level, message=message) for level, message in lines]
    session.add_all([*to_rows(failed.id, "build", build), *to_rows(failed.id, "runtime", runtime)])
    incident = await rules.on_deployment(session, failed)
    await session.commit()
    return incident


async def test_a_new_failure_finds_the_earlier_one_of_the_same_kind(database):
    async with session_scope() as session:
        api = await make_service(session, name="storefront-api", external_id="prj_api")
        web = await make_service(session, name="storefront-web", external_id="prj_web")
        stripe = await open_failure(session, api, scenario_lines(STRIPE_ENV), minutes_ago=600)
        rules.resolve(stripe)
        syntax = await open_failure(
            session, web, scenario_lines(SCENARIOS_BY_ID["syntax-error"]), minutes_ago=300
        )
        rules.resolve(syntax)
        await session.commit()
        cache = await open_failure(
            session, api, scenario_lines(SCENARIOS_BY_ID["bad-env-var"]), minutes_ago=10
        )

    assert await memory.remember_pending() == 3
    assert await memory.remember_pending() == 0  # idempotent: nothing left to look at

    async with session_scope() as session:
        cache = await session.get(Incident, cache.id)
        [match] = await memory.similar(session, cache)
        assert (match.incident.id, match.kind) == (stripe.id, "family")
        # Only earlier incidents are memory: the stripe one has nothing before it.
        assert await memory.similar(session, await session.get(Incident, stripe.id)) == []


async def test_an_incident_without_usable_logs_is_looked_at_once(database):
    async with session_scope() as session:
        service = await make_service(session)
        noise = [("error", "    at main (/app/dist/main.js:3:9)"), ("error", "^")]
        incident = await open_failure(session, service, noise, minutes_ago=5)
    assert await memory.remember_pending() == 0
    async with session_scope() as session:
        incident = await session.scalar(select(Incident).where(Incident.id == incident.id))
        assert incident.signature == ""
        assert await memory.similar(session, incident) == []


async def test_the_migration_finds_what_resolved_older_incidents(database):
    async with session_scope() as session:
        service = await make_service(session)
        failed = await make_deployment(session, service, status="failed", minutes_ago=30)
        incident = await rules.on_deployment(session, failed)
        await session.commit()
        fix = await make_deployment(session, service, status="ready", minutes_ago=5)
        await rules.on_deployment(session, fix)
        await session.commit()
    await db.get_engine().dispose()

    def downgrade_then_upgrade() -> None:
        config = Config(str(API_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(API_DIR / "migrations"))
        command.downgrade(config, "0010")
        command.upgrade(config, "head")

    await asyncio.to_thread(downgrade_then_upgrade)
    async with session_scope() as session:
        incident = await session.get(Incident, incident.id)
        assert incident.resolved_by_deployment_id == fix.id
        assert incident.signature is None  # fingerprints need logs: the job does those
