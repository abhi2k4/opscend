"""Netlify adapter (REST API, https://open-api.netlify.com)."""

import base64
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, ClassVar

from app.core.time import parse_iso, utcnow
from app.integrations.base import (
    AccountInfo,
    DeploymentIn,
    DeploymentRef,
    HttpAdapter,
    LogLineIn,
    NormalizedBatch,
    RawEventIn,
    ServiceIn,
    ServiceRef,
    WebhookVerificationError,
    first_line,
    lower_headers,
    repo_slug,
)
from app.integrations.registry import register
from app.schemas import Capability, ConfigField, DeployStatus, LogKind, ProviderManifest

API = "https://api.netlify.com/api/v1"
PAGE = 100

_STATE: dict[str, DeployStatus] = {
    "new": "queued",
    "pending_review": "queued",
    "accepted": "queued",
    "enqueued": "queued",
    "building": "building",
    "uploading": "building",
    "uploaded": "building",
    "preparing": "building",
    "prepared": "building",
    "processing": "building",
    "processed": "building",
    "retrying": "building",
    "ready": "ready",
    "error": "failed",
    "rejected": "canceled",
}
_CONTEXT = {"production": "production", "deploy-preview": "preview", "branch-deploy": "preview"}


@register
class NetlifyAdapter(HttpAdapter):
    provider: ClassVar[str] = "netlify"
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {Capability.LIST_SERVICES, Capability.LIST_DEPLOYS, Capability.WEBHOOKS}
    )
    manifest: ClassVar[ProviderManifest] = ProviderManifest(
        provider="netlify",
        name="Netlify",
        description="Sites and deploys from the Netlify API.",
        availability="available",
        capabilities=sorted(capabilities),
        token_label="Personal access token",
        token_help_url="https://app.netlify.com/user/applications#personal-access-tokens",
        config_fields=[
            ConfigField(
                key="webhook_secret",
                label="Webhook signing secret (the JWS secret token on the outgoing webhook)",
                required=False,
                placeholder="stored encrypted",
            ),
        ],
        webhook_path="/api/webhooks/netlify",
    )

    async def _get(self, path: str, **params: Any) -> Any:
        return await self._json(
            "Netlify",
            "GET",
            f"{API}{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._token}"},
        )

    async def validate(self) -> AccountInfo:
        user = await self._get("/user") or {}
        return AccountInfo(account_name=user.get("full_name") or user.get("email") or "netlify")

    async def list_services(self) -> list[ServiceIn]:
        services: list[ServiceIn] = []
        page = 1
        while True:
            sites = await self._get("/sites", page=page, per_page=PAGE) or []
            for site in sites:
                build = site.get("build_settings") or {}
                published = site.get("published_deploy") or {}
                services.append(
                    ServiceIn(
                        external_id=site["id"],
                        name=site["name"],
                        repo=_repo(build),
                        health_url=site.get("ssl_url") or site.get("url"),
                        latest_deployment=(
                            _deployment(published, site["id"]) if published.get("id") else None
                        ),
                    )
                )
            if len(sites) < PAGE:
                return services
            page += 1

    async def list_deployments(self, service: ServiceRef, since: datetime) -> list[DeploymentIn]:
        deploys = await self._get(f"/sites/{service.external_id}/deploys", page=1, per_page=PAGE)
        normalized = [_deployment(deploy, service.external_id) for deploy in deploys or []]
        return [deploy for deploy in normalized if deploy.started_at >= since]

    async def get_logs(
        self, deployment: DeploymentRef, kind: LogKind, limit: int = 500
    ) -> list[LogLineIn]:
        return []  # Netlify's public API does not serve build logs.

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> list[RawEventIn]:
        _verify_jws(
            lower_headers(headers).get("x-webhook-signature", ""), self._require_secret(), body
        )
        deploy = json.loads(body)
        state = deploy.get("state", "unknown")
        return [
            RawEventIn(
                provider=self.provider,
                event_type=f"deploy.{state}",
                dedup_key=f"netlify:{deploy.get('id')}:{state}",
                payload=deploy,
            )
        ]

    @staticmethod
    def normalize(event_type: str, payload: dict[str, Any]) -> NormalizedBatch:
        if (
            not payload.get("id")
            or not payload.get("site_id")
            or payload.get("state") not in _STATE
        ):
            return NormalizedBatch()
        return NormalizedBatch(deployments=[_deployment(payload, payload["site_id"])])


def _repo(build: dict[str, Any]) -> str | None:
    if build.get("provider") == "github" and build.get("repo_path"):
        return build["repo_path"]
    return repo_slug(build.get("repo_url"))


def _deployment(deploy: dict[str, Any], site_id: str) -> DeploymentIn:
    status = _STATE.get(deploy.get("state", ""), "queued")
    # A cancelled build is reported as an error whose message says so.
    if status == "failed" and "cancel" in (deploy.get("error_message") or "").lower():
        status = "canceled"
    started = parse_iso(deploy.get("created_at")) or utcnow()
    finished = None
    if status in ("ready", "failed", "canceled"):
        finished = parse_iso(deploy.get("published_at") or deploy.get("updated_at"))
    return DeploymentIn(
        service_external_id=site_id,
        external_id=deploy["id"],
        status=status,
        commit_sha=deploy.get("commit_ref"),
        commit_message=first_line(deploy.get("title")),
        commit_author=deploy.get("committer"),
        branch=deploy.get("branch"),
        environment=_CONTEXT.get(deploy.get("context") or "", "preview"),
        started_at=started,
        finished_at=finished,
        url=deploy.get("deploy_ssl_url") or deploy.get("ssl_url"),
    )


def _b64url(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _verify_jws(token: str, secret: str, body: bytes) -> None:
    """Netlify signs deliveries with an HS256 JWS whose `sha256` claim is the body's hash."""
    try:
        header_b64, claims_b64, signature_b64 = token.split(".")
        header = json.loads(_b64url(header_b64))
        claims = json.loads(_b64url(claims_b64))
        signature = _b64url(signature_b64)
    except (ValueError, TypeError) as exc:
        raise WebhookVerificationError("x-webhook-signature is not a valid JWS") from exc
    expected = hmac.new(secret.encode(), f"{header_b64}.{claims_b64}".encode(), hashlib.sha256)
    if header.get("alg") != "HS256" or not hmac.compare_digest(signature, expected.digest()):
        raise WebhookVerificationError("x-webhook-signature does not match")
    if claims.get("iss") != "netlify" or not hmac.compare_digest(
        str(claims.get("sha256", "")), hashlib.sha256(body).hexdigest()
    ):
        raise WebhookVerificationError("x-webhook-signature does not cover this body")
