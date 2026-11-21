"""HTTP surface: auth, response shapes against the contract, demo mode, secrecy."""

import pytest
from sqlalchemy import select

from app import schemas
from app.core import crypto
from app.core.db import session_scope
from app.main import app
from app.models import Integration, Investigation, RawEvent
from tests.conftest import ADMIN, drain_jobs

PUBLIC = {
    ("GET", "/api/health"),
    ("GET", "/api/system"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/webhooks/{provider}"),
}


def api_routes() -> list[tuple[str, str]]:
    """Every (METHOD, path) the app serves, read from its own OpenAPI document."""
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    )


# ───────────────────────────── auth


async def test_public_endpoints(anon_client):
    assert (await anon_client.get("/api/health")).json() == {"status": "ok"}
    system = schemas.SystemInfo.model_validate((await anon_client.get("/api/system")).json())
    assert (system.queue, system.database, system.demo_mode) == ("inline", "sqlite", False)
    assert system.ai.model_dump() == {
        "provider": "groq",
        "model": "test-model",
        "configured": False,
    }
    assert (await anon_client.get("/api/docs")).status_code == 200
    assert "/api/timeline" in (await anon_client.get("/api/openapi.json")).json()["paths"]


async def test_every_other_route_requires_a_session(anon_client):
    protected = [route for route in api_routes() if route not in PUBLIC]
    assert len(protected) >= 25
    for method, path in protected:
        url = path.replace("{", "").replace("}", "")
        response = await anon_client.request(method, url, json={})
        assert response.status_code == 401, f"{method} {path} → {response.status_code}"
        assert response.json() == {"detail": "Not authenticated"}


async def test_login_sets_an_httponly_cookie_and_logout_clears_it(anon_client):
    bad = await anon_client.post("/api/auth/login", json={**ADMIN, "password": "wrong"})
    assert bad.status_code == 401 and "set-cookie" not in bad.headers

    response = await anon_client.post("/api/auth/login", json=ADMIN)
    user = schemas.User.model_validate(response.json())
    assert user.email == ADMIN["email"]
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("opscend_session=")
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert "password" not in response.text

    assert (await anon_client.get("/api/auth/me")).json() == response.json()
    assert (await anon_client.post("/api/auth/logout")).status_code == 200
    assert (await anon_client.get("/api/auth/me")).status_code == 401


async def test_forged_or_garbage_cookies_are_rejected(anon_client):
    import jwt

    forged = jwt.encode(
        {"sub": "anyone"}, "not-the-key-not-the-key-not-the-key!", algorithm="HS256"
    )
    for value in ("garbage", forged):
        anon_client.cookies.set("opscend_session", value)
        assert (await anon_client.get("/api/overview")).status_code == 401


async def test_empty_instance_returns_empty_shapes(client):
    overview = schemas.Overview.model_validate((await client.get("/api/overview")).json())
    assert overview.stats.services == 0 and len(overview.activity) == 24
    for path in (
        "/api/services",
        "/api/timeline",
        "/api/deployments",
        "/api/incidents",
        "/api/investigations",
        "/api/integrations",
        "/api/events",
    ):
        assert (await client.get(path)).json() == []
    assert (await client.get("/api/deployments/nope")).status_code == 404
    assert (await client.post("/api/demo/reset")).status_code == 409  # demo mode is off


# ───────────────────────────── demo data against the contract


