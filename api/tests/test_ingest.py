"""Webhook intake end to end: verify â†’ raw event â†’ job â†’ deployment â†’ incident."""

import hashlib
import hmac
import json
from datetime import timedelta

import httpx
import respx
from sqlalchemy import func, select

from app.core.db import session_scope
from app.core.queue import get_queue
from app.models import Commit, Deployment, Incident, Integration, RawEvent, Service
from tests.conftest import FIXTURES, SECRET_TOKEN, drain_jobs, load_fixture, make_service

WEBHOOK_SECRET = "test-webhook-secret"


def vercel_delivery() -> tuple[bytes, dict[str, str]]:
    body = (FIXTURES / "vercel_webhook_deployment_error.json").read_bytes()
    signature = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha1).hexdigest()
    return body, {"x-vercel-signature": signature, "content-type": "application/json"}


async def count(model) -> int:
    async with session_scope() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_same_webhook_twice_makes_one_event_one_deployment_one_incident(anon_client):
    async with session_scope() as session:
        await make_service(session)
    body, headers = vercel_delivery()

    first = await anon_client.post("/api/webhooks/vercel", content=body, headers=headers)
    second = await anon_client.post("/api/webhooks/vercel", content=body, headers=headers)
    third = await anon_client.post("/api/webhooks/vercel", content=body, headers=headers)
    assert (first.status_code, first.json()) == (202, {"accepted": 1, "duplicates": 0})
    assert (second.status_code, second.json()) == (202, {"accepted": 0, "duplicates": 1})
    assert third.json() == {"accepted": 0, "duplicates": 1}
    await drain_jobs()

    assert await count(Deployment) == 1
    assert await count(Incident) == 1
    async with session_scope() as session:
        events = (await session.scalars(select(RawEvent).order_by(RawEvent.received_at))).all()
        assert [event.duplicate for event in events] == [False, True, True]
        assert {event.dedup_key for event in events} == {"vercel:evt_3kd9Zp0aQ1"}
        assert all(event.processed_at is not None for event in events)
        deployment = await session.scalar(select(Deployment))
        assert (deployment.status, deployment.external_id) == ("failed", "dpl_8mErrorBuild")

    await anon_client.post(
        "/api/auth/login", json={"email": "admin@opscend.local", "password": "opscend-dev"}
    )
    inspector = (await anon_client.get("/api/events")).json()
    assert [event["duplicate"] for event in inspector] == [True, True, False]  # newest first
    assert inspector[0]["source"] == "webhook"
    assert inspector[0]["payload"]["type"] == "deployment.error"


async def test_webhook_handler_does_not_normalize_inline(anon_client, monkeypatch):
    """The handler only stores and enqueues; the deployment appears once the job has run."""
    # Hold the job instead of letting the inline queue start it: otherwise it can finish
    # before the assertions below and the test fails on timing alone.
    queue = get_queue()
    held = []

    async def hold(name, *args):  # noqa: ANN001, ANN002
        held.append((name, *args))

    monkeypatch.setattr(queue, "enqueue", hold)
    async with session_scope() as session:
        await make_service(session)
    body, headers = vercel_delivery()
    response = await anon_client.post("/api/webhooks/vercel", content=body, headers=headers)
    assert response.status_code == 202
    assert await count(RawEvent) == 1
    assert await count(Deployment) == 0
    [(name, *args)] = held
    assert name == "process_event"
    await type(queue).enqueue(queue, name, *args)
    await drain_jobs()
    assert await count(Deployment) == 1


async def test_bad_signature_is_rejected_and_stores_nothing(anon_client):
    async with session_scope() as session:
        await make_service(session)
    body, headers = vercel_delivery()
    for bad in ({**headers, "x-vercel-signature": "0" * 40}, {"content-type": "application/json"}):
        response = await anon_client.post("/api/webhooks/vercel", content=body, headers=bad)
        assert response.status_code == 401
    tampered = body.replace(b"dpl_8mErrorBuild", b"dpl_somethingElse")
    assert (
        await anon_client.post("/api/webhooks/vercel", content=tampered, headers=headers)
    ).status_code == 401
    assert await count(RawEvent) == 0


async def test_webhook_for_an_unconnected_provider_is_404(anon_client):
    body, headers = vercel_delivery()
    response = await anon_client.post("/api/webhooks/vercel", content=body, headers=headers)
    assert response.status_code == 404
    assert (await anon_client.post("/api/webhooks/nope", content=b"{}")).status_code == 404


