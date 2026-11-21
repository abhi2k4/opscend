"""Fly.io adapter (GraphQL API for apps and releases, HTTP API for logs)."""

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
from app.schemas import Capability, DeployStatus, LogKind, LogLevel, ProviderManifest

BASE = "https://api.fly.io"
GRAPHQL = f"{BASE}/graphql"
MAX_PAGES = 10

_VIEWER = "query { viewer { ... on User { email } ... on Macaroon { email } } }"
_APPS = """
query($after: String) {
  apps(first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { id name hostname status organization { slug } }
  }
}
"""
_RELEASES = """
query($appName: String!, $limit: Int!) {
  app(name: $appName) {
    releases: releasesUnprocessed(first: $limit) {
      nodes { id version description reason status imageRef user { email name } createdAt }
    }
  }
}
"""

# Fly does not publish the full list of release states; anything not named here is
# treated as shipped, because a release only gets a version once it is rolled out.
_STATUS: dict[str, DeployStatus] = {
    "pending": "queued",
    "running": "building",
    "in_progress": "building",
    "complete": "ready",
    "completed": "ready",
    "succeeded": "ready",
    "failed": "failed",
    "dead": "failed",
    "interrupted": "canceled",
    "cancelled": "canceled",
    "canceled": "canceled",
}
_LEVELS: dict[str, LogLevel] = {
    "debug": "debug",
    "info": "info",
    "warn": "warn",
    "warning": "warn",
    "error": "error",
    "fatal": "error",
}


@register
class FlyAdapter(PollOnly, HttpAdapter):
    provider: ClassVar[str] = "fly"
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {Capability.LIST_SERVICES, Capability.LIST_DEPLOYS, Capability.RUNTIME_LOGS}
    )
    manifest: ClassVar[ProviderManifest] = ProviderManifest(
        provider="fly",
        name="Fly.io",
        description="Apps, releases and recent machine logs from Fly.io.",
        availability="available",
        capabilities=sorted(capabilities),
        token_label="Access token (fly tokens create readonly)",
        token_help_url="https://fly.io/docs/security/tokens/",
        config_fields=[],
        webhook_path=None,
    )

    def _auth(self) -> dict[str, str]:
        """Macaroon tokens (`fm1…`, `fm2…`) use the FlyV1 scheme; older tokens use Bearer."""
        token = self._token.strip()
        for scheme in ("FlyV1 ", "Bearer "):
            token = token.removeprefix(scheme)
        scheme = "FlyV1" if token.split("_", 1)[0] in ("fm1r", "fm1a", "fm2") else "Bearer"
        return {"Authorization": f"{scheme} {token}"}

    async def _graphql(self, query: str, **variables: Any) -> dict[str, Any]:
        body = await self._json(
            "Fly.io",
            "POST",
            GRAPHQL,
            json={"query": query, "variables": variables},
            headers=self._auth(),
        )
        if errors := (body or {}).get("errors"):
            message = str(errors[0].get("message", "unknown error"))[:200]
            raise ProviderError(f"Fly.io API error: {message}")
        return (body or {}).get("data") or {}

    async def validate(self) -> AccountInfo:
        viewer = (await self._graphql(_VIEWER)).get("viewer") or {}
        return AccountInfo(account_name=viewer.get("email") or "fly.io")

    async def list_services(self) -> list[ServiceIn]:
        services: list[ServiceIn] = []
        after: str | None = None
        for _ in range(MAX_PAGES):
            apps = (await self._graphql(_APPS, after=after)).get("apps") or {}
            for app in apps.get("nodes") or []:
                host = app.get("hostname")
                services.append(
                    ServiceIn(
                        # Fly addresses apps by name everywhere.
                        external_id=app["name"],
                        name=app["name"],
                        health_url=f"https://{host}" if host else None,
                        meta={"org": (app.get("organization") or {}).get("slug")},
                    )
                )
            info = apps.get("pageInfo") or {}
            after = info.get("endCursor")
            if not info.get("hasNextPage") or not after:
                break
        return services

    async def list_deployments(self, service: ServiceRef, since: datetime) -> list[DeploymentIn]:
        data = await self._graphql(_RELEASES, appName=service.external_id, limit=25)
        nodes = ((data.get("app") or {}).get("releases") or {}).get("nodes") or []
        releases = [_release(node, service.external_id) for node in nodes]
        return [release for release in releases if release.started_at >= since]

    async def get_logs(
        self, deployment: DeploymentRef, kind: LogKind, limit: int = 500
    ) -> list[LogLineIn]:
        if kind != "runtime":
            return []
        # Fly serves the app's recent log buffer; it is not split by release.
        body = await self._json(
            "Fly.io",
            "GET",
            f"{BASE}/api/v1/apps/{deployment.service.external_id}/logs",
            params={"next_token": ""},
            headers=self._auth(),
        )
        entries = (body or {}).get("data") or []
        lines = [line for entry in entries if (line := _log_line(entry)) is not None]
        return lines[-limit:]


def _release(node: dict[str, Any], app: str) -> DeploymentIn:
    status = _STATUS.get(str(node.get("status") or "").lower(), "ready")
    created = parse_iso(node.get("createdAt")) or utcnow()
    user = node.get("user") or {}
    return DeploymentIn(
        service_external_id=app,
        external_id=node["id"],
        status=status,
        commit_message=first_line(node.get("description")) or f"Release v{node.get('version')}",
        commit_author=user.get("name") or user.get("email"),
        environment="production",
        started_at=created,
        # Releases carry one timestamp, so duration is unknown.
        finished_at=created if status in ("ready", "failed", "canceled") else None,
    )


def _log_line(entry: dict[str, Any]) -> LogLineIn | None:
    attributes = entry.get("attributes") or {}
    ts = parse_iso(attributes.get("timestamp"))
    message = attributes.get("message")
    if ts is None or not message:
        return None
    level = _LEVELS.get(str(attributes.get("level") or "").lower(), "info")
    return LogLineIn(ts=ts, level=level, message=message.rstrip("\n"))
