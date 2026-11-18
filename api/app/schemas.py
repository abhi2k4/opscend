"""API response and request models.

These mirror `web/lib/types.ts` field for field: that file is the contract.
All timestamps serialize as ISO-8601 UTC strings and all ids are strings.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Capability(StrEnum):
    LIST_SERVICES = "LIST_SERVICES"
    LIST_DEPLOYS = "LIST_DEPLOYS"
    BUILD_LOGS = "BUILD_LOGS"
    RUNTIME_LOGS = "RUNTIME_LOGS"
    WEBHOOKS = "WEBHOOKS"
    COMMITS = "COMMITS"
    COMMIT_DIFF = "COMMIT_DIFF"


DeployStatus = Literal["queued", "building", "ready", "failed", "canceled"]
LogLevel = Literal["debug", "info", "warn", "error"]
LogKind = Literal["build", "runtime"]
HealthState = Literal["up", "down", "unknown"]
Confidence = Literal["low", "medium", "high"]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ───────────────────────────── system / auth


class AIInfo(Schema):
    provider: str
    model: str
    configured: bool


class SystemInfo(Schema):
    version: str
    demo_mode: bool
    ai: AIInfo
    queue: Literal["arq", "inline"]
    database: Literal["postgresql", "sqlite"]


class User(Schema):
    id: str
    email: str


class LoginRequest(BaseModel):
    email: str
    password: str


# ───────────────────────────── integrations


class ConfigField(Schema):
    key: str
    label: str
    required: bool
    placeholder: str


class ProviderManifest(Schema):
    provider: str
    name: str
    description: str
    availability: Literal["available", "planned"]
    capabilities: list[Capability]
    token_label: str
    token_help_url: str | None
    config_fields: list[ConfigField]
    webhook_path: str | None


class Integration(Schema):
    id: str
    provider: str
    account_name: str | None
    status: Literal["connected", "error", "pending"]
    status_detail: str | None
    capabilities: list[Capability]
    token_hint: str
    is_demo: bool
    last_synced_at: datetime | None
    created_at: datetime


class IntegrationCreate(BaseModel):
    provider: str
    token: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


# ───────────────────────────── core entities


class HealthPoint(Schema):
    status_code: int | None
    latency_ms: int | None
    ok: bool
    checked_at: datetime


class Service(Schema):
    id: str
    integration_id: str
    provider: str
    external_id: str
    name: str
    repo: str | None
    health_url: str | None
    health: HealthState
    latency_ms: int | None
    health_history: list[HealthPoint]
    last_deploy_status: DeployStatus | None
    last_deploy_at: datetime | None


class Commit(Schema):
    repo: str
    sha: str
    message: str
    author: str
    committed_at: datetime
    url: str | None


class Deployment(Schema):
    id: str
    service_id: str
    service_name: str
    provider: str
    external_id: str
    status: DeployStatus
    commit_sha: str | None
    commit_message: str | None
    commit_author: str | None
    branch: str | None
    environment: str | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    url: str | None


class DeploymentDetail(Deployment):
    service: Service
    commit: Commit | None
    capabilities: list[Capability]
    incident_id: str | None
    investigation_id: str | None


class LogLine(Schema):
    id: str
    ts: datetime
    level: LogLevel
    message: str
    kind: LogKind


class DiffFile(Schema):
    filename: str
    status: Literal["added", "modified", "removed", "renamed"]
    additions: int
    deletions: int
    patch: str | None


class CommitDiff(Schema):
    repo: str
    sha: str
    message: str
    author: str
    files: list[DiffFile]


class Incident(Schema):
    id: str
    service_id: str
    service_name: str
    provider: str
    trigger: Literal["deploy_failed", "health_check_failed"]
    status: Literal["open", "resolved"]
    title: str
    deployment_id: str | None
    investigation_id: str | None
    opened_at: datetime
    resolved_at: datetime | None


# ───────────────────────────── timeline


class DeploymentItem(Schema):
    kind: Literal["deployment"] = "deployment"
    id: str
    at: datetime
    provider: str
    deployment: Deployment


class CommitItem(Schema):
    kind: Literal["commit"] = "commit"
    id: str
    at: datetime
    provider: Literal["github"] = "github"
    commit: Commit


class IncidentItem(Schema):
    kind: Literal["incident"] = "incident"
    id: str
    at: datetime
    provider: str
    incident: Incident


TimelineItem = Annotated[DeploymentItem | CommitItem | IncidentItem, Field(discriminator="kind")]


# ───────────────────────────── overview


class OverviewStats(Schema):
    services: int
    services_down: int
    deploys_24h: int
    failed_24h: int
    open_incidents: int
    investigations: int


class ActivityBucket(Schema):
    hour: datetime
    ready: int
    failed: int


class Overview(Schema):
    stats: OverviewStats
    services: list[Service]
    incidents: list[Incident]
    deployments: list[Deployment]
    activity: list[ActivityBucket]


# ───────────────────────────── investigator


class LogEvidence(Schema):
    type: Literal["log"] = "log"
    ref: str
    deployment_id: str
    quote: str


class CommitEvidence(Schema):
    type: Literal["commit"] = "commit"
    ref: str
    quote: str


class DeployEvidence(Schema):
    type: Literal["deploy"] = "deploy"
    ref: str
    quote: str


class HealthEvidence(Schema):
    type: Literal["health"] = "health"
    ref: str
    quote: str


EvidenceRef = Annotated[
    LogEvidence | CommitEvidence | DeployEvidence | HealthEvidence, Field(discriminator="type")
]


class InvestigationReport(Schema):
    inconclusive: bool
    likely_cause: str
    confidence: Confidence
    summary: str
    culprit_commit_sha: str | None
    evidence: list[EvidenceRef]
    suggested_fix: str | None
    missing: str | None


class InvestigationStep(Schema):
    id: str
    index: int
    type: Literal["llm", "tool", "report"]
    name: str
    input: dict[str, Any] | None
    output_summary: str | None
    started_at: datetime
    duration_ms: int | None
    tokens: int | None
    status: Literal["running", "ok", "error"]


class Investigation(Schema):
    id: str
    deployment_id: str | None
    incident_id: str | None
    service_name: str | None
    status: Literal["queued", "running", "completed", "failed"]
    error: str | None
    model: str
    tokens_used: int
    duration_ms: int | None
    created_at: datetime
    finished_at: datetime | None
    report: InvestigationReport | None
    steps: list[InvestigationStep]


# ───────────────────────────── developer console


class RawEvent(Schema):
    id: str
    provider: str
    source: Literal["webhook", "poll", "demo"]
    event_type: str
    dedup_key: str
    received_at: datetime
    processed_at: datetime | None
    duplicate: bool
    payload: Any


class DemoScenario(Schema):
    id: str
    title: str
    description: str


class DemoBreakRequest(BaseModel):
    scenario_id: str


class DemoBreakResult(Schema):
    deployment_id: str
    incident_id: str


class Ok(BaseModel):
    status: Literal["ok"] = "ok"


class Accepted(BaseModel):
    """Webhook acknowledgement: how many events were stored and how many were duplicates."""

    accepted: int
    duplicates: int