async def test_demo_seed_matches_the_contract(demo_client):
    client = demo_client
    overview = schemas.Overview.model_validate((await client.get("/api/overview")).json())
    assert overview.stats.services == 3
    assert overview.stats.open_incidents == 1 == len(overview.incidents)
    assert overview.stats.investigations == 1
    assert len(overview.deployments) == 20
    assert all(len(service.health_history) == 24 for service in overview.services)
    assert {s.name: s.provider for s in overview.services} == {
        "storefront-web": "vercel",
        "storefront-api": "railway",
        "worker": "railway",
    }
    assert sum(b.ready + b.failed for b in overview.activity) > 0

    deployments = [
        schemas.Deployment.model_validate(item)
        for item in (await client.get("/api/deployments", params={"limit": 500})).json()
    ]
    assert len(deployments) == 40
    statuses = [d.status for d in deployments]
    assert statuses.count("failed") == 2 and statuses.count("canceled") == 1
    assert statuses.count("building") == 1 and statuses.count("ready") == 36
    assert deployments == sorted(deployments, key=lambda d: d.started_at, reverse=True)

    integrations = [
        schemas.Integration.model_validate(item)
        for item in (await client.get("/api/integrations")).json()
    ]
    assert sorted(i.provider for i in integrations) == ["github", "railway", "vercel"]
    assert all(i.is_demo and i.status == "connected" for i in integrations)

    catalog = [
        schemas.ProviderManifest.model_validate(item)
        for item in (await client.get("/api/integrations/catalog")).json()
    ]
    assert [m.provider for m in catalog if m.availability == "planned"] == [
        "render",
        "fly",
        "netlify",
        "cloudflare",
        "aws",
    ]

    incidents = [
        schemas.Incident.model_validate(i) for i in (await client.get("/api/incidents")).json()
    ]
    assert sorted(i.status for i in incidents) == ["open", "resolved"]
    only_open = (await client.get("/api/incidents", params={"status": "open"})).json()
    assert [i["status"] for i in only_open] == ["open"]


async def test_demo_failed_deploy_detail_logs_diff_and_investigation(demo_client):
    client = demo_client
    [failed] = (
        await client.get("/api/deployments", params={"status": "failed", "provider": "railway"})
    ).json()
    detail = schemas.DeploymentDetail.model_validate(
        (await client.get(f"/api/deployments/{failed['id']}")).json()
    )
    assert detail.service.name == "storefront-api"
    assert detail.commit is not None and detail.commit.sha == detail.commit_sha
    assert detail.incident_id and detail.investigation_id
    assert "RUNTIME_LOGS" in detail.capabilities

    logs = {}
    for kind in ("build", "runtime"):
        response = await client.get(f"/api/deployments/{detail.id}/logs", params={"kind": kind})
        logs[kind] = [schemas.LogLine.model_validate(line) for line in response.json()]
        assert all(line.kind == kind and line.id.startswith("log_") for line in logs[kind])
    assert 30 <= len(logs["build"]) + len(logs["runtime"]) <= 80
    assert any("STRIPE_WEBHOOK_SECRET" in line.message for line in logs["runtime"])
    again = (
        await client.get(f"/api/deployments/{detail.id}/logs", params={"kind": "runtime"})
    ).json()
    assert [line["id"] for line in again] == [line.id for line in logs["runtime"]]  # stable ids
    assert (
        await client.get(f"/api/deployments/{detail.id}/logs", params={"kind": "nope"})
    ).status_code == 422

    diff = schemas.CommitDiff.model_validate(
        (await client.get(f"/api/deployments/{detail.id}/diff")).json()
    )
    assert diff.sha == detail.commit_sha and len(diff.files) == 3

    investigation = schemas.Investigation.model_validate(
        (await client.get(f"/api/investigations/{detail.investigation_id}")).json()
    )
    assert investigation.status == "completed" and investigation.service_name == "storefront-api"
    assert [s.index for s in investigation.steps] == list(range(7))
    assert {s.type for s in investigation.steps} == {"llm", "tool", "report"}
    assert investigation.steps[-1].name == "submit_report"
    assert investigation.tokens_used == sum(s.tokens or 0 for s in investigation.steps)

    # Every evidence ref in the seeded report points at something that really exists.
    log_ids = {line.id for line in logs["runtime"]} | {line.id for line in logs["build"]}
    deploy_ids = {
        d["id"] for d in (await client.get("/api/deployments", params={"limit": 500})).json()
    }
    report = investigation.report
    assert report is not None and report.culprit_commit_sha == detail.commit_sha
    assert {e.type for e in report.evidence} == {"log", "commit", "deploy"}
    for evidence in report.evidence:
        if evidence.type == "log":
            assert evidence.ref in log_ids and evidence.deployment_id == detail.id
        elif evidence.type == "commit":
            assert evidence.ref == detail.commit_sha
        else:
            assert evidence.ref in deploy_ids

    listed = (await client.get("/api/investigations")).json()
    assert [i["id"] for i in listed] == [investigation.id]

    # A deploy whose commit has no stored diff, with no real GitHub connected.
    [other] = (await client.get("/api/deployments", params={"status": "canceled"})).json()
    assert (await client.get(f"/api/deployments/{other['id']}/diff")).status_code == 404


