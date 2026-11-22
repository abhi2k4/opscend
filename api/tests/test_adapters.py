"""Adapter contract tests against recorded-style provider responses (no live calls)."""

import hashlib
import hmac
import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.integrations import registry
from app.integrations.base import (
    CommitSource,
    DeploymentRef,
    ProviderAdapter,
    ProviderError,
    ResourceUnavailableError,
    ServiceRef,
    WebhookVerificationError,
)
from app.integrations.github import GitHubAdapter
from app.integrations.railway import API as RAILWAY_API
from app.integrations.railway import RailwayAdapter
from app.integrations.vercel import VercelAdapter
from app.schemas import Capability
from tests.conftest import FIXTURES, load_fixture

SINCE = datetime(2026, 11, 1, tzinfo=UTC)
SECRET = "whsec_test"
TOKEN = "tok_super_secret_value"


def raw(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ───────────────────────────── registry


ALL_PROVIDERS = ["vercel", "railway", "github", "render", "fly", "netlify", "cloudflare", "aws"]


def test_registry_lists_every_adapter_in_order():
    catalog = registry.catalog()
    assert [m.provider for m in catalog] == ALL_PROVIDERS
    assert all(m.availability == "available" for m in catalog)
    assert registry.get_adapter_class("heroku") is None


@pytest.mark.parametrize("provider", ALL_PROVIDERS)
def test_adapters_satisfy_the_protocol(provider):
    adapter = registry.build_adapter(provider, TOKEN)
    assert isinstance(adapter, ProviderAdapter)
    assert adapter.manifest.provider == adapter.provider == provider
    assert set(adapter.manifest.capabilities) == set(adapter.capabilities)
    assert TOKEN not in repr(adapter)


def test_github_is_a_commit_source_not_a_deploy_provider():
    assert isinstance(GitHubAdapter(TOKEN), CommitSource)
    assert Capability.LIST_DEPLOYS not in GitHubAdapter.capabilities
    assert {Capability.COMMITS, Capability.COMMIT_DIFF} <= GitHubAdapter.capabilities


# ───────────────────────────── vercel


@respx.mock
async def test_vercel_validate_sends_bearer_token_and_team():
    route = respx.get("https://api.vercel.com/v2/user").respond(
        json={"user": {"username": "acme-dana", "email": "dana@acme.dev"}}
    )
    account = await VercelAdapter(TOKEN, {"team_id": "team_9xAcme"}).validate()
    assert account.account_name == "acme-dana"
    request = route.calls.last.request
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.url.params["teamId"] == "team_9xAcme"


@respx.mock
async def test_vercel_bad_token_raises_without_leaking_it():
    respx.get("https://api.vercel.com/v2/user").respond(403, json={"error": {"code": "forbidden"}})
    with pytest.raises(ProviderError) as error:
        await VercelAdapter(TOKEN).validate()
    assert TOKEN not in str(error.value)


@respx.mock
async def test_vercel_list_services():
    respx.get("https://api.vercel.com/v10/projects").respond(
        json=load_fixture("vercel_projects.json")
    )
    services = await VercelAdapter(TOKEN).list_services()
    assert [(s.external_id, s.name, s.repo) for s in services] == [
        ("prj_QmT4wq1storefront", "storefront-web", "acme/storefront"),
        ("prj_Zk81docsSite", "docs", None),
    ]
    # A project with a live production deployment brings its URL and that deployment along,
    # so the service can be health-checked and show its last deploy without extra calls.
    web, docs = services
    assert web.health_url == "https://storefront.acme.dev"
    assert web.latest_deployment.external_id == "dpl_7Hq2LastProdStorefrontWeb01"
    assert web.latest_deployment.status == "ready" and web.latest_deployment.branch == "main"
    assert docs.health_url is None and docs.latest_deployment is None


@respx.mock
async def test_vercel_deployments_are_normalized():
    route = respx.get("https://api.vercel.com/v6/deployments").respond(
        json=load_fixture("vercel_deployments.json")
    )
    service = ServiceRef(external_id="prj_QmT4wq1storefront", name="storefront-web")
    failed, ready, building = await VercelAdapter(TOKEN).list_deployments(service, SINCE)

    assert route.calls.last.request.url.params["projectId"] == "prj_QmT4wq1storefront"
    assert route.calls.last.request.url.params["since"] == str(int(SINCE.timestamp() * 1000))

    assert failed.status == "failed"
    assert failed.external_id == "dpl_8mErrorBuild"
    assert failed.service_external_id == "prj_QmT4wq1storefront"
    assert failed.commit_sha == "9f2c1e7a44d0b6c3a1f5e8d27b90c4a6e3d1f052"
    assert failed.commit_message == "feat(web): product image zoom"  # first line only
    assert failed.commit_author == "Dana Okafor"
    assert failed.branch == "main"
    assert failed.environment == "production"
    assert failed.url == "https://storefront-web-8merror-acme.vercel.app"
    assert (failed.finished_at - failed.started_at).total_seconds() == 37

    assert (ready.status, ready.environment, ready.commit_author) == (
        "ready",
        "preview",
        "dana-okafor",
    )
    assert (building.status, building.finished_at, building.commit_sha) == ("building", None, None)


@respx.mock
async def test_vercel_build_logs_handle_both_event_shapes():
    respx.get("https://api.vercel.com/v3/deployments/dpl_8mErrorBuild/events").respond(
        json=load_fixture("vercel_events.json")
    )
    ref = DeploymentRef("dpl_8mErrorBuild", ServiceRef("prj_QmT4wq1storefront", "storefront-web"))
    adapter = VercelAdapter(TOKEN)
    lines = await adapter.get_logs(ref, "build")
    assert [line.level for line in lines] == ["info", "info", "warn", "error", "error"]
    assert lines[1].message == "Installing dependencies..."
    assert lines[-1].message.startswith("Error: Command")


@respx.mock
async def test_vercel_runtime_logs_are_read_from_the_stream():
    records = [
        {"source": "delimiter", "timestampInMs": 1795082400000, "message": ""},
        {
            "source": "serverless",
            "level": "error",
            "timestampInMs": 1795082402000,
            "message": "TypeError: Cannot read properties of undefined\n",
        },
        {
            "source": "request",
            "level": "info",
            "timestampInMs": "1795082401000",
            "message": "",
            "requestMethod": "GET",
            "requestPath": "/api/cart",
            "responseStatusCode": "500",
        },
        {
            "source": "serverless",
            "level": "warning",
            "timestampInMs": 1795082403000,
            "message": "slow",
        },
    ]
    stream = "\n".join([json.dumps(record) for record in records] + ["not json", ""])
    route = respx.get(
        "https://api.vercel.com/v1/projects/prj_1/deployments/dpl_1/runtime-logs"
    ).respond(text=stream)
    ref = DeploymentRef("dpl_1", ServiceRef("prj_1", "web"))
    lines = await VercelAdapter(TOKEN, {"team_id": "team_9"}).get_logs(ref, "runtime")
    assert route.calls.last.request.url.params["teamId"] == "team_9"
    assert [(line.level, line.message) for line in lines] == [
        ("error", "GET /api/cart → 500"),
        ("error", "TypeError: Cannot read properties of undefined"),
        ("warn", "slow"),
    ]

    # Expired logs are an empty answer, not an error; a bad token still is one.
    route.respond(410)
    assert await VercelAdapter(TOKEN).get_logs(ref, "runtime") == []
    route.respond(403)
    with pytest.raises(ProviderError):
        await VercelAdapter(TOKEN).get_logs(ref, "runtime")


def test_vercel_webhook_signature_and_normalization():
    body = raw("vercel_webhook_deployment_error.json")
    signature = hmac.new(SECRET.encode(), body, hashlib.sha1).hexdigest()
    adapter = VercelAdapter(TOKEN, webhook_secret=SECRET)

    [event] = adapter.parse_webhook({"X-Vercel-Signature": signature}, body)
    assert (event.event_type, event.dedup_key) == ("deployment.error", "vercel:evt_3kd9Zp0aQ1")

    [deployment] = VercelAdapter.normalize(event.event_type, event.payload).deployments
    assert deployment.status == "failed"
    assert deployment.external_id == "dpl_8mErrorBuild"
    assert deployment.service_external_id == "prj_QmT4wq1storefront"
    assert deployment.commit_sha.startswith("9f2c1e7")
    assert deployment.finished_at == deployment.started_at

    assert VercelAdapter.normalize("project.created", event.payload).deployments == []


@pytest.mark.parametrize("signature", ["", "deadbeef", "sha1=nope"])
def test_vercel_webhook_rejects_bad_signature(signature):
    body = raw("vercel_webhook_deployment_error.json")
    with pytest.raises(WebhookVerificationError):
        VercelAdapter(TOKEN, webhook_secret=SECRET).parse_webhook(
            {"x-vercel-signature": signature}, body
        )


def test_webhook_without_a_configured_secret_is_rejected():
    body = raw("vercel_webhook_deployment_error.json")
    signature = hmac.new(b"", body, hashlib.sha1).hexdigest()
    with pytest.raises(WebhookVerificationError):
        VercelAdapter(TOKEN).parse_webhook({"x-vercel-signature": signature}, body)


def test_vercel_webhook_rejects_a_tampered_body():
    body = raw("vercel_webhook_deployment_error.json")
    signature = hmac.new(SECRET.encode(), body, hashlib.sha1).hexdigest()
    with pytest.raises(WebhookVerificationError):
        VercelAdapter(TOKEN, webhook_secret=SECRET).parse_webhook(
            {"x-vercel-signature": signature},
            body.replace(b"deployment.error", b"deployment.ready"),
        )


# ───────────────────────────── railway


@respx.mock
async def test_railway_validate_and_graphql_errors():
    route = respx.post(RAILWAY_API).respond(
        json={"data": {"me": {"name": "Priya", "email": "p@a"}}}
    )
    assert (await RailwayAdapter(TOKEN).validate()).account_name == "Priya"
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"

    respx.post(RAILWAY_API).respond(json={"errors": [{"message": "Not Authorized"}]})
    with pytest.raises(ProviderError, match="rejected the token"):
        await RailwayAdapter(TOKEN).validate()


@respx.mock
async def test_railway_workspace_token_validates_through_projects():
    """Workspace tokens cannot query `me`; listing projects proves the token works."""

    def reply(request: httpx.Request) -> httpx.Response:
        if "me {" in json.loads(request.content)["query"]:
            return httpx.Response(200, json={"errors": [{"message": "Not Authorized"}]})
        return httpx.Response(200, json=load_fixture("railway_projects.json"))

    respx.post(RAILWAY_API).mock(side_effect=reply)
    assert (await RailwayAdapter(TOKEN).validate()).account_name.startswith("workspace")


@respx.mock
async def test_railway_services_carry_project_and_environments():
    respx.post(RAILWAY_API).respond(json=load_fixture("railway_projects.json"))
    api, worker = await RailwayAdapter(TOKEN).list_services()
    assert (api.external_id, api.name) == ("5d0c7c1e-8f43-4b1e-9a57-2f6d1c0e8a11", "storefront-api")
    assert worker.name == "worker"
    assert api.meta["project_id"] == "c1f0a6de-2b7c-4d3e-9f18-6e5a4b3c2d10"
    assert api.meta["environments"] == {"env-prod-0001": "production", "env-stg-0002": "staging"}


@respx.mock
async def test_railway_deployments_are_normalized():
    route = respx.post(RAILWAY_API).respond(json=load_fixture("railway_deployments.json"))
    service = ServiceRef(
        external_id="5d0c7c1e-8f43-4b1e-9a57-2f6d1c0e8a11",
        name="storefront-api",
        meta={"project_id": "c1f0a6de", "environments": {"env-prod-0001": "production"}},
    )
    deployments = await RailwayAdapter(TOKEN).list_deployments(service, SINCE)
    variables = json.loads(route.calls.last.request.content)["variables"]
    assert variables["input"] == {"projectId": "c1f0a6de", "serviceId": service.external_id}

    failed, removed = deployments  # the October deployment is older than `since`
    assert failed.status == "failed"
    assert failed.commit_sha == "bb083918c9be1579a96112ac2a5779ee95256c89"
    assert failed.commit_message == "feat(payments): verify Stripe webhook signatures"
    assert failed.commit_author == "Priya Nair"
    assert failed.environment == "production"
    assert (failed.finished_at - failed.started_at).total_seconds() == 160
    # A superseded deploy shows as REMOVED on Railway; it did deploy, so it stays "ready".
    assert (removed.status, removed.finished_at) == ("ready", None)
    assert removed.url == "https://storefront-api-production.up.railway.app"


@respx.mock
async def test_railway_runtime_logs():
    route = respx.post(RAILWAY_API).respond(json=load_fixture("railway_deployment_logs.json"))
    ref = DeploymentRef("dep-failed-0003", ServiceRef("svc", "storefront-api"))
    lines = await RailwayAdapter(TOKEN).get_logs(ref, "runtime", limit=200)
    assert "deploymentLogs" in json.loads(route.calls.last.request.content)["query"]
    assert [line.level for line in lines] == ["info", "error", "error", "warn"]
    assert "STRIPE_WEBHOOK_SECRET" in lines[1].message


def test_railway_webhook_uses_a_shared_secret_header():
    body = raw("railway_webhook_failed.json")
    adapter = RailwayAdapter(TOKEN, webhook_secret=SECRET)
    [event] = adapter.parse_webhook({"X-Webhook-Secret": SECRET}, body)
    [again] = adapter.parse_webhook({"Authorization": f"Bearer {SECRET}"}, body)
    assert event.dedup_key == again.dedup_key == "railway:dep-failed-0003:Deployment.failed:failed"

    [deployment] = RailwayAdapter.normalize(event.event_type, event.payload).deployments
    assert deployment.status == "failed"
    assert deployment.external_id == "dep-failed-0003"
    assert deployment.service_external_id == "5d0c7c1e-8f43-4b1e-9a57-2f6d1c0e8a11"
    assert deployment.environment == "production"
    assert deployment.commit_author == "Priya Nair"

    for headers in ({}, {"X-Webhook-Secret": "wrong"}, {"Authorization": "Bearer wrong"}):
        with pytest.raises(WebhookVerificationError):
            adapter.parse_webhook(headers, body)


def test_railway_ignores_non_deployment_events():
    payload = {"type": "VolumeAlert.triggered", "resource": {"service": {"id": "svc"}}}
    assert RailwayAdapter.normalize("VolumeAlert.triggered", payload).deployments == []


# ───────────────────────────── github


@respx.mock
async def test_github_commits_and_repo_selection():
    respx.get("https://api.github.com/user").respond(json={"login": "acme-bot"})
    commits_route = respx.get("https://api.github.com/repos/acme/storefront/commits").respond(
        json=load_fixture("github_commits.json")
    )
    adapter = GitHubAdapter(TOKEN, {"repos": "acme/storefront, acme/api ,"})
    assert (await adapter.validate()).account_name == "acme-bot"
    assert await adapter.list_repos() == ["acme/storefront", "acme/api"]

    first, second = await adapter.list_commits("acme/storefront", SINCE)
    assert commits_route.calls.last.request.url.params["since"] == "2026-11-01T00:00:00Z"
    assert first.sha == "bb083918c9be1579a96112ac2a5779ee95256c89"
    assert first.author == "Priya Nair"
    assert first.committed_at == datetime(2026, 11, 18, 5, 51, 30, tzinfo=UTC)
    assert first.url.endswith(first.sha)
    assert second.author == "dana-okafor"  # falls back to the login


@respx.mock
async def test_github_falls_back_to_recently_pushed_repos():
    respx.get("https://api.github.com/user/repos").respond(
        json=[{"full_name": "acme/storefront"}, {"full_name": "acme/infra"}]
    )
    assert await GitHubAdapter(TOKEN).list_repos() == ["acme/storefront", "acme/infra"]


@respx.mock
async def test_github_commit_diff():
    sha = "bb083918c9be1579a96112ac2a5779ee95256c89"
    respx.get(f"https://api.github.com/repos/acme/storefront/commits/{sha}").respond(
        json=load_fixture("github_commit_detail.json")
    )
    diff = await GitHubAdapter(TOKEN).get_commit_diff("acme/storefront", sha)
    assert (diff.repo, diff.sha, diff.author) == ("acme/storefront", sha, "Priya Nair")
    assert [(f.filename.rsplit("/", 1)[-1], f.status) for f in diff.files] == [
        ("env.ts", "modified"),
        ("verify.ts", "added"),
        ("stripe.png", "modified"),  # GitHub's "changed" has no equivalent in the contract
        ("legacy.ts", "removed"),
    ]
    assert diff.files[2].patch is None
    assert "STRIPE_WEBHOOK_SECRET" in diff.files[0].patch


@respx.mock
async def test_github_errors_are_translated():
    respx.get("https://api.github.com/user").respond(401, json={"message": "Bad credentials"})
    with pytest.raises(ProviderError, match="rejected the token"):
        await GitHubAdapter(TOKEN).validate()
    respx.get("https://api.github.com/user").mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(ProviderError, match="ConnectTimeout"):
        await GitHubAdapter(TOKEN).validate()


@respx.mock
@pytest.mark.parametrize("status", [403, 404, 409])
async def test_github_unreadable_repo_is_a_skippable_error(status):
    respx.get("https://api.github.com/repos/acme/private/commits").respond(status, json={})
    with pytest.raises(ResourceUnavailableError, match="not readable"):
        await GitHubAdapter(TOKEN).list_commits("acme/private", SINCE)


def test_github_push_webhook_signature_and_normalization():
    body = raw("github_push.json")
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "72d3162e-cc78-11e3-81ab-4c9367dc0958",
    }
    adapter = GitHubAdapter(TOKEN, webhook_secret=SECRET)
    [event] = adapter.parse_webhook(headers, body)
    assert (event.event_type, event.dedup_key) == (
        "push",
        "github:72d3162e-cc78-11e3-81ab-4c9367dc0958",
    )

    [commit] = GitHubAdapter.normalize("push", event.payload).commits
    assert commit.repo == "acme/storefront"
    assert commit.author == "Priya Nair"
    assert commit.committed_at == datetime(2026, 11, 18, 5, 51, 30, tzinfo=UTC)  # +05:30 → UTC
    assert GitHubAdapter.normalize("ping", event.payload).commits == []

    for bad in ("", "sha256=" + "0" * 64, signature.removeprefix("sha256=")):
        with pytest.raises(WebhookVerificationError):
            adapter.parse_webhook({**headers, "X-Hub-Signature-256": bad}, body)


@respx.mock
async def test_github_follows_the_redirect_of_a_renamed_repo():
    respx.get("https://api.github.com/repos/acme/old/commits").respond(
        301, headers={"location": "https://api.github.com/repositories/42/commits"}, json={}
    )
    respx.get("https://api.github.com/repositories/42/commits").respond(json=[])
    assert await GitHubAdapter(TOKEN).list_commits("acme/old", SINCE) == []
