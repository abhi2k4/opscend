"""The provider adapter contract.

Every call to a provider goes through an adapter implementing `ProviderAdapter`.
Adapters only translate: they turn provider payloads into the small normalized
`*In` models below and never touch the database.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field

from app.schemas import Capability, CommitDiff, DeployStatus, LogKind, LogLevel, ProviderManifest

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class ProviderError(Exception):
    """A provider rejected a call. The message is safe to show the user (never holds a token)."""


class ResourceUnavailableError(ProviderError):
    """One resource (a repo, a project) is out of this token's reach; the rest still work."""


class WebhookVerificationError(Exception):
    """A webhook delivery failed signature or shared-secret verification."""


class AccountInfo(BaseModel):
    account_name: str


class DeploymentIn(BaseModel):
    service_external_id: str
    external_id: str
    status: DeployStatus
    commit_sha: str | None = None
    commit_message: str | None = None
    commit_author: str | None = None
    branch: str | None = None
    environment: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    url: str | None = None


class ServiceIn(BaseModel):
    external_id: str
    name: str
    repo: str | None = None
    health_url: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    # The provider's current production deployment, when it reports one. Lets a
    # service show its last deploy even when that is older than the sync window.
    latest_deployment: DeploymentIn | None = None


class CommitIn(BaseModel):
    repo: str
    sha: str
    message: str
    author: str
    committed_at: datetime
    url: str | None = None


class LogLineIn(BaseModel):
    ts: datetime
    level: LogLevel
    message: str


class RawEventIn(BaseModel):
    """One verified inbound event, ready to be stored as a `raw_event` row."""

    provider: str
    event_type: str
    dedup_key: str
    payload: dict[str, Any]


class NormalizedBatch(BaseModel):
    """What one raw event means once translated into Opscend's own model."""

    deployments: list[DeploymentIn] = Field(default_factory=list)
    commits: list[CommitIn] = Field(default_factory=list)


@dataclass(frozen=True)
class ServiceRef:
    """The parts of a stored service an adapter needs to query its provider."""

    external_id: str
    name: str
    repo: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeploymentRef:
    external_id: str
    service: ServiceRef


@runtime_checkable
class ProviderAdapter(Protocol):
    """What Opscend needs from a deploy or source provider.

    `capabilities` says which methods are meaningful; callers check it before
    calling, and the UI reads it to hide what a provider cannot do.
    """

    provider: ClassVar[str]
    capabilities: ClassVar[frozenset[Capability]]
    manifest: ClassVar[ProviderManifest]

    def __init__(
        self,
        token: str,
        config: dict[str, Any] | None = None,
        *,
        webhook_secret: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None: ...

    async def validate(self) -> AccountInfo: ...

    async def list_services(self) -> list[ServiceIn]: ...

    async def list_deployments(
        self, service: ServiceRef, since: datetime
    ) -> list[DeploymentIn]: ...

    async def get_logs(
        self, deployment: DeploymentRef, kind: LogKind, limit: int = 500
    ) -> list[LogLineIn]: ...

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> list[RawEventIn]:
        """Verify the delivery (raising `WebhookVerificationError`) and split it into events."""
        ...

    @staticmethod
    def normalize(event_type: str, payload: dict[str, Any]) -> NormalizedBatch:
        """Translate a stored raw event payload. Pure: needs no token and no network."""
        ...


@runtime_checkable
class CommitSource(Protocol):
    """Extra surface for source-control providers (capabilities COMMITS / COMMIT_DIFF)."""

    async def list_repos(self) -> list[str]: ...

    async def list_commits(self, repo: str, since: datetime) -> list[CommitIn]: ...

    async def get_commit_diff(self, repo: str, sha: str) -> CommitDiff: ...


class HttpAdapter:
    """Shared plumbing: holds the token privately and owns (or borrows) an httpx client."""

    def __init__(
        self,
        token: str,
        config: dict[str, Any] | None = None,
        *,
        webhook_secret: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token
        self._webhook_secret = webhook_secret
        self.config = config or {}
        self._client = client
        self._owns_client = client is None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def __repr__(self) -> str:  # never leak the token through logging or tracebacks
        return f"<{type(self).__name__}>"

    def _require_secret(self) -> str:
        if not self._webhook_secret:
            raise WebhookVerificationError("no webhook secret configured for this integration")
        return self._webhook_secret


def lower_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def first_line(text: str | None) -> str | None:
    return text.strip().splitlines()[0] if text and text.strip() else None