async def test_demo_timeline_merges_and_filters(demo_client):
    client = demo_client
    raw = (await client.get("/api/timeline", params={"limit": 500})).json()
    kinds = {item["kind"] for item in raw}
    assert kinds == {"deployment", "commit", "incident"}
    assert len(raw) == 40 + 23 + 2
    assert [i["at"] for i in raw] == sorted((i["at"] for i in raw), reverse=True)
    for item in raw:
        assert set(item) == {"kind", "id", "at", "provider", item["kind"]}
    assert all(i["provider"] == "github" for i in raw if i["kind"] == "commit")
    assert len((await client.get("/api/timeline")).json()) == 65
    assert len((await client.get("/api/timeline", params={"limit": 5})).json()) == 5

    vercel = (await client.get("/api/timeline", params={"provider": "vercel"})).json()
    assert {i["provider"] for i in vercel} == {"vercel"} and {i["kind"] for i in vercel} == {
        "deployment",
        "incident",
    }
    failed = (await client.get("/api/timeline", params={"status": "failed"})).json()
    assert [i["deployment"]["status"] for i in failed] == ["failed", "failed"]
    github = (await client.get("/api/timeline", params={"provider": "github"})).json()
    assert {i["kind"] for i in github} == {"commit"}

    worker = next(s for s in (await client.get("/api/services")).json() if s["name"] == "worker")
    scoped = (await client.get("/api/timeline", params={"service_id": worker["id"]})).json()
    assert all(
        i["deployment"]["service_id"] == worker["id"] for i in scoped if i["kind"] == "deployment"
    )
    assert (await client.get("/api/timeline", params={"service_id": "nope"})).status_code == 404


@pytest.mark.parametrize(
    "scenario_id",
    ["bad-env-var", "syntax-error", "failing-migration", "dependency-bump", "timeout"],
)
async def test_demo_break_goes_through_the_ingest_pipeline(demo_client, scenario_id):
    client = demo_client
    scenarios = [
        schemas.DemoScenario.model_validate(s)
        for s in (await client.get("/api/demo/scenarios")).json()
    ]
    assert len(scenarios) == 5
    before = len((await client.get("/api/deployments", params={"limit": 500})).json())

    response = await client.post("/api/demo/break", json={"scenario_id": scenario_id})
    assert response.status_code == 200, response.text
    result = schemas.DemoBreakResult.model_validate(response.json())

    detail = (await client.get(f"/api/deployments/{result.deployment_id}")).json()
    assert detail["status"] == "failed" and detail["incident_id"] == result.incident_id
    assert detail["commit"] is not None  # arrived through the GitHub push webhook
    assert detail["duration_ms"] > 0
    incident = (await client.get(f"/api/incidents/{result.incident_id}")).json()
    assert (incident["status"], incident["trigger"]) == ("open", "deploy_failed")
    assert incident["deployment_id"] == result.deployment_id

    # One open incident per service still holds after the break.
    open_incidents = (await client.get("/api/incidents", params={"status": "open"})).json()
    assert len({i["service_id"] for i in open_incidents}) == len(open_incidents)

    top = (await client.get("/api/timeline", params={"limit": 6})).json()
    assert result.deployment_id in {i["id"] for i in top}
    assert result.incident_id in {i["id"] for i in top}

    logs = (await client.get(f"/api/deployments/{result.deployment_id}/logs")).json()
    assert any(line["level"] == "error" for line in logs) or scenario_id in (
        "bad-env-var",
        "dependency-bump",
        "timeout",
    )
    assert (await client.get(f"/api/deployments/{result.deployment_id}/diff")).json()[
        "sha"
    ] == detail["commit_sha"]

    async with session_scope() as session:
        events = (await session.scalars(select(RawEvent).where(RawEvent.source == "demo"))).all()
    assert {"push"} < {event.event_type for event in events}
    assert all(event.processed_at and not event.error for event in events)
    expected_new = 2 if detail["service_name"] == "storefront-api" else 1  # + healthy web deploy
    after = len((await client.get("/api/deployments", params={"limit": 500})).json())
    assert after - before == expected_new

    assert (await client.post("/api/demo/break", json={"scenario_id": "nope"})).status_code == 404


