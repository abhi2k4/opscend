"""Vercel adapter (REST API, https://vercel.com/docs/rest-api)."""

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, ClassVar

import httpx

from app.core.time import from_epoch_ms, utcnow
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

API = "https://api.vercel.com"

_STATE: dict[str, DeployStatus] = {
    "QUEUED": "queued",
    "INITIALIZING": "building",
    "BUILDING": "building",
    "READY": "ready",
    "ERROR": "failed",
    "CANCELED": "canceled",
}

_EVENT_STATE: dict[str, DeployStatus] = {
    "deployment.created": "building",
    "deployment.succeeded": "ready",
    "deployment.ready": "ready",
    "deployment.error": "failed",
    "deployment.canceled": "canceled",
}

_LOG_EVENT_LEVEL: dict[str, LogLevel] = {
    "stdout": "info",
    "command": "info",
    "stderr": "error",
    "fatal": "error",
}


@register
class VercelAdapter(HttpAdapter):
    provider: ClassVar[str] = "vercel"
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {
            Capability.LIST_SERVICES,
            Capability.LIST_DEPLOYS,
            Capability.BUILD_LOGS,
            Capability.WEBHOOKS,
        }
    )
    manifest: ClassVar[ProviderManifest] = ProviderManifest(
        provider="vercel",
        name="Vercel",
        description="Projects, deployments and build logs from the Vercel REST API.",
        availability="available",
        capabilities=sorted(capabilities),
        token_label="Access token",
        token_help_url="https://vercel.com/account/settings/tokens",
        config_fields=[
            ConfigField(
                key="team_id",
                label="Team ID (leave empty for a personal account)",
                required=False,
                placeholder="team_...",
            ),
            ConfigField(
                key="webhook_secret",
                label="Webhook secret (shown once when you create the webhook)",
                required=False,
                placeholder="stored encrypted",
            ),
        ],
        webhook_path="/api/webhooks/vercel",
    )

    async def _get(self, path: str, **params: Any) -> Any:
        if team_id := self.config.get("team_id"):
            params["teamId"] = team_id
        try:
            response = await self.client.get(
                f"{API}{path}",
                params={k: v for k, v in params.items() if v is not None},
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Vercel request failed: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise ProviderError("Vercel rejected the token (check it and the team id)")
        if response.status_code >= 400:
            raise ProviderError(f"Vercel API returned HTTP {response.status_code} for {path}")
        return response.json()

    async def validate(self) -> AccountInfo:
        user = (await self._get("/v2/user")).get("user", {})
        return AccountInfo(account_name=user.get("username") or user.get("email") or "vercel")

    async def list_services(self) -> list[ServiceIn]:
        services: list[ServiceIn] = []
        until: int | None = None
        while True:
            page = await self._get("/v10/projects", limit=100, until=until)
            for project in page.get("projects", []):
                link = project.get("link") or {}
                repo = (
                    f"{link['org']}/{link['repo']}"
                    if link.get("type") == "github" and link.get("org") and link.get("repo")
                    else None
                )
                production = (project.get("targets") or {}).get("production") or {}
                services.append(
                    ServiceIn(
                        external_id=project["id"],
                        name=project["name"],
                        repo=repo,
                        health_url=_production_url(production),
                        latest_deployment=(
                            _deployment_from_api(production, project["id"])
                            if production.get("id")
                            else None
                        ),
                    )
                )
            until = (page.get("pagination") or {}).get("next")
            if not until:
                return services

    async def list_deployments(self, service: ServiceRef, since: datetime) -> list[DeploymentIn]:
        page = await self._get(
            "/v6/deployments",
            projectId=service.external_id,
            since=int(since.timestamp() * 1000),
            limit=100,
        )
        return [_deployment_from_api(item, service.external_id) for item in page["deployments"]]

    async def get_logs(
        self, deployment: DeploymentRef, kind: LogKind, limit: int = 500
    ) -> list[LogLineIn]:
        if kind != "build":
            return []
        events = await self._get(
            f"/v3/deployments/{deployment.external_id}/events",
            builds=1,
            direction="forward",
            limit=limit,
        )
        lines = [line for event in events if (line := _log_line(event)) is not None]
        return lines[-limit:]

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> list[RawEventIn]:
        signature = lower_headers(headers).get("x-vercel-signature", "")
        expected = hmac.new(self._require_secret().encode(), body, hashlib.sha1).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise WebhookVerificationError("x-vercel-signature does not match")
        event = json.loads(body)
        return [
            RawEventIn(
                provider=self.provider,
                event_type=event["type"],
                dedup_key=f"vercel:{event['id']}",
                payload=event,
            )
        ]

    @staticmethod
    def normalize(event_type: str, payload: dict[str, Any]) -> NormalizedBatch:
        status = _EVENT_STATE.get(event_type)
        body = payload.get("payload") or {}
        deployment = body.get("deployment") or {}
        project_id = (body.get("project") or {}).get("id") or body.get("projectId")
        if status is None or not deployment.get("id") or not project_id:
            return NormalizedBatch()
        at = from_epoch_ms(payload.get("createdAt")) or utcnow()
        meta = deployment.get("meta") or {}
        url = deployment.get("url")
        return NormalizedBatch(
            deployments=[
                DeploymentIn(
                    service_external_id=project_id,
                    external_id=deployment["id"],
                    status=status,
                    started_at=at,
                    finished_at=at if status in ("ready", "failed", "canceled") else None,
                    environment=body.get("target") or "preview",
                    url=f"https://{url}" if url else None,
                    **_commit_fields(meta),
                )
            ]
        )


def _commit_fields(meta: dict[str, Any]) -> dict[str, str | None]:
    return {
        "commit_sha": meta.get("githubCommitSha"),
        "commit_message": first_line(meta.get("githubCommitMessage")),
        "commit_author": meta.get("githubCommitAuthorName") or meta.get("githubCommitAuthorLogin"),
        "branch": meta.get("githubCommitRef"),
    }


def _production_url(production: dict[str, Any]) -> str | None:
    """The live site of a project: its first production alias, if that deployment is up."""
    aliases = production.get("alias") or []
    if production.get("readyState") != "READY" or not aliases:
        return None
    return f"https://{aliases[0]}"


def _deployment_from_api(item: dict[str, Any], project_id: str) -> DeploymentIn:
    state = item.get("state") or item.get("readyState") or "QUEUED"
    status = _STATE.get(state, "queued")
    started = from_epoch_ms(item.get("buildingAt") or item.get("created") or item.get("createdAt"))
    finished = (
        from_epoch_ms(item.get("ready") or item.get("readyAt"))
        if status in ("ready", "failed", "canceled")
        else None
    )
    url = item.get("url")
    return DeploymentIn(
        service_external_id=project_id,
        external_id=item.get("uid") or item["id"],  # lists say `uid`, project targets say `id`
        status=status,
        started_at=started or utcnow(),
        finished_at=finished,
        environment=item.get("target") or "preview",
        url=f"https://{url}" if url else None,
        **_commit_fields(item.get("meta") or {}),
    )


def _log_line(event: dict[str, Any]) -> LogLineIn | None:
    """Build events come either flat or with the text nested under `payload`."""
    inner = event.get("payload") or {}
    text = event.get("text") or inner.get("text")
    ts = from_epoch_ms(event.get("created") or event.get("date") or inner.get("date"))
    if not text or ts is None:
        return None
    level = _LOG_EVENT_LEVEL.get(event.get("type", "stdout"), "info")
    if level == "info" and text.lstrip().lower().startswith(("warn", "warning")):
        level = "warn"
    return LogLineIn(ts=ts, level=level, message=text.rstrip("\n"))
