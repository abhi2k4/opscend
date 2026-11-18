"""`POST /api/demo/break`: simulate a bad push, through the real ingest pipeline.

Nothing here writes deployments or incidents directly. It builds provider-shaped
webhook bodies (a GitHub push, then Vercel / Railway deployment events), signs them
with the demo webhook secret and hands them to the same `receive_webhook` and
normalizer the live webhook route uses. The incident opens by the ordinary rules.
"""

import hashlib
import hmac
import json
import random
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.time import utcnow
from app.incidents import rules
from app.ingest.normalizer import process_raw_event
from app.ingest.webhooks import receive_webhook
from app.models import Deployment, Incident, Service
from app.services.logs import to_rows

from .scenarios import VERCEL_BUILD_OK, Scenario
from .seed import (
    REPO,
    SERVICE_BY_NAME,
    ServiceSpec,
    new_external_id,
    render_logs,
    seed_scenario_artifacts,
)

HEALTHY_SIBLING_SECONDS = 72


class DemoUnavailable(Exception):
    """Demo data is missing (demo mode off, or the demo integrations were deleted)."""


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def github_push(sha: str, scenario: Scenario, at: datetime) -> tuple[dict[str, str], bytes]:
    username = scenario.author.lower().replace(" ", "-")
    commit = {
        "id": sha,
        "message": scenario.commit_message,
        "timestamp": _iso(at),
        "url": f"https://github.com/{REPO}/commit/{sha}",
        "author": {"name": scenario.author, "username": username},
        "modified": [item.filename for item in scenario.files if item.status == "modified"],
        "added": [item.filename for item in scenario.files if item.status == "added"],
        "removed": [],
    }
    body = _body(
        {
            "ref": "refs/heads/main",
            "after": sha,
            "repository": {"full_name": REPO, "default_branch": "main"},
            "pusher": {"name": username},
            "head_commit": commit,
            "commits": [commit],
        }
    )
    signature = hmac.new(_secret(), body, hashlib.sha256).hexdigest()
    return {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": str(uuid.uuid4()),
        "X-Hub-Signature-256": f"sha256={signature}",
    }, body


def vercel_event(
    event_type: str,
    service: ServiceSpec,
    deployment_id: str,
    sha: str,
    scenario: Scenario,
    at: datetime,
) -> tuple[dict[str, str], bytes]:
    body = _body(
        {
            "id": f"evt_{secrets.token_hex(12)}",
            "type": event_type,
            "createdAt": int(at.timestamp() * 1000),
            "payload": {
                "team": {"id": "team_acme"},
                "user": {"id": "usr_demo"},
                "deployment": {
                    "id": deployment_id,
                    "name": service.name,
                    "url": f"{service.name}-{deployment_id[4:13].lower()}-acme.vercel.app",
                    "meta": {
                        "githubCommitSha": sha,
                        "githubCommitMessage": scenario.commit_message,
                        "githubCommitAuthorName": scenario.author,
                        "githubCommitRef": "main",
                        "githubOrg": "acme",
                        "githubRepo": "storefront",
                    },
                },
                "links": {
                    "deployment": f"https://vercel.com/acme/{service.name}/{deployment_id}",
                    "project": f"https://vercel.com/acme/{service.name}",
                },
                "target": "production",
                "project": {"id": service.external_id},
                "plan": "pro",
                "regions": ["iad1"],
            },
        }
    )
    signature = hmac.new(_secret(), body, hashlib.sha1).hexdigest()
    return {"x-vercel-signature": signature}, body


def railway_event(
    event_type: str,
    status: str,
    service: ServiceSpec,
    deployment_id: str,
    sha: str,
    scenario: Scenario,
    at: datetime,
) -> tuple[dict[str, str], bytes]:
    body = _body(
        {
            "type": event_type,
            "details": {
                "id": deployment_id,
                "source": "GitHub",
                "status": status,
                "branch": "main",
                "commitHash": sha,
                "commitAuthor": scenario.author,
                "commitMessage": scenario.commit_message,
            },
            "resource": {
                "workspace": {"id": "0b1d5c9e-demo", "name": "acme"},
                "project": {"id": "c1f0a6de-2b7c-4d3e-9f18-6e5a4b3c2d10", "name": "storefront"},
                "environment": {"id": "7e2a-demo-env", "name": "production", "isEphemeral": False},
                "service": {"id": service.external_id, "name": service.name},
                "deployment": {"id": deployment_id},
            },
            "severity": "ERROR" if status == "FAILED" else "INFO",
            "timestamp": _iso(at),
        }
    )
    return {"X-Webhook-Secret": get_settings().demo_webhook_secret}, body