async def test_event_for_an_unknown_service_is_processed_without_effect(anon_client):
    async with session_scope() as session:
        await make_service(session, external_id="prj_other")
    body, headers = vercel_delivery()
    await anon_client.post("/api/webhooks/vercel", content=body, headers=headers)
    await drain_jobs()
    assert await count(Deployment) == 0
    async with session_scope() as session:
        event = await session.scalar(select(RawEvent))
        assert event.processed_at is not None and event.error is None


async def test_github_push_webhook_feeds_the_commit_table(anon_client):
    async with session_scope() as session:
        await make_service(session, provider="github", name="unused", external_id="none")
    body = (FIXTURES / "github_push.json").read_bytes()
    headers = {
        "X-Hub-Signature-256": "sha256="
        + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest(),
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "72d3162e-cc78-11e3-81ab-4c9367dc0958",
    }
    for _ in range(2):  # GitHub redelivers with the same delivery id
        assert (
            await anon_client.post("/api/webhooks/github", content=body, headers=headers)
        ).status_code == 202
    await drain_jobs()
    assert await count(Commit) == 1
    async with session_scope() as session:
        commit = await session.scalar(select(Commit))
        assert (commit.repo, commit.author) == ("acme/storefront", "Priya Nair")


async def test_railway_webhook_then_poll_converge_on_one_deployment(anon_client):
    """A webhook and the poller describing the same deploy must not create two rows."""
    from app.ingest.normalizer import process_raw_event
    from app.ingest.store import record_event
    from app.integrations.base import RawEventIn
    from app.integrations.railway import RailwayAdapter

    async with session_scope() as session:
        await make_service(
            session,
            provider="railway",
            name="storefront-api",
            external_id="5d0c7c1e-8f43-4b1e-9a57-2f6d1c0e8a11",
        )
    body = (FIXTURES / "railway_webhook_failed.json").read_bytes()
    response = await anon_client.post(
        "/api/webhooks/railway", content=body, headers={"X-Webhook-Secret": WEBHOOK_SECRET}
    )
    assert response.status_code == 202
    await drain_jobs()

    polled = RailwayAdapter.normalize("Deployment.failed", json.loads(body))
    polled.deployments[0].started_at -= timedelta(seconds=160)
    async with session_scope() as session:
        for _ in range(2):
            row = await record_event(
                session,
                RawEventIn(
                    provider="railway",
                    event_type="poll.deployment",
                    dedup_key="railway:poll:dep-failed-0003:failed",
                    payload=polled.model_dump(mode="json"),
                ),
                source="poll",
                keep_duplicate=False,
            )
            if row is not None:
                await process_raw_event(row.id)

    assert await count(Deployment) == 1
    assert await count(Incident) == 1
    assert await count(RawEvent) == 2  # the webhook and one poll result; the repeat was dropped
    async with session_scope() as session:
        deployment = await session.scalar(select(Deployment))
        # The poll knew the real start time; the webhook only knew when it failed.
        assert (deployment.finished_at - deployment.started_at).total_seconds() == 160


