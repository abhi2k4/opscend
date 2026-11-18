"""GitHub adapter (REST API). GitHub is a commit source, not a deploy provider:
it feeds the `commit` table and serves commit diffs to the investigator."""

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, ClassVar

import httpx

from app.core.time import parse_iso, utcnow
from app.integrations.base import (
    AccountInfo,
    CommitIn,
    DeploymentIn,
    DeploymentRef,
    HttpAdapter,
    LogLineIn,
    NormalizedBatch,
    ProviderError,
    RawEventIn,
    ResourceUnavailableError,
    ServiceIn,
    ServiceRef,
    WebhookVerificationError,
    lower_headers,
)
from app.integrations.registry import register
from app.schemas import (
    Capability,
    CommitDiff,
    ConfigField,
    DiffFile,
    LogKind,
    ProviderManifest,
)

API = "https://api.github.com"
_FILE_STATUS = {"added": "added", "removed": "removed", "renamed": "renamed"}
MAX_PATCH_CHARS = 20_000


@register
class GitHubAdapter(HttpAdapter):
    provider: ClassVar[str] = "github"
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {Capability.COMMITS, Capability.COMMIT_DIFF, Capability.WEBHOOKS}
    )
    manifest: ClassVar[ProviderManifest] = ProviderManifest(
        provider="github",
        name="GitHub",
        description="Commits and diffs, so a failed deploy can be traced to the change behind it.",
        availability="available",
        capabilities=sorted(capabilities),
        token_label="Personal access token",
        token_help_url="https://github.com/settings/personal-access-tokens",
        config_fields=[
            ConfigField(
                key="repos",
                label="Repositories (comma separated; empty = repos linked to your services)",
                required=False,
                placeholder="acme/storefront, acme/api",
            ),
            ConfigField(
                key="webhook_secret",
                label="Webhook secret (the one you set on the repository webhook)",
                required=False,
                placeholder="stored encrypted",
            ),
        ],
        webhook_path="/api/webhooks/github",
    )

    async def _get(self, path: str, **params: Any) -> Any:
        try:
            response = await self.client.get(
                f"{API}{path}",
                params=params,
                follow_redirects=True,  # renamed or transferred repos answer 301
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"GitHub request failed: {type(exc).__name__}") from exc
        if response.status_code == 401:
            raise ProviderError("GitHub rejected the token")
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            raise ProviderError("GitHub rate limit reached; the next poll will retry")
        if response.status_code in (403, 404, 409, 451):
            # 403: a fine-grained token without access to this repo. 409: an empty repo.
            raise ResourceUnavailableError(
                f"GitHub: {path} is not readable with this token (HTTP {response.status_code})"
            )
        if response.status_code >= 400:
            raise ProviderError(f"GitHub API returned HTTP {response.status_code} for {path}")
        return response.json()

    async def validate(self) -> AccountInfo:
        return AccountInfo(account_name=(await self._get("/user"))["login"])

    async def list_services(self) -> list[ServiceIn]:
        return []

    async def list_deployments(self, service: ServiceRef, since: datetime) -> list[DeploymentIn]:
        return []

    async def get_logs(
        self, deployment: DeploymentRef, kind: LogKind, limit: int = 500
    ) -> list[LogLineIn]:
        return []

    async def list_repos(self) -> list[str]:
        """Explicitly configured repos, else the ten most recently pushed ones."""
        configured = self.config.get("repos")
        if isinstance(configured, str):
            configured = [part.strip() for part in configured.split(",")]
        if configured := [repo for repo in configured or [] if repo]:
            return configured
        repos = await self._get("/user/repos", sort="pushed", per_page=10)
        return [repo["full_name"] for repo in repos]

    async def list_commits(self, repo: str, since: datetime) -> list[CommitIn]:
        items = await self._get(
            f"/repos/{repo}/commits",
            since=since.strftime("%Y-%m-%dT%H:%M:%SZ"),
            per_page=50,
        )
        if not isinstance(items, list):
            raise ResourceUnavailableError(f"GitHub: unexpected commits response for {repo}")
        return [_commit_from_api(repo, item) for item in items]

    async def get_commit_diff(self, repo: str, sha: str) -> CommitDiff:
        data = await self._get(f"/repos/{repo}/commits/{sha}")
        commit = data.get("commit") or {}
        return CommitDiff(
            repo=repo,
            sha=data["sha"],
            message=commit.get("message", ""),
            author=(commit.get("author") or {}).get("name") or "unknown",
            files=[_diff_file(item) for item in data.get("files", [])],
        )

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> list[RawEventIn]:
        lowered = lower_headers(headers)
        digest = hmac.new(self._require_secret().encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(lowered.get("x-hub-signature-256", ""), f"sha256={digest}"):
            raise WebhookVerificationError("X-Hub-Signature-256 does not match")
        delivery = lowered.get("x-github-delivery") or hashlib.sha256(body).hexdigest()[:32]
        return [
            RawEventIn(
                provider=self.provider,
                event_type=lowered.get("x-github-event", "unknown"),
                dedup_key=f"github:{delivery}",
                payload=json.loads(body),
            )
        ]

    @staticmethod
    def normalize(event_type: str, payload: dict[str, Any]) -> NormalizedBatch:
        repo = (payload.get("repository") or {}).get("full_name")
        if event_type != "push" or not repo:
            return NormalizedBatch()
        commits = []
        for item in payload.get("commits") or []:
            author = item.get("author") or {}
            commits.append(
                CommitIn(
                    repo=repo,
                    sha=item["id"],
                    message=item.get("message", ""),
                    author=author.get("name") or author.get("username") or "unknown",
                    committed_at=parse_iso(item.get("timestamp")) or utcnow(),
                    url=item.get("url"),
                )
            )
        return NormalizedBatch(commits=commits)


def _commit_from_api(repo: str, item: dict[str, Any]) -> CommitIn:
    commit = item.get("commit") or {}
    author = commit.get("author") or {}
    return CommitIn(
        repo=repo,
        sha=item["sha"],
        message=commit.get("message", ""),
        author=author.get("name") or (item.get("author") or {}).get("login") or "unknown",
        committed_at=parse_iso(author.get("date")) or utcnow(),
        url=item.get("html_url"),
    )


def _diff_file(item: dict[str, Any]) -> DiffFile:
    patch = item.get("patch")
    if patch and len(patch) > MAX_PATCH_CHARS:
        patch = patch[:MAX_PATCH_CHARS] + "\n… (patch truncated)"
    return DiffFile(
        filename=item["filename"],
        status=_FILE_STATUS.get(item.get("status", ""), "modified"),
        additions=item.get("additions", 0),
        deletions=item.get("deletions", 0),
        patch=patch,
    )
