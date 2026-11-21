"""AWS adapter: Amplify Hosting apps and ECS services.

Calls are signed here with Signature Version 4, so no SDK is needed. The stored
token is the secret access key; the access key id and region are plain config.
"""

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import quote

from app.core.time import utcnow
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
from app.schemas import Capability, ConfigField, DeployStatus, LogKind, LogLevel, ProviderManifest

ECS_TARGET = "AmazonEC2ContainerServiceV20141113"
MAX_PAGES = 10

_AMPLIFY_STATUS: dict[str, DeployStatus] = {
    "CREATED": "queued",
    "PENDING": "queued",
    "PROVISIONING": "building",
    "RUNNING": "building",
    "CANCELLING": "building",
    "SUCCEED": "ready",
    "FAILED": "failed",
    "CANCELLED": "canceled",
}
_ECS_ROLLOUT: dict[str, DeployStatus] = {
    "IN_PROGRESS": "building",
    "COMPLETED": "ready",
    "FAILED": "failed",
}


def sign(
    *,
    method: str,
    host: str,
    path: str,
    query: dict[str, str],
    headers: dict[str, str],
    body: bytes,
    service: str,
    region: str,
    access_key_id: str,
    secret_access_key: str,
    now: datetime,
) -> dict[str, str]:
    """Return `headers` plus the SigV4 `Authorization`, `Host` and `X-Amz-Date` headers."""
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = amz_date[:8]
    signed = {key.lower(): value.strip() for key, value in headers.items()}
    signed |= {"host": host, "x-amz-date": amz_date}
    names = ";".join(sorted(signed))
    canonical_query = "&".join(
        f"{quote(key, safe='-_.~')}={quote(value, safe='-_.~')}"
        for key, value in sorted(query.items())
    )
    canonical = "\n".join(
        [
            method,
            # Every service but S3 signs the already-encoded path encoded once more.
            quote(path, safe="/-_.~"),
            canonical_query,
            "".join(f"{name}:{signed[name]}\n" for name in sorted(signed)),
            names,
            hashlib.sha256(body).hexdigest(),
        ]
    )
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    key = f"AWS4{secret_access_key}".encode()
    for part in (date, region, service, "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        **headers,
        "Host": host,
        "X-Amz-Date": amz_date,
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key_id}/{scope}, "
            f"SignedHeaders={names}, Signature={signature}"
        ),
    }