async def test_demo_reset_restores_the_seed(demo_client):
    client = demo_client
    await client.post("/api/demo/break", json={"scenario_id": "syntax-error"})
    assert (await client.post("/api/demo/reset")).json() == {"status": "ok"}
    assert len((await client.get("/api/deployments", params={"limit": 500})).json()) == 40
    assert len((await client.get("/api/incidents")).json()) == 2
    assert (await client.get("/api/events")).json() == []
    assert len((await client.get("/api/investigations")).json()) == 1


async def test_incident_can_be_resolved_by_hand(demo_client):
    [incident] = (await demo_client.get("/api/incidents", params={"status": "open"})).json()
    resolved = (await demo_client.post(f"/api/incidents/{incident['id']}/resolve")).json()
    assert resolved["status"] == "resolved" and resolved["resolved_at"]
    assert (await demo_client.get("/api/overview")).json()["stats"]["open_incidents"] == 0


async def test_service_health_url_can_be_edited(demo_client):
    [service, *_] = (await demo_client.get("/api/services")).json()
    updated = await demo_client.patch(f"/api/services/{service['id']}", json={"health_url": ""})
    assert schemas.Service.model_validate(updated.json()).health_url is None


# ───────────────────────────── investigator endpoints


async def test_investigate_without_a_key_is_409_with_a_hint(demo_client):
    [failed, *_] = (await demo_client.get("/api/deployments", params={"status": "failed"})).json()
    [incident] = (await demo_client.get("/api/incidents", params={"status": "open"})).json()
    for url in (
        f"/api/deployments/{failed['id']}/investigate",
        f"/api/incidents/{incident['id']}/investigate",
    ):
        response = await demo_client.post(url)
        assert response.status_code == 409
        assert "GROQ_API_KEY" in response.json()["detail"]
    assert len((await demo_client.get("/api/investigations")).json()) == 1  # nothing was created


@pytest.fixture
async def ai_client(env):
    """Demo client with a (fake) key configured and the model call stubbed out."""
    from app.investigator import orchestrator
    from tests.conftest import _clear_caches, running_app
    from tests.test_investigator import FakeLLM, report, turn

    env.setenv("OPSCEND_DEMO", "1")
    env.setenv("GROQ_API_KEY", "gsk_fake_key_for_tests")
    _clear_caches()

    def fake_llm():
        def play(request):
            if len(request["messages"]) == 2:
                target = request["messages"][1]["content"].split("deployment_id: ")[1].split(" ")[0]
                return turn(("get_logs", {"deployment_id": target, "kind": "runtime"}))
            return turn(report(culprit_commit_sha=None))

        return FakeLLM(play)

    env.setattr(orchestrator, "build_llm", fake_llm)
    async with running_app() as client:
        assert (await client.post("/api/auth/login", json=ADMIN)).status_code == 200
        yield client


