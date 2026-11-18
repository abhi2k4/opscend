"""Railway adapter (GraphQL public API, https://docs.railway.com/reference/public-api).

Railway is polling-first. Its webhooks are not signed: Railway's docs recommend a
custom secret header instead, so `parse_webhook` checks `X-Webhook-Secret` (or an
`Authorization: Bearer` value) against the integration's webhook secret.
"""

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, ClassVar

import httpx

from app.core.time import parse_iso, utcnow
from app.integrations.base import (
    AccountInfo,
    DeploymentIn,
    DeploymentRef,
    HttpAdapter,
    LogLineIn,
    NormalizedBatch,
    ProviderError,
    RawEventIn,
    ServiceIn,
    ServiceRef,
    WebhookVerificationError,
    first_line,
    lower_headers,
)
from app.integrations.registry import register
from app.schemas import Capability, ConfigField, DeployStatus, LogKind, LogLevel, ProviderManifest

API = "https://backboard.railway.com/graphql/v2"

_STATUS: dict[str, DeployStatus] = {
    "QUEUED": "queued",
    "WAITING": "queued",
    "NEEDS_APPROVAL": "queued",
    "INITIALIZING": "building",
    "BUILDING": "building",
    "DEPLOYING": "building",
    "SUCCESS": "ready",
    "SLEEPING": "ready",
    "FAILED": "failed",
    "CRASHED": "failed",
    # Railway marks a deploy REMOVED once a newer one replaces it: it did go live.
    "REMOVED": "ready",
    "REMOVING": "ready",
    "SKIPPED": "canceled",
}
# States whose `updatedAt` is the moment the deploy finished.
_SETTLED = frozenset({"SUCCESS", "FAILED", "CRASHED", "SKIPPED"})

# Webhook event names are `Deployment.<state>`; map the state part when no status is given.
_EVENT_STATUS: dict[str, DeployStatus] = {
    "queued": "queued",
    "initializing": "building",
    "building": "building",
    "deploying": "building",
    "deployed": "ready",
    "success": "ready",
    "redeployed": "ready",
    "failed": "failed",
    "crashed": "failed",
    "removed": "canceled",
}

_SEVERITY: dict[str, LogLevel] = {
    "debug": "debug",
    "info": "info",
    "warn": "warn",
    "warning": "warn",
    "error": "error",
    "err": "error",
    "fatal": "error",
}

_ME = "query { me { name email } }"
_PROJECTS = """
query {
  projects {
    edges { node {
      id
      name
      services { edges { node { id name } } }
      environments { edges { node { id name } } }
    } }
  }
}
"""
_DEPLOYMENTS = """
query deployments($input: DeploymentListInput!, $first: Int) {
  deployments(input: $input, first: $first) {
    edges { node { id status createdAt updatedAt staticUrl environmentId meta } }
  }
}
"""
_BUILD_LOGS = """
query buildLogs($deploymentId: String!, $limit: Int) {
  buildLogs(deploymentId: $deploymentId, limit: $limit) { timestamp message severity }
}
"""
_DEPLOY_LOGS = """
query deploymentLogs($deploymentId: String!, $limit: Int) {
  deploymentLogs(deploymentId: $deploymentId, limit: $limit) { timestamp message severity }
}
"""


