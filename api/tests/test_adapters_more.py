"""Contract tests for the Render, Fly.io, Netlify, Cloudflare and AWS adapters (no live calls)."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.integrations.aws import AwsAdapter, sign
from app.integrations.base import (
    DeploymentRef,
    ProviderError,
    ServiceRef,
    WebhookVerificationError,
    repo_slug,
)
from app.integrations.cloudflare import CloudflareAdapter
from app.integrations.fly import GRAPHQL as FLY_GRAPHQL
from app.integrations.fly import FlyAdapter
from app.integrations.netlify import NetlifyAdapter
from app.integrations.render import RenderAdapter

SINCE = datetime(2026, 11, 1, tzinfo=UTC)
TOKEN = "tok_super_secret_value"
SECRET = "whsec_test"


def test_repo_slug_reads_github_urls_only():
    assert repo_slug("https://github.com/acme/storefront") == "acme/storefront"
    assert repo_slug("git@github.com:acme/storefront.git") == "acme/storefront"
    assert repo_slug("https://gitlab.com/acme/storefront") is None
    assert repo_slug(None) is None


@pytest.mark.parametrize(
    "adapter",
    [RenderAdapter(TOKEN), FlyAdapter(TOKEN), CloudflareAdapter(TOKEN), AwsAdapter(TOKEN)],
)
def test_poll_only_adapters_refuse_webhooks(adapter):
    with pytest.raises(WebhookVerificationError):
        adapter.parse_webhook({}, b"{}")
    assert adapter.normalize("anything", {}).deployments == []


# ───────────────────────────── render

RENDER = "https://api.render.com/v1"


@respx.mock
async def test_render_validate_and_bad_key():
    route = respx.get(f"{RENDER}/owners").respond(
        json=[{"owner": {"id": "tea-1", "name": "Acme", "email": "ops@acme.dev"}, "cursor": "c"}]
    )
    assert (await RenderAdapter(TOKEN).validate()).account_name == "Acme"
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"

    respx.get(f"{RENDER}/owners").respond(401, json={"message": "unauthorized"})
    with pytest.raises(ProviderError) as error:
        await RenderAdapter(TOKEN).validate()
    assert TOKEN not in str(error.value)


@respx.mock
async def test_render_services_and_deploys():
    respx.get(f"{RENDER}/services").respond(
        json=[
            {
                "cursor": "c1",
                "service": {
                    "id": "srv-api",
                    "name": "storefront-api",
                    "ownerId": "tea-1",
                    "type": "web_service",
                    "repo": "https://github.com/acme/storefront",
                    "serviceDetails": {"url": "https://storefront-api.onrender.com"},
                },
            },
            {
                "cursor": "c2",
                "service": {
                    "id": "srv-worker",
                    "name": "worker",
                    "ownerId": "tea-1",
                    "type": "background_worker",
                    "serviceDetails": {},
                },
            },
        ]
    )
    api, worker = await RenderAdapter(TOKEN).list_services()
    assert (api.external_id, api.repo, api.health_url) == (
        "srv-api",
        "acme/storefront",
        "https://storefront-api.onrender.com",
    )
    assert api.meta["owner_id"] == "tea-1"
    assert worker.health_url is None and worker.repo is None

    route = respx.get(f"{RENDER}/services/srv-api/deploys").respond(
        json=[
            {
                "cursor": "d1",
                "deploy": {
                    "id": "dep-2",
                    "status": "build_failed",
                    "commit": {"id": "7c3f2de", "message": "refactor: env\n\nbody"},
                    "createdAt": "2026-11-20T10:00:00Z",
                    "startedAt": "2026-11-20T10:00:05Z",
                    "finishedAt": "2026-11-20T10:01:00Z",
                },
            },
            {
                "cursor": "d2",
                "deploy": {
                    "id": "dep-1",
                    "status": "deactivated",
                    "createdAt": "2026-11-19T10:00:00Z",
                },
            },
            {
                "cursor": "d3",
                "deploy": {
                    "id": "dep-3",
                    "status": "build_in_progress",
                    "createdAt": "2026-11-20T11:00:00Z",
                },
            },
        ]
    )
    failed, old, running = await RenderAdapter(TOKEN).list_deployments(
        ServiceRef(external_id="srv-api", name="storefront-api"), SINCE
    )
    assert route.calls.last.request.url.params["createdAfter"] == "2026-11-01T00:00:00Z"
    assert (failed.status, failed.commit_sha, failed.commit_message) == (
        "failed",
        "7c3f2de",
        "refactor: env",
    )
    assert failed.finished_at == datetime(2026, 11, 20, 10, 1, tzinfo=UTC)
    assert old.status == "ready"
    assert running.status == "building" and running.finished_at is None


@respx.mock
async def test_render_logs_are_scoped_to_the_service_and_sorted():
    route = respx.get(f"{RENDER}/logs").respond(
        json={
            "hasMore": False,
            "logs": [
                {
                    "id": "2",
                    "timestamp": "2026-11-20T10:00:02Z",
                    "message": "KeyError: 'STRIPE_SECRET_KEY'",
                    "labels": [{"name": "level", "value": "error"}],
                },
                {
                    "id": "1",
                    "timestamp": "2026-11-20T10:00:01Z",
                    "message": "Starting",
                    "labels": [],
                },
            ],
        }
    )
    service = ServiceRef(external_id="srv-api", name="api", meta={"owner_id": "tea-1"})
    lines = await RenderAdapter(TOKEN).get_logs(DeploymentRef("dep-2", service), "runtime")
    params = route.calls.last.request.url.params
    assert (params["ownerId"], params["resource"], params["type"]) == ("tea-1", "srv-api", "app")
    assert [(line.level, line.message) for line in lines] == [
        ("info", "Starting"),
        ("error", "KeyError: 'STRIPE_SECRET_KEY'"),
    ]
    # Without the workspace id there is nothing to ask for.
    assert (
        await RenderAdapter(TOKEN).get_logs(DeploymentRef("d", ServiceRef("s", "s")), "build") == []
    )


# ───────────────────────────── fly


@respx.mock
async def test_fly_uses_the_right_auth_scheme():
    route = respx.post(FLY_GRAPHQL).respond(json={"data": {"viewer": {"email": "dana@acme.dev"}}})
    assert (await FlyAdapter("fo1_personal").validate()).account_name == "dana@acme.dev"
    assert route.calls.last.request.headers["authorization"] == "Bearer fo1_personal"
    await FlyAdapter("FlyV1 fm2_macaroon").validate()
    assert route.calls.last.request.headers["authorization"] == "FlyV1 fm2_macaroon"


@respx.mock
async def test_fly_graphql_errors_surface_without_the_token():
    respx.post(FLY_GRAPHQL).respond(json={"errors": [{"message": "Not authorized"}]})
    with pytest.raises(ProviderError) as error:
        await FlyAdapter(TOKEN).validate()
    assert "Not authorized" in str(error.value) and TOKEN not in str(error.value)


@respx.mock
async def test_fly_apps_releases_and_logs():
    respx.post(FLY_GRAPHQL).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": {
                        "apps": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "app1",
                                    "name": "storefront-api",
                                    "hostname": "storefront-api.fly.dev",
                                    "organization": {"slug": "acme"},
                                }
                            ],
                        }
                    }
                },
            ),
            httpx.Response(
                200,
                json={
                    "data": {
                        "app": {
                            "releases": {
                                "nodes": [
                                    {
                                        "id": "rel2",
                                        "version": 12,
                                        "status": "failed",
                                        "description": "Release v12",
                                        "user": {"email": "dana@acme.dev", "name": "Dana"},
                                        "createdAt": "2026-11-20T10:00:00Z",
                                    },
                                    {
                                        "id": "rel1",
                                        "version": 11,
                                        "status": "complete",
                                        "createdAt": "2026-10-01T10:00:00Z",
                                    },
                                ]
                            }
                        }
                    }
                },
            ),
        ]
    )
    adapter = FlyAdapter(TOKEN)
    (app,) = await adapter.list_services()
    assert (app.external_id, app.health_url) == ("storefront-api", "https://storefront-api.fly.dev")
    (release,) = await adapter.list_deployments(
        ServiceRef("storefront-api", "storefront-api"), SINCE
    )
    assert (release.external_id, release.status, release.commit_author) == (
        "rel2",
        "failed",
        "Dana",
    )

    respx.get("https://api.fly.io/api/v1/apps/storefront-api/logs").respond(
        json={
            "data": [
                {
                    "id": "l1",
                    "attributes": {
                        "timestamp": "2026-11-20T10:00:01.123Z",
                        "message": "boom",
                        "level": "error",
                    },
                }
            ],
            "meta": {"next_token": "t"},
        }
    )
    ref = DeploymentRef("rel2", ServiceRef("storefront-api", "storefront-api"))
    assert [(line.level, line.message) for line in await adapter.get_logs(ref, "runtime")] == [
        ("error", "boom")
    ]
    assert await adapter.get_logs(ref, "build") == []


# ───────────────────────────── netlify

NETLIFY = "https://api.netlify.com/api/v1"
DEPLOY = {
    "id": "dpl_1",
    "site_id": "site_1",
    "state": "error",
    "error_message": "Build script returned non-zero exit code: 2",
    "commit_ref": "7c3f2de",
    "title": "refactor: env",
    "branch": "main",
    "context": "production",
    "created_at": "2026-11-20T10:00:00.000Z",
    "updated_at": "2026-11-20T10:01:00.000Z",
    "deploy_ssl_url": "https://dpl--storefront.netlify.app",
}


def _jws(body: bytes, secret: str, **claims) -> str:
    def enc(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    payload = {"iss": "netlify", "sha256": hashlib.sha256(body).hexdigest()} | claims
    head = f"{enc(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())}.{enc(json.dumps(payload).encode())}"
    return f"{head}.{enc(hmac.new(secret.encode(), head.encode(), hashlib.sha256).digest())}"


@respx.mock
async def test_netlify_sites_and_deploys():
    respx.get(f"{NETLIFY}/user").respond(json={"full_name": "Dana", "email": "dana@acme.dev"})
    assert (await NetlifyAdapter(TOKEN).validate()).account_name == "Dana"
    respx.get(f"{NETLIFY}/sites").respond(
        json=[
            {
                "id": "site_1",
                "name": "storefront",
                "ssl_url": "https://storefront.netlify.app",
                "build_settings": {"provider": "github", "repo_path": "acme/storefront"},
                "published_deploy": DEPLOY | {"id": "dpl_0", "state": "ready"},
            }
        ]
    )
    (site,) = await NetlifyAdapter(TOKEN).list_services()
    assert (site.repo, site.health_url) == ("acme/storefront", "https://storefront.netlify.app")
    assert site.latest_deployment.status == "ready"

    respx.get(f"{NETLIFY}/sites/site_1/deploys").respond(
        json=[
            DEPLOY,
            DEPLOY | {"id": "dpl_2", "error_message": "Canceled build"},
            DEPLOY | {"id": "dpl_old", "created_at": "2026-10-01T00:00:00.000Z"},
        ]
    )
    failed, canceled = await NetlifyAdapter(TOKEN).list_deployments(
        ServiceRef("site_1", "storefront"), SINCE
    )
    assert (failed.status, failed.commit_sha, failed.environment) == (
        "failed",
        "7c3f2de",
        "production",
    )
    assert canceled.status == "canceled"


def test_netlify_webhook_is_verified_and_normalized():
    body = json.dumps(DEPLOY).encode()
    adapter = NetlifyAdapter(TOKEN, webhook_secret=SECRET)
    (event,) = adapter.parse_webhook({"X-Webhook-Signature": _jws(body, SECRET)}, body)
    assert (event.event_type, event.dedup_key) == ("deploy.error", "netlify:dpl_1:error")
    (deployment,) = adapter.normalize(event.event_type, event.payload).deployments
    assert (deployment.service_external_id, deployment.status) == ("site_1", "failed")


@pytest.mark.parametrize(
    "signature",
    [
        "",
        "not.a.jws",
        _jws(json.dumps(DEPLOY).encode(), "wrong-secret"),
        _jws(b"another body", SECRET),
        _jws(json.dumps(DEPLOY).encode(), SECRET, iss="someone-else"),
    ],
)
def test_netlify_webhook_rejects_bad_signatures(signature):
    with pytest.raises(WebhookVerificationError):
        NetlifyAdapter(TOKEN, webhook_secret=SECRET).parse_webhook(
            {"x-webhook-signature": signature}, json.dumps(DEPLOY).encode()
        )


# ───────────────────────────── cloudflare

CF = "https://api.cloudflare.com/client/v4/accounts/acc123/pages/projects"
CF_DEPLOY = {
    "id": "d-uuid-1",
    "environment": "production",
    "url": "https://abc123.storefront.pages.dev",
    "created_on": "2026-11-20T10:00:00.000000Z",
    "modified_on": "2026-11-20T10:01:00.000000Z",
    "latest_stage": {"name": "build", "status": "failure", "ended_on": "2026-11-20T10:00:50Z"},
    "deployment_trigger": {
        "type": "github:push",
        "metadata": {"branch": "main", "commit_hash": "7c3f2de", "commit_message": "refactor: env"},
    },
}


async def test_cloudflare_requires_an_account_id():
    with pytest.raises(ProviderError):
        await CloudflareAdapter(TOKEN).validate()


@respx.mock
async def test_cloudflare_projects_deployments_and_logs():
    adapter = CloudflareAdapter(TOKEN, {"account_id": "acc123"})
    respx.get(CF).respond(
        json={
            "success": True,
            "result": [
                {
                    "name": "storefront",
                    "subdomain": "storefront.pages.dev",
                    "domains": ["storefront.pages.dev", "shop.acme.dev"],
                    "source": {
                        "type": "github",
                        "config": {"owner": "acme", "repo_name": "storefront"},
                    },
                    "canonical_deployment": CF_DEPLOY
                    | {"id": "d-uuid-0", "latest_stage": {"name": "deploy", "status": "success"}},
                }
            ],
        }
    )
    (project,) = await adapter.list_services()
    assert (project.external_id, project.repo, project.health_url) == (
        "storefront",
        "acme/storefront",
        "https://shop.acme.dev",
    )
    assert project.latest_deployment.status == "ready"

    respx.get(f"{CF}/storefront/deployments").respond(
        json={
            "success": True,
            "result": [
                CF_DEPLOY,
                CF_DEPLOY
                | {"id": "d-uuid-2", "latest_stage": {"name": "clone_repo", "status": "active"}},
            ],
        }
    )
    failed, building = await adapter.list_deployments(ServiceRef("storefront", "storefront"), SINCE)
    assert (failed.status, failed.commit_sha, failed.branch) == ("failed", "7c3f2de", "main")
    assert building.status == "building" and building.finished_at is None

    respx.get(f"{CF}/storefront/deployments/d-uuid-1/history/logs").respond(
        json={
            "success": True,
            "result": {
                "total": 2,
                "data": [
                    {"ts": "2026-11-20T10:00:10Z", "line": "Installing dependencies"},
                    {"ts": "2026-11-20T10:00:40Z", "line": "Error: build failed"},
                ],
            },
        }
    )
    ref = DeploymentRef("d-uuid-1", ServiceRef("storefront", "storefront"))
    assert [line.level for line in await adapter.get_logs(ref, "build")] == ["info", "error"]


@respx.mock
async def test_cloudflare_unsuccessful_envelope_is_an_error():
    respx.get(CF).respond(json={"success": False, "errors": [{"code": 10000}], "result": None})
    with pytest.raises(ProviderError):
        await CloudflareAdapter(TOKEN, {"account_id": "acc123"}).validate()


# ───────────────────────────── aws

AWS_CONFIG = {"access_key_id": "AKIDEXAMPLE", "region": "eu-west-1"}


def test_sigv4_matches_the_aws_reference_signature():
    headers = sign(
        method="GET",
        host="iam.amazonaws.com",
        path="/",
        query={"Action": "ListUsers", "Version": "2010-05-08"},
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
        body=b"",
        service="iam",
        region="us-east-1",
        access_key_id="AKIDEXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        now=datetime(2015, 8, 30, 12, 36, tzinfo=UTC),
    )
    assert headers["Authorization"].endswith(
        "Signature=5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7"
    )


@respx.mock
async def test_aws_validate_signs_the_call_and_never_sends_the_secret():
    route = respx.post("https://sts.eu-west-1.amazonaws.com/").respond(
        text="<GetCallerIdentityResponse><GetCallerIdentityResult>"
        "<Account>123456789012</Account></GetCallerIdentityResult></GetCallerIdentityResponse>"
    )
    account = await AwsAdapter(TOKEN, AWS_CONFIG).validate()
    assert account.account_name == "123456789012 · eu-west-1"
    request = route.calls.last.request
    assert "Credential=AKIDEXAMPLE/" in request.headers["authorization"]
    assert "/eu-west-1/sts/aws4_request" in request.headers["authorization"]
    assert TOKEN not in str(request.headers) and TOKEN.encode() not in request.content

    respx.post("https://sts.eu-west-1.amazonaws.com/").respond(403, text="<ErrorResponse/>")
    with pytest.raises(ProviderError) as error:
        await AwsAdapter(TOKEN, AWS_CONFIG).validate()
    assert TOKEN not in str(error.value)
    with pytest.raises(ProviderError):
        await AwsAdapter(TOKEN).validate()


@respx.mock
async def test_aws_lists_amplify_branches_and_ecs_services():
    amplify = "https://amplify.eu-west-1.amazonaws.com"
    respx.get(f"{amplify}/apps").respond(
        json={
            "apps": [
                {
                    "appId": "d1abc",
                    "name": "storefront",
                    "repository": "https://github.com/acme/storefront",
                    "defaultDomain": "d1abc.amplifyapp.com",
                }
            ]
        }
    )
    respx.get(f"{amplify}/apps/d1abc/branches").respond(
        json={
            "branches": [
                {"branchName": "main", "displayName": "main", "stage": "PRODUCTION"},
                {"branchName": "feature/x", "displayName": "feature-x", "stage": "DEVELOPMENT"},
            ]
        }
    )

    def ecs(request: httpx.Request) -> httpx.Response:
        action = request.headers["x-amz-target"].split(".")[-1]
        if action == "ListClusters":
            return httpx.Response(
                200, json={"clusterArns": ["arn:aws:ecs:eu-west-1:1:cluster/prod"]}
            )
        assert json.loads(request.content)["cluster"] == "prod"
        return httpx.Response(
            200, json={"serviceArns": ["arn:aws:ecs:eu-west-1:1:service/prod/api"]}
        )

    respx.post("https://ecs.eu-west-1.amazonaws.com/").mock(side_effect=ecs)
    main, feature, service = await AwsAdapter(TOKEN, AWS_CONFIG).list_services()
    assert (main.external_id, main.name, main.repo, main.health_url) == (
        "amplify:d1abc:main",
        "storefront",
        "acme/storefront",
        "https://main.d1abc.amplifyapp.com",
    )
    assert (feature.external_id, feature.name) == (
        "amplify:d1abc:feature/x",
        "storefront (feature/x)",
    )
    assert (service.external_id, service.name) == ("ecs:prod:api", "api")


@respx.mock
async def test_aws_one_unreadable_product_does_not_hide_the_other():
    respx.get("https://amplify.eu-west-1.amazonaws.com/apps").respond(403, json={})
    respx.post("https://ecs.eu-west-1.amazonaws.com/").respond(json={"clusterArns": []})
    assert await AwsAdapter(TOKEN, AWS_CONFIG).list_services() == []
    respx.post("https://ecs.eu-west-1.amazonaws.com/").respond(403, json={})
    with pytest.raises(ProviderError):
        await AwsAdapter(TOKEN, AWS_CONFIG).list_services()


@respx.mock
async def test_aws_amplify_jobs_and_build_logs():
    base = "https://amplify.eu-west-1.amazonaws.com/apps/d1abc/branches/main/jobs"
    respx.get(base).respond(
        json={
            "jobSummaries": [
                {
                    "jobId": "7",
                    "status": "FAILED",
                    "commitId": "7c3f2de",
                    "commitMessage": "refactor: env",
                    "startTime": 1795082400.0,
                    "endTime": 1795082460.5,
                },
                {"jobId": "8", "status": "RUNNING", "commitId": "HEAD", "startTime": 1795086000},
            ]
        }
    )
    adapter = AwsAdapter(TOKEN, AWS_CONFIG)
    service = ServiceRef("amplify:d1abc:main", "storefront")
    failed, running = await adapter.list_deployments(service, SINCE)
    assert (failed.external_id, failed.status, failed.commit_sha) == (
        "amplify:d1abc:main:7",
        "failed",
        "7c3f2de",
    )
    assert failed.finished_at is not None
    assert (running.status, running.commit_sha, running.finished_at) == ("building", None, None)

    respx.get(f"{base}/7").respond(
        json={
            "job": {
                "steps": [
                    {
                        "stepName": "BUILD",
                        "status": "FAILED",
                        "startTime": 1795082400,
                        "logUrl": "https://logs.example-bucket.test/build.txt?X-Amz-Signature=abc",
                    },
                    {"stepName": "DEPLOY", "status": "CANCELLED"},
                ]
            }
        }
    )
    log = respx.get("https://logs.example-bucket.test/build.txt").respond(
        text="2026-11-20T10:00:10.000Z [INFO]: npm ci\n2026-11-20T10:00:40.000Z [ERROR]: !!! Build failed\n"
    )
    lines = await adapter.get_logs(DeploymentRef("amplify:d1abc:main:7", service), "build")
    assert [line.level for line in lines] == ["info", "error"]
    assert lines[0].ts == datetime(2026, 11, 20, 10, 0, 10, tzinfo=UTC)
    # The pre-signed log link is fetched as is, without our credentials.
    assert "authorization" not in log.calls.last.request.headers


@respx.mock
async def test_aws_ecs_rollouts():
    respx.post("https://ecs.eu-west-1.amazonaws.com/").respond(
        json={
            "services": [
                {
                    "deployments": [
                        {
                            "id": "ecs-svc/2",
                            "status": "PRIMARY",
                            "rolloutState": "FAILED",
                            "rolloutStateReason": "ECS deployment circuit breaker: tasks failed to start.",
                            "createdAt": 1795082400.611,
                            "updatedAt": 1795082700.0,
                        },
                        {
                            "id": "ecs-svc/1",
                            "status": "ACTIVE",
                            "rolloutState": "COMPLETED",
                            "taskDefinition": "arn:aws:ecs:eu-west-1:1:task-definition/api:41",
                            "createdAt": 1795000000.0,
                        },
                    ]
                }
            ]
        }
    )
    adapter = AwsAdapter(TOKEN, AWS_CONFIG)
    failed, done = await adapter.list_deployments(ServiceRef("ecs:prod:api", "api"), SINCE)
    assert (failed.status, done.status, done.commit_message) == ("failed", "ready", "api:41")
    assert "circuit breaker" in failed.commit_message
    assert (
        await adapter.get_logs(
            DeploymentRef("ecs-svc/2", ServiceRef("ecs:prod:api", "api")), "build"
        )
        == []
    )