async def test_investigate_creates_a_queued_run_that_the_job_completes(ai_client):
    client = ai_client
    assert (await client.get("/api/system")).json()["ai"]["configured"] is True
    [failed] = (
        await client.get("/api/deployments", params={"status": "failed", "provider": "railway"})
    ).json()

    response = await client.post(f"/api/deployments/{failed['id']}/investigate")
    assert response.status_code == 200, response.text
    started = schemas.Investigation.model_validate(response.json())
    assert started.status in ("queued", "running") and started.report is None
    assert started.deployment_id == failed["id"] and started.incident_id is not None

    # Asking again while it runs returns the same investigation instead of a second one.
    again = await client.post(f"/api/deployments/{failed['id']}/investigate")
    assert again.json()["id"] == started.id

    await drain_jobs()
    done = schemas.Investigation.model_validate(
        (await client.get(f"/api/investigations/{started.id}")).json()
    )
    assert done.status == "completed" and done.report is not None
    assert [s.type for s in done.steps] == ["llm", "tool", "llm", "report"]
    assert done.duration_ms is not None

    detail = (await client.get(f"/api/deployments/{failed['id']}")).json()
    assert detail["investigation_id"] == started.id  # the most recent one
    newest = (await client.get("/api/investigations")).json()[0]
    assert newest["id"] == started.id

    [incident] = (await client.get("/api/incidents", params={"status": "open"})).json()
    from_incident = await client.post(f"/api/incidents/{incident['id']}/investigate")
    assert from_incident.status_code == 200
    assert from_incident.json()["deployment_id"] == failed["id"]
    await drain_jobs()


async def test_orphaned_investigations_are_failed_on_startup(env):
    from tests.conftest import running_app

    async with running_app(), session_scope() as session:
        session.add(Investigation(model="m", status="running"))
        await session.commit()
    async with running_app(), session_scope() as session:
        investigation = await session.scalar(select(Investigation))
        assert investigation.status == "failed" and "restart" in investigation.error


# ───────────────────────────── secrecy


async def test_no_token_or_secret_in_any_response(demo_client):
    """Walk every GET endpoint (and the docs) and look for any stored secret."""
    client = demo_client
    async with session_scope() as session:
        integrations = (await session.scalars(select(Integration))).all()
        secrets = {crypto.decrypt(i.token_encrypted) for i in integrations}
        secrets |= {i.token_encrypted for i in integrations}
        secrets |= {i.webhook_secret_encrypted for i in integrations}
        secrets.add(crypto.decrypt(integrations[0].webhook_secret_encrypted))
    assert len(secrets) == 10

    await client.post("/api/demo/break", json={"scenario_id": "bad-env-var"})
    ids = {
        "deployment_id": (await client.get("/api/deployments")).json()[0]["id"],
        "incident_id": (await client.get("/api/incidents")).json()[0]["id"],
        "investigation_id": (await client.get("/api/investigations")).json()[0]["id"],
        "integration_id": (await client.get("/api/integrations")).json()[0]["id"],
        "service_id": (await client.get("/api/services")).json()[0]["id"],
        "session_id": "no-such-chat",
    }
    bodies = []
    for method, path in api_routes():
        if method == "GET":
            response = await client.get(path.format(**ids), params={"limit": 200})
            assert response.status_code in (200, 404), path
            bodies.append(response.text)
    for integration_id in [i["id"] for i in (await client.get("/api/integrations")).json()]:
        bodies.append((await client.post(f"/api/integrations/{integration_id}/test")).text)
        bodies.append((await client.post(f"/api/integrations/{integration_id}/sync")).text)
    assert len(bodies) > 20
    for body in bodies:
        assert "token_encrypted" not in body and "password_hash" not in body
        for secret in secrets:
            assert secret not in body
    integration = (await client.get("/api/integrations")).json()[0]
    assert len(integration["token_hint"]) == 4
    assert "token" not in {key for key in integration if key != "token_hint"}


async def test_api_reference_is_served_in_the_opscend_skin(anon_client):
    page = await anon_client.get("/api/docs")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "/api/docs/assets/theme.css" in page.text and "/api/openapi.json" in page.text
    assert "ops-bar" in page.text and "Opscend API reference" in page.text

    theme = await anon_client.get("/api/docs/assets/theme.css")
    assert theme.status_code == 200 and theme.headers["content-type"].startswith("text/css")
    assert (await anon_client.get("/api/docs/assets/sherlog.svg")).status_code == 200
    # Only the listed assets are served: no path tricks.
    assert (await anon_client.get("/api/docs/assets/..%2F..%2Fmain.py")).status_code == 404
    # The page itself is not an API operation.
    assert "/api/docs" not in (await anon_client.get("/api/openapi.json")).json()["paths"]