@respx.mock
async def test_connecting_vercel_validates_encrypts_and_syncs(client):
    respx.get("https://api.vercel.com/v2/user").respond(json={"user": {"username": "acme-dana"}})
    respx.get("https://api.vercel.com/v10/projects").respond(
        json=load_fixture("vercel_projects.json")
    )
    deployments = respx.get("https://api.vercel.com/v6/deployments")
    deployments.mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=load_fixture("vercel_deployments.json")
            if request.url.params["projectId"] == "prj_QmT4wq1storefront"
            else {"deployments": []},
        )
    )

    response = await client.post(
        "/api/integrations",
        json={
            "provider": "vercel",
            "token": SECRET_TOKEN,
            "config": {"team_id": "team_9xAcme", "webhook_secret": "whsec_from_vercel"},
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["status"] == "connected"
    assert created["account_name"] == "acme-dana"
    assert created["token_hint"] == SECRET_TOKEN[-4:]
    assert created["last_synced_at"] is not None
    assert SECRET_TOKEN not in response.text and "whsec_from_vercel" not in response.text

    async with session_scope() as session:
        integration = await session.scalar(select(Integration))
        assert SECRET_TOKEN not in integration.token_encrypted
        assert "webhook_secret" not in integration.config
        assert "whsec_from_vercel" not in (integration.webhook_secret_encrypted or "")
        assert {s.name for s in (await session.scalars(select(Service))).all()} == {
            "storefront-web",
            "docs",
        }
    # Three from the deployment list, plus the project's own production deployment,
    # which is older than the sync window and would otherwise never be seen.
    assert await count(Deployment) == 4
    # The newest deploy is still building, so the earlier failure is superseded: no incident.
    assert await count(Incident) == 0

    # A second sync sees the same states: nothing new is stored or created.
    events_before = await count(RawEvent)
    synced = await client.post(f"/api/integrations/{created['id']}/sync")
    assert synced.status_code == 200
    assert await count(RawEvent) == events_before
    assert await count(Deployment) == 4

    # Deleting the integration removes what hung off it.
    assert (await client.delete(f"/api/integrations/{created['id']}")).status_code == 200
    assert await count(Service) == 0 and await count(Deployment) == 0


@respx.mock
async def test_connecting_with_a_bad_token_fails_cleanly(client):
    respx.get("https://api.vercel.com/v2/user").respond(403, json={"error": {"code": "forbidden"}})
    response = await client.post(
        "/api/integrations", json={"provider": "vercel", "token": SECRET_TOKEN, "config": {}}
    )
    assert response.status_code == 400
    assert SECRET_TOKEN not in response.text
    assert await count(Integration) == 0

    unknown = await client.post(
        "/api/integrations", json={"provider": "heroku", "token": "x", "config": {}}
    )
    assert unknown.status_code == 400

    # A required field left empty is refused before any provider call is made.
    incomplete = await client.post(
        "/api/integrations", json={"provider": "cloudflare", "token": "x", "config": {}}
    )
    assert incomplete.status_code == 422


@respx.mock
async def test_provider_outage_marks_the_integration_as_error(client):
    respx.get("https://api.vercel.com/v2/user").respond(json={"user": {"username": "acme-dana"}})
    respx.get("https://api.vercel.com/v10/projects").respond(500)
    response = await client.post(
        "/api/integrations", json={"provider": "vercel", "token": SECRET_TOKEN, "config": {}}
    )
    body = response.json()
    assert (body["status"], body["status_detail"]) == (
        "error",
        "Vercel API returned HTTP 500 for /v10/projects",
    )


async def test_reconciler_replays_events_whose_job_was_lost(anon_client):
    from app.ingest import poller
    from app.ingest.webhooks import receive_webhook

    async with session_scope() as session:
        await make_service(session)
        body, headers = vercel_delivery()
        [event] = await receive_webhook(session, "vercel", headers, body)  # stored, never enqueued
        event.received_at -= timedelta(minutes=5)
        await session.commit()
    assert await count(Deployment) == 0
    await poller.reconcile()
    assert await count(Deployment) == 1 and await count(Incident) == 1


async def test_webhook_for_a_service_with_monitoring_off_stores_nothing(anon_client):
    async with session_scope() as session:
        service = await make_service(session)
        service.monitored = False
        await session.commit()
    body, headers = vercel_delivery()

    response = await anon_client.post("/api/webhooks/vercel", content=body, headers=headers)
    assert response.status_code == 202
    await drain_jobs()

    assert await count(Deployment) == 0
    assert await count(Incident) == 0


@respx.mock
async def test_sync_skips_services_with_monitoring_off_and_backfills_new_ones(client):
    respx.get("https://api.vercel.com/v2/user").respond(json={"user": {"username": "acme-dana"}})
    respx.get("https://api.vercel.com/v10/projects").respond(
        json=load_fixture("vercel_projects.json")
    )
    polled: list[str] = []

    def deployments(request: httpx.Request) -> httpx.Response:
        polled.append(request.url.params["projectId"])
        return httpx.Response(200, json={"deployments": []})

    respx.get("https://api.vercel.com/v6/deployments").mock(side_effect=deployments)
    created = (
        await client.post("/api/integrations", json={"provider": "vercel", "token": SECRET_TOKEN})
    ).json()
    url = f"/api/integrations/{created['id']}/services"
    services = {s["name"]: s for s in (await client.get(url)).json()}
    assert set(services) == {"storefront-web", "docs"}
    assert all(s["monitored"] for s in services.values())
    deploys_before = await count(Deployment)

    # Keep only "docs".
    chosen = (await client.put(url, json={"service_ids": [services["docs"]["id"]]})).json()
    assert {s["name"]: s["monitored"] for s in chosen} == {"docs": True, "storefront-web": False}
    await drain_jobs()
    polled.clear()
    assert (await client.post(f"/api/integrations/{created['id']}/sync")).status_code == 200
    assert polled == [services["docs"]["external_id"]]
    # The service that is off is still listed for the integration, and gained nothing.
    assert {s["name"] for s in (await client.get(url)).json()} == {"storefront-web", "docs"}
    assert await count(Deployment) == deploys_before

    # Turning it back on syncs it in the background.
    polled.clear()
    both = [s["id"] for s in services.values()]
    assert all(s["monitored"] for s in (await client.put(url, json={"service_ids": both})).json())
    await drain_jobs()
    assert services["storefront-web"]["external_id"] in polled

    assert (await client.put(url, json={"service_ids": ["nope"]})).status_code == 422