@register
class RailwayAdapter(HttpAdapter):
    provider: ClassVar[str] = "railway"
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {
            Capability.LIST_SERVICES,
            Capability.LIST_DEPLOYS,
            Capability.BUILD_LOGS,
            Capability.RUNTIME_LOGS,
            Capability.WEBHOOKS,
        }
    )
    manifest: ClassVar[ProviderManifest] = ProviderManifest(
        provider="railway",
        name="Railway",
        description="Services, deployments, build and runtime logs from Railway's GraphQL API.",
        availability="available",
        capabilities=sorted(capabilities),
        token_label="Account or workspace token",
        token_help_url="https://railway.com/account/tokens",
        config_fields=[
            ConfigField(
                key="webhook_secret",
                label="Webhook secret (send it as an X-Webhook-Secret custom header)",
                required=False,
                placeholder="any long random string",
            ),
        ],
        webhook_path="/api/webhooks/railway",
    )

    async def _query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = await self.client.post(
                API,
                json={"query": query, "variables": variables or {}},
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Railway request failed: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise ProviderError("Railway rejected the token")
        if response.status_code == 429:
            raise ProviderError("Railway rate limit reached; the next poll will retry")
        if response.status_code >= 400:
            raise ProviderError(f"Railway API returned HTTP {response.status_code}")
        body = response.json()
        if errors := body.get("errors"):
            message = errors[0].get("message", "unknown error")
            if "not authorized" in message.lower():
                raise ProviderError("Railway: this token is not authorized for that query")
            raise ProviderError(f"Railway GraphQL error: {message}")
        return body["data"]

    async def validate(self) -> AccountInfo:
        try:
            me = (await self._query(_ME))["me"]
            return AccountInfo(account_name=me.get("name") or me.get("email") or "railway")
        except ProviderError:
            pass
        # Workspace tokens cannot query `me`, but they can list their projects.
        try:
            projects = _nodes((await self._query(_PROJECTS))["projects"])
        except ProviderError as exc:
            raise ProviderError(
                "Railway rejected the token. Create an account or workspace token at "
                "railway.com/account/tokens; project tokens are not supported."
            ) from exc
        label = projects[0]["name"] if len(projects) == 1 else f"{len(projects)} projects"
        return AccountInfo(account_name=f"workspace · {label}")

    async def list_services(self) -> list[ServiceIn]:
        data = await self._query(_PROJECTS)
        services: list[ServiceIn] = []
        for project in _nodes(data["projects"]):
            environments = {env["id"]: env["name"] for env in _nodes(project["environments"])}
            for service in _nodes(project["services"]):
                services.append(
                    ServiceIn(
                        external_id=service["id"],
                        name=service["name"],
                        meta={
                            "project_id": project["id"],
                            "project_name": project["name"],
                            "environments": environments,
                        },
                    )
                )
        return services

    async def list_deployments(self, service: ServiceRef, since: datetime) -> list[DeploymentIn]:
        data = await self._query(
            _DEPLOYMENTS,
            {
                "input": {
                    "projectId": service.meta.get("project_id"),
                    "serviceId": service.external_id,
                },
                "first": 50,
            },
        )
        environments: dict[str, str] = service.meta.get("environments") or {}
        deployments = [
            _deployment_from_api(node, service.external_id, environments)
            for node in _nodes(data["deployments"])
        ]
        return [d for d in deployments if d.started_at >= since]

    async def get_logs(
        self, deployment: DeploymentRef, kind: LogKind, limit: int = 500
    ) -> list[LogLineIn]:
        query, key = (
            (_BUILD_LOGS, "buildLogs") if kind == "build" else (_DEPLOY_LOGS, "deploymentLogs")
        )
        data = await self._query(query, {"deploymentId": deployment.external_id, "limit": limit})
        lines = []
        for entry in data.get(key) or []:
            ts = parse_iso(entry.get("timestamp"))
            if ts is None or not entry.get("message"):
                continue
            level = _SEVERITY.get((entry.get("severity") or "info").lower(), "info")
            lines.append(LogLineIn(ts=ts, level=level, message=entry["message"]))
        return lines

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> list[RawEventIn]:
        lowered = lower_headers(headers)
        presented = lowered.get("x-webhook-secret") or lowered.get(
            "authorization", ""
        ).removeprefix("Bearer ")
        if not hmac.compare_digest(presented.encode(), self._require_secret().encode()):
            raise WebhookVerificationError("webhook secret header does not match")
        event = json.loads(body)
        event_type = str(event.get("type", "unknown"))
        deployment_id = _webhook_deployment_id(event)
        if deployment_id:
            # No delivery id is sent, so identity is the deployment plus the state it reached.
            dedup = f"railway:{deployment_id}:{event_type}:{_webhook_status(event_type, event)}"
        else:
            dedup = f"railway:body:{hashlib.sha256(body).hexdigest()[:32]}"
        return [
            RawEventIn(
                provider=self.provider, event_type=event_type, dedup_key=dedup, payload=event
            )
        ]

    @staticmethod
    def normalize(event_type: str, payload: dict[str, Any]) -> NormalizedBatch:
        deployment_id = _webhook_deployment_id(payload)
        resource = payload.get("resource") or {}
        service_id = (resource.get("service") or payload.get("service") or {}).get("id")
        status = _webhook_status(event_type, payload)
        if not deployment_id or not service_id or status is None:
            return NormalizedBatch()
        details = payload.get("details") or (payload.get("deployment") or {}).get("meta") or {}
        environment = (resource.get("environment") or payload.get("environment") or {}).get("name")
        at = parse_iso(payload.get("timestamp")) or utcnow()
        return NormalizedBatch(
            deployments=[
                DeploymentIn(
                    service_external_id=service_id,
                    external_id=deployment_id,
                    status=status,
                    commit_sha=details.get("commitHash"),
                    commit_message=first_line(details.get("commitMessage")),
                    commit_author=details.get("commitAuthor"),
                    branch=details.get("branch"),
                    environment=environment,
                    started_at=at,
                    finished_at=at if status in ("ready", "failed", "canceled") else None,
                )
            ]
        )


def _nodes(connection: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [edge["node"] for edge in (connection or {}).get("edges", [])]


def _deployment_from_api(
    node: dict[str, Any], service_id: str, environments: dict[str, str]
) -> DeploymentIn:
    status = _STATUS.get(node.get("status", ""), "queued")
    meta = node.get("meta") or {}
    static_url = node.get("staticUrl")
    return DeploymentIn(
        service_external_id=service_id,
        external_id=node["id"],
        status=status,
        commit_sha=meta.get("commitHash"),
        commit_message=first_line(meta.get("commitMessage")),
        commit_author=meta.get("commitAuthor"),
        branch=meta.get("branch"),
        environment=environments.get(node.get("environmentId", "")),
        started_at=parse_iso(node.get("createdAt")) or utcnow(),
        finished_at=parse_iso(node.get("updatedAt")) if node.get("status") in _SETTLED else None,
        url=f"https://{static_url}" if static_url else None,
    )


def _webhook_deployment_id(payload: dict[str, Any]) -> str | None:
    resource = payload.get("resource") or {}
    return (
        (resource.get("deployment") or {}).get("id")
        or (payload.get("details") or {}).get("id")
        or (payload.get("deployment") or {}).get("id")
    )


def _webhook_status(event_type: str, payload: dict[str, Any]) -> DeployStatus | None:
    """Prefer the event name (`Deployment.failed`); fall back to a status field."""
    scope, _, state = event_type.partition(".")
    if scope.lower() == "deployment" and state.lower() in _EVENT_STATUS:
        return _EVENT_STATUS[state.lower()]
    raw = (payload.get("details") or {}).get("status") or payload.get("status")
    if scope.upper() in ("DEPLOYMENT", "DEPLOY") and raw:
        return _STATUS.get(str(raw).upper())
    return None
