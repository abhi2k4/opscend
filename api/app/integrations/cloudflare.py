"""Cloudflare Pages adapter (REST API, https://developers.cloudflare.com/api/resources/pages)."""

from datetime import datetime
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
)
from app.integrations.registry import register
from app.schemas import Capability, ConfigField, DeployStatus, LogKind, LogLevel, ProviderManifest

API = "https://api.cloudflare.com/client/v4"
PAGE = 25
MAX_PAGES = 20


@register
class CloudflareAdapter(PollOnly, HttpAdapter):
    provider: ClassVar[str] = "cloudflare"
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {Capability.LIST_SERVICES, Capability.LIST_DEPLOYS, Capability.BUILD_LOGS}
    )
    manifest: ClassVar[ProviderManifest] = ProviderManifest(
        provider="cloudflare",
        name="Cloudflare",
        description="Pages projects, deployments and build logs from the Cloudflare API.",
        availability="available",
        capabilities=sorted(capabilities),
        token_label="API token (Pages: Read)",
        token_help_url="https://dash.cloudflare.com/profile/api-tokens",
        config_fields=[
            ConfigField(
                key="account_id",
                label="Account ID",
                required=True,
                placeholder="32 hex characters, from the dashboard URL",
            ),
        ],
        webhook_path=None,
    )

    @property
    def _account(self) -> str:
        account_id = self.config.get("account_id")
        if not account_id:
            raise ProviderError("Cloudflare needs an account ID")
        return f"/accounts/{account_id}"

    async def _get(self, path: str, **params: Any) -> dict[str, Any]:
        body = await self._json(
            "Cloudflare",
            "GET",
            f"{API}{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        if not (body or {}).get("success", False):
            raise ProviderError(f"Cloudflare API reported an error for {path}")
        return body

    async def _pages(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            body = await self._get(path, page=page, per_page=PAGE)
            batch = body.get("result") or []
            items.extend(batch)
            total_pages = (body.get("result_info") or {}).get("total_pages")
            if len(batch) < PAGE or (total_pages is not None and page >= total_pages):
                break
        return items

    async def validate(self) -> AccountInfo:
        # Listing projects proves both the token and the account id in one call.
        projects = (await self._get(f"{self._account}/pages/projects", page=1, per_page=1)).get(
            "result"
        ) or []
        suffix = str(self.config["account_id"])[:8]
        return AccountInfo(
            account_name=f"Pages · {suffix}" if not projects else f"Pages · {projects[0]['name']}"
        )

    async def list_services(self) -> list[ServiceIn]:
        services: list[ServiceIn] = []
        for project in await self._pages(f"{self._account}/pages/projects"):
            name = project["name"]
            source = project.get("source") or {}
            config = source.get("config") or {}
            repo = (
                f"{config['owner']}/{config['repo_name']}"
                if source.get("type") == "github"
                and config.get("owner")
                and config.get("repo_name")
                else None
            )
            domains = project.get("domains") or []
            host = domains[-1] if domains else project.get("subdomain")
            latest = project.get("canonical_deployment") or project.get("latest_deployment") or {}
            services.append(
                ServiceIn(
                    # Every Pages endpoint is addressed by project name, so that is the id.
                    external_id=name,
                    name=name,
                    repo=repo,
                    health_url=f"https://{host}" if host else None,
                    latest_deployment=_deployment(latest, name) if latest.get("id") else None,
                )
            )
        return services

    async def list_deployments(self, service: ServiceRef, since: datetime) -> list[DeploymentIn]:
        body = await self._get(
            f"{self._account}/pages/projects/{service.external_id}/deployments",
            page=1,
            per_page=PAGE,
        )
        deployments = [_deployment(item, service.external_id) for item in body.get("result") or []]
        return [deployment for deployment in deployments if deployment.started_at >= since]

    async def get_logs(
        self, deployment: DeploymentRef, kind: LogKind, limit: int = 500
    ) -> list[LogLineIn]:
        if kind != "build":
            return []
        body = await self._get(
            f"{self._account}/pages/projects/{deployment.service.external_id}"
            f"/deployments/{deployment.external_id}/history/logs"
        )
        entries = (body.get("result") or {}).get("data") or []
        lines = [line for entry in entries if (line := _log_line(entry)) is not None]
        return lines[-limit:]


def _status(stage: dict[str, Any]) -> DeployStatus:
    state = stage.get("status")
    if state == "failure":
        return "failed"
    if state == "canceled":
        return "canceled"
    if state == "success" and stage.get("name") == "deploy":
        return "ready"
    if state == "idle" and stage.get("name") in (None, "queued"):
        return "queued"
    return "building"


def _deployment(item: dict[str, Any], project: str) -> DeploymentIn:
    stage = item.get("latest_stage") or {}
    status = _status(stage)
    trigger = (item.get("deployment_trigger") or {}).get("metadata") or {}
    finished = None
    if status in ("ready", "failed", "canceled"):
        finished = parse_iso(stage.get("ended_on") or item.get("modified_on"))
    return DeploymentIn(
        service_external_id=project,
        external_id=item["id"],
        status=status,
        commit_sha=trigger.get("commit_hash"),
        commit_message=first_line(trigger.get("commit_message")),
        branch=trigger.get("branch"),
        environment=item.get("environment") or "preview",
        started_at=parse_iso(item.get("created_on")) or utcnow(),
        finished_at=finished,
        url=item.get("url"),
    )


def _log_line(entry: dict[str, Any]) -> LogLineIn | None:
    ts = parse_iso(entry.get("ts"))
    text = entry.get("line")
    if ts is None or not text:
        return None
    lowered = text.lstrip().lower()
    level: LogLevel = "info"
    if lowered.startswith(("error", "failed", "✘")) or "error:" in lowered:
        level = "error"
    elif lowered.startswith(("warn", "▲")):
        level = "warn"
    return LogLineIn(ts=ts, level=level, message=text.rstrip("\n"))