@register
class AwsAdapter(PollOnly, HttpAdapter):
    provider: ClassVar[str] = "aws"
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {Capability.LIST_SERVICES, Capability.LIST_DEPLOYS, Capability.BUILD_LOGS}
    )
    manifest: ClassVar[ProviderManifest] = ProviderManifest(
        provider="aws",
        name="AWS",
        description="Amplify Hosting builds (with build logs) and ECS service rollouts.",
        availability="available",
        capabilities=sorted(capabilities),
        token_label="Secret access key (read-only IAM user)",
        token_help_url="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html",
        config_fields=[
            ConfigField(
                key="access_key_id", label="Access key ID", required=True, placeholder="AKIA..."
            ),
            ConfigField(key="region", label="Region", required=True, placeholder="us-east-1"),
        ],
        webhook_path=None,
    )

    async def _call(
        self,
        service: str,
        method: str,
        path: str = "/",
        *,
        query: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> Any:
        region = str(self.config.get("region") or "").strip()
        access_key_id = str(self.config.get("access_key_id") or "").strip()
        if not region or not access_key_id:
            raise ProviderError("AWS needs an access key ID and a region")
        host = f"{service}.{region}.amazonaws.com"
        query = query or {}
        signed = sign(
            method=method,
            host=host,
            path=path,
            query=query,
            headers=headers or {},
            body=body,
            service=service,
            region=region,
            access_key_id=access_key_id,
            secret_access_key=self._token,
            now=utcnow(),
        )
        # Send the query exactly as it was signed.
        encoded = "&".join(
            f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(query.items())
        )
        suffix = f"?{encoded}" if encoded else ""
        try:
            response = await self.client.request(
                method, f"https://{host}{path}{suffix}", headers=signed, content=body
            )
        except Exception as exc:
            raise ProviderError(f"AWS request failed: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise ProviderError(
                f"AWS denied the {service} call (check the keys, region and IAM permissions)"
            )
        if response.status_code >= 400:
            raise ProviderError(f"AWS {service} API returned HTTP {response.status_code}")
        return response

    async def _amplify(self, path: str, key: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        token: str | None = None
        for _ in range(MAX_PAGES):
            query = {"maxResults": "50"} | ({"nextToken": token} if token else {})
            page = (await self._call("amplify", "GET", path, query=query)).json()
            items.extend(page.get(key) or [])
            token = page.get("nextToken")
            if not token:
                break
        return items

    async def _ecs(self, action: str, **payload: Any) -> dict[str, Any]:
        response = await self._call(
            "ecs",
            "POST",
            headers={
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": f"{ECS_TARGET}.{action}",
            },
            body=json.dumps(payload).encode(),
        )
        return response.json()

    async def _ecs_list(self, action: str, key: str, **payload: Any) -> list[str]:
        arns: list[str] = []
        token: str | None = None
        for _ in range(MAX_PAGES):
            extra = {"nextToken": token} if token else {}
            page = await self._ecs(action, maxResults=100, **payload, **extra)
            arns.extend(page.get(key) or [])
            token = page.get("nextToken")
            if not token:
                break
        return arns

    async def validate(self) -> AccountInfo:
        response = await self._call(
            "sts",
            "POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=b"Action=GetCallerIdentity&Version=2011-06-15",
        )
        account = re.search(r"<Account>(\d+)</Account>", response.text)
        return AccountInfo(
            account_name=f"{account.group(1) if account else 'aws'} · {self.config['region']}"
        )

    async def list_services(self) -> list[ServiceIn]:
        """Amplify branches and ECS services. A product the keys cannot read is skipped."""
        services: list[ServiceIn] = []
        failures: list[ProviderError] = []
        for source in (self._amplify_services, self._ecs_services):
            try:
                services.extend(await source())
            except ProviderError as exc:
                failures.append(exc)
        if len(failures) == 2:
            raise failures[0]
        return services

    async def _amplify_services(self) -> list[ServiceIn]:
        services: list[ServiceIn] = []
        for app in await self._amplify("/apps", "apps"):
            app_id, domain = app["appId"], app.get("defaultDomain")
            for branch in await self._amplify(f"/apps/{app_id}/branches", "branches"):
                name = branch["branchName"]
                prefix = branch.get("displayName") or name
                production = branch.get("stage") == "PRODUCTION"
                services.append(
                    ServiceIn(
                        external_id=f"amplify:{app_id}:{name}",
                        name=app["name"] if production else f"{app['name']} ({name})",
                        repo=repo_slug(app.get("repository")),
                        health_url=f"https://{prefix}.{domain}" if domain else None,
                        meta={"kind": "amplify", "app_id": app_id, "branch": name},
                    )
                )
        return services

    async def _ecs_services(self) -> list[ServiceIn]:
        services: list[ServiceIn] = []
        for cluster_arn in await self._ecs_list("ListClusters", "clusterArns"):
            cluster = cluster_arn.rsplit("/", 1)[-1]
            for service_arn in await self._ecs_list("ListServices", "serviceArns", cluster=cluster):
                name = service_arn.rsplit("/", 1)[-1]
                services.append(
                    ServiceIn(
                        external_id=f"ecs:{cluster}:{name}",
                        name=name,
                        meta={"kind": "ecs", "cluster": cluster, "service": name},
                    )
                )
        return services

    async def list_deployments(self, service: ServiceRef, since: datetime) -> list[DeploymentIn]:
        kind, first, second = _parts(service.external_id)
        if kind == "amplify":
            path = f"/apps/{first}/branches/{quote(second, safe='')}/jobs"
            page = (await self._call("amplify", "GET", path, query={"maxResults": "50"})).json()
            jobs = [
                _amplify_job(job, service.external_id, second)
                for job in page.get("jobSummaries") or []
            ]
            return [job for job in jobs if job.started_at >= since]
        described = await self._ecs("DescribeServices", cluster=first, services=[second])
        deployments = [
            _ecs_deployment(deployment, service.external_id)
            for item in described.get("services") or []
            for deployment in item.get("deployments") or []
        ]
        return [deployment for deployment in deployments if deployment.started_at >= since]

    async def get_logs(
        self, deployment: DeploymentRef, kind: LogKind, limit: int = 500
    ) -> list[LogLineIn]:
        source, app_id, branch = _parts(deployment.service.external_id)
        if kind != "build" or source != "amplify":
            return []
        job_id = deployment.external_id.rsplit(":", 1)[-1]
        path = f"/apps/{app_id}/branches/{quote(branch, safe='')}/jobs/{job_id}"
        job = (await self._call("amplify", "GET", path)).json().get("job") or {}
        lines: list[LogLineIn] = []
        for step in job.get("steps") or []:
            if not step.get("logUrl"):
                continue
            # A pre-signed, short-lived link to the step's log file; it needs no auth header.
            text = await self.client.get(step["logUrl"])
            if text.status_code != 200:
                continue
            at = _epoch(step.get("startTime")) or utcnow()
            failed = step.get("status") == "FAILED"
            lines.extend(_log_line(line, at, failed) for line in text.text.splitlines() if line)
        return lines[-limit:]


def _parts(external_id: str) -> tuple[str, str, str]:
    kind, first, second = external_id.split(":", 2)
    return kind, first, second


def _epoch(value: Any) -> datetime | None:
    return datetime.fromtimestamp(float(value), UTC) if value else None


def _amplify_job(job: dict[str, Any], service_id: str, branch: str) -> DeploymentIn:
    status = _AMPLIFY_STATUS.get(job.get("status", ""), "queued")
    commit = job.get("commitId")
    return DeploymentIn(
        service_external_id=service_id,
        external_id=f"{service_id}:{job['jobId']}",
        status=status,
        commit_sha=commit if commit and commit != "HEAD" else None,
        commit_message=first_line(job.get("commitMessage")),
        branch=branch,
        environment="production",
        started_at=_epoch(job.get("startTime")) or utcnow(),
        finished_at=_epoch(job.get("endTime"))
        if status in ("ready", "failed", "canceled")
        else None,
    )


def _ecs_deployment(deployment: dict[str, Any], service_id: str) -> DeploymentIn:
    rollout = deployment.get("rolloutState")
    # Services without rolling-update state report only PRIMARY/ACTIVE/INACTIVE.
    status = _ECS_ROLLOUT.get(rollout or "", "ready" if rollout is None else "building")
    task_definition = str(deployment.get("taskDefinition") or "").rsplit("/", 1)[-1]
    return DeploymentIn(
        service_external_id=service_id,
        external_id=deployment["id"],
        status=status,
        commit_message=first_line(deployment.get("rolloutStateReason")) or task_definition or None,
        environment="production",
        started_at=_epoch(deployment.get("createdAt")) or utcnow(),
        finished_at=_epoch(deployment.get("updatedAt")) if status in ("ready", "failed") else None,
    )


def _log_line(text: str, at: datetime, step_failed: bool) -> LogLineIn:
    level: LogLevel = "info"
    if "[ERROR]" in text or "!!!" in text or (step_failed and "error" in text.lower()):
        level = "error"
    elif "[WARNING]" in text:
        level = "warn"
    # Amplify log lines start with their own timestamp; fall back to the step's start.
    stamp = re.match(r"(\d{4}-\d{2}-\d{2}T[\d:.]+Z)", text)
    ts = at
    if stamp:
        try:
            ts = datetime.fromisoformat(stamp.group(1).replace("Z", "+00:00"))
        except ValueError:
            ts = at
    return LogLineIn(ts=ts, level=level, message=text)