def _body(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


def _secret() -> bytes:
    return get_settings().demo_webhook_secret.encode()


def deploy_events(
    service: ServiceSpec,
    deployment_id: str,
    sha: str,
    scenario: Scenario,
    started: datetime,
    finished: datetime,
    *,
    failed: bool,
) -> list[tuple[dict[str, str], bytes]]:
    """The 'started' and 'finished' webhook pair a provider sends for one deployment."""
    if service.provider == "vercel":
        end = "deployment.error" if failed else "deployment.succeeded"
        return [
            vercel_event("deployment.created", service, deployment_id, sha, scenario, started),
            vercel_event(end, service, deployment_id, sha, scenario, finished),
        ]
    end_type, end_status = (
        ("Deployment.failed", "FAILED")
        if failed
        else (
            "Deployment.deployed",
            "SUCCESS",
        )
    )
    args = (service, deployment_id, sha, scenario)
    return [
        railway_event("Deployment.building", "BUILDING", *args, started),
        railway_event(end_type, end_status, *args, finished),
    ]


async def break_demo(session: AsyncSession, scenario: Scenario) -> tuple[str, str]:
    """Run a scenario. Returns (deployment_id, incident_id) of the failure it produced."""
    target = SERVICE_BY_NAME[scenario.service]
    service = await session.scalar(
        select(Service).where(
            Service.provider == target.provider, Service.external_id == target.external_id
        )
    )
    if service is None:
        raise DemoUnavailable("demo data is not loaded; POST /api/demo/reset first")

    # One incident can be open per service. So that every run of the demo shows a fresh
    # incident, the previous one on this service is resolved first, as an operator would.
    previous = await rules.open_incident_for(session, service.id)
    if previous is not None:
        rules.resolve(previous)
        await session.commit()

    rng = random.Random()
    now = utcnow()
    sha = secrets.token_hex(20)
    # Start after the service's newest deploy, or this failure would count as superseded.
    newest = await session.scalar(
        select(Deployment.started_at)
        .where(Deployment.service_id == service.id)
        .order_by(Deployment.started_at.desc())
        .limit(1)
    )
    started = now - timedelta(seconds=scenario.build_seconds)
    if newest is not None and newest >= started:
        started = min(newest + timedelta(seconds=1), now)
    deployment_ext = new_external_id(target.provider, rng)

    deliveries = [("github", github_push(sha, scenario, started - timedelta(seconds=25)))]
    sibling_ext: str | None = None
    web = SERVICE_BY_NAME["storefront-web"]
    if target.name == "storefront-api":
        # The same push also deploys the frontend, which stays healthy.
        sibling_ext = new_external_id(web.provider, rng)
        sibling_start = now - timedelta(
            seconds=max(scenario.build_seconds, HEALTHY_SIBLING_SECONDS + 8)
        )
        sibling_end = sibling_start + timedelta(seconds=HEALTHY_SIBLING_SECONDS)
        deliveries += [
            (web.provider, event)
            for event in deploy_events(
                web, sibling_ext, sha, scenario, sibling_start, sibling_end, failed=False
            )
        ]
    deliveries += [
        (target.provider, event)
        for event in deploy_events(target, deployment_ext, sha, scenario, started, now, failed=True)
    ]

    for provider, (headers, body) in deliveries:
        for event in await receive_webhook(session, provider, headers, body, source="demo"):
            await process_raw_event(event.id)

    session.expire_all()
    deployment = await _deployment(session, target.provider, deployment_ext)
    incident = await session.scalar(
        select(Incident).where(Incident.dedup_key == f"deploy:{deployment.id}")
    )
    if incident is None:
        raise DemoUnavailable("the ingest pipeline did not open an incident")
    await seed_scenario_artifacts(session, scenario, deployment, sha)
    if sibling_ext is not None:
        sibling = await _deployment(session, web.provider, sibling_ext)
        session.add_all(
            to_rows(sibling.id, "build", render_logs(VERCEL_BUILD_OK, sibling.started_at, sha, web))
        )
        await session.commit()
    return deployment.id, incident.id


async def _deployment(session: AsyncSession, provider: str, external_id: str) -> Deployment:
    deployment = await session.scalar(
        select(Deployment).where(
            Deployment.provider == provider, Deployment.external_id == external_id
        )
    )
    if deployment is None:
        raise DemoUnavailable("the ingest pipeline did not produce the demo deployment")
    return deployment
