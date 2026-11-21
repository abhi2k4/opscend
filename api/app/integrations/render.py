"""Render adapter (REST API, https://api-docs.render.com)."""

from datetime import datetime, timedelta
from typing import Any, ClassVar

from app.core.time import parse_iso, utcnow
from app.integrations.base import (
    AccountInfo,
    DeploymentIn,
    DeploymentRef,
    HttpAdapter,
    LogLineIn,
    PollOnly,
    ProviderError,
    ServiceIn,
    ServiceRef,
    first_line,
    repo_slug,
)
from app.integrations.registry import register
from app.schemas import Capability, DeployStatus, LogKind, LogLevel, ProviderManifest

API = "https://api.render.com/v1"
PAGE = 100

_STATUS: dict[str, DeployStatus] = {
    "created": "queued",
    "queued": "queued",
    "build_in_progress": "building",
    "update_in_progress": "building",
    "pre_deploy_in_progress": "building",
    "live": "ready",
    # A deactivated deploy went live and was later replaced by a newer one.
    "deactivated": "ready",
    "build_failed": "failed",
    "update_failed": "failed",
    "pre_deploy_failed": "failed",
    "canceled": "canceled",
}
_LOG_TYPE: dict[str, str] = {"build": "build", "runtime": "app"}
_LEVELS: dict[str, LogLevel] = {
    "debug": "debug",
    "info": "info",
    "notice": "info",
    "warn": "warn",
    "warning": "warn",
    "error": "error",
    "critical": "error",
    "fatal": "error",
}
# Render returns logs by time window, not by deploy; look this far back.
LOG_WINDOW = timedelta(hours=6)


@register
class RenderAdapter(PollOnly, HttpAdapter):
    provider: ClassVar[str] = "render"
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {
            Capability.LIST_SERVICES,
            Capability.LIST_DEPLOYS,
            Capability.BUILD_LOGS,
            Capability.RUNTIME_LOGS,
        }
    )
    manifest: ClassVar[ProviderManifest] = ProviderManifest(
        provider="render",
        name="Render",
        description="Services, deploys and logs from the Render API.",
        availability="available",
        capabilities=sorted(capabilities),
        token_label="API key",
        token_help_url="https://dashboard.render.com/u/settings#api-keys",
        config_fields=[],
        webhook_path=None,
    )

    async def _get(self, path: str, **params: Any) -> Any:
        return await self._json(
            "Render",
            "GET",
            f"{API}{path}",
            params={k: v for k, v in params.items() if v is not None},
            headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
        )

    async def _pages(self, path: str, key: str, **params: Any) -> list[dict[str, Any]]:
        """Follow Render's cursor paging: each item carries the cursor to continue after it."""
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = await self._get(path, limit=PAGE, cursor=cursor, **params) or []
            items.extend(entry[key] for entry in page if entry.get(key))
            if len(page) < PAGE:
                return items
            cursor = page[-1].get("cursor")
            if not cursor:
                return items

    async def validate(self) -> AccountInfo:
        owners = await self._pages("/owners", "owner")
        if not owners:
            raise ProviderError("Render returned no workspace for this API key")
        return AccountInfo(account_name=owners[0].get("name") or owners[0].get("email") or "render")

    async def list_services(self) -> list[ServiceIn]:
        return [
            ServiceIn(
                external_id=service["id"],
                name=service["name"],
                repo=repo_slug(service.get("repo")),
                health_url=(service.get("serviceDetails") or {}).get("url"),
                meta={"owner_id": service.get("ownerId"), "type": service.get("type")},
            )
            for service in await self._pages("/services", "service", includePreviews="false")
        ]

    async def list_deployments(self, service: ServiceRef, since: datetime) -> list[DeploymentIn]:
        deploys = await self._pages(
            f"/services/{service.external_id}/deploys",
            "deploy",
            createdAfter=since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        return [_deployment(deploy, service) for deploy in deploys]

    async def get_logs(
        self, deployment: DeploymentRef, kind: LogKind, limit: int = 500
    ) -> list[LogLineIn]:
        owner_id = deployment.service.meta.get("owner_id")
        if not owner_id:
            return []
        now = utcnow()
        page = await self._get(
            "/logs",
            ownerId=owner_id,
            resource=deployment.service.external_id,
            type=_LOG_TYPE[kind],
            startTime=(now - LOG_WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ"),
            endTime=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            direction="backward",
            limit=min(limit, PAGE),
        )
        lines = [line for entry in (page or {}).get("logs", []) if (line := _log_line(entry))]
        return sorted(lines, key=lambda line: line.ts)


def _deployment(deploy: dict[str, Any], service: ServiceRef) -> DeploymentIn:
    status = _STATUS.get(deploy.get("status", ""), "queued")
    commit = deploy.get("commit") or {}
    started = parse_iso(deploy.get("startedAt") or deploy.get("createdAt")) or utcnow()
    finished = (
        parse_iso(deploy.get("finishedAt")) if status in ("ready", "failed", "canceled") else None
    )
    return DeploymentIn(
        service_external_id=service.external_id,
        external_id=deploy["id"],
        status=status,
        commit_sha=commit.get("id"),
        commit_message=first_line(commit.get("message")),
        started_at=started,
        finished_at=finished,
        environment="production",
    )


def _log_line(entry: dict[str, Any]) -> LogLineIn | None:
    ts = parse_iso(entry.get("timestamp"))
    message = entry.get("message")
    if ts is None or not message:
        return None
    labels = {label.get("name"): label.get("value") for label in entry.get("labels") or []}
    level = _LEVELS.get(str(labels.get("level", "")).lower(), "info")
    return LogLineIn(ts=ts, level=level, message=message.rstrip("\n"))
