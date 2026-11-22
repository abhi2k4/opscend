"""The investigator's tools. All five are read-only: this class has no method that
writes to the database or to a provider, and provider tokens never reach its output.

Every id a tool shows the model is recorded in the `EvidenceLedger`; the final
report may only cite ids found there.
"""

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import duration_ms, utcnow
from app.integrations.base import ProviderError
from app.models import Deployment, HealthCheck, LogLine, Service
from app.services import diffs, logs
from app.services.presenters import find_commit

MAX_LOG_LINES = 60
MAX_LINE_CHARS = 300
MAX_PATCH_CHARS = 1800
MAX_OUTPUT_CHARS = 6000
RECENT_WINDOW = timedelta(hours=2)
UNTRUSTED_CLOSE = "</untrusted_data>"


@dataclass
class EvidenceLedger:
    """Everything the model has actually been shown, keyed the way reports cite it."""

    logs: dict[str, tuple[str, str]] = field(default_factory=dict)  # log id → (deployment id, text)
    commits: set[str] = field(default_factory=set)  # full shas
    deploys: dict[str, str] = field(default_factory=dict)  # deployment id or external id → id
    services: set[str] = field(default_factory=set)  # service ids with health history shown

    def add_deployment(self, deployment: Deployment) -> None:
        self.deploys[deployment.id] = deployment.id
        self.deploys[deployment.external_id] = deployment.id
        if deployment.commit_sha:
            self.commits.add(deployment.commit_sha)

    def resolve_commit(self, ref: str) -> str | None:
        ref = ref.strip().lower()
        if len(ref) < 7:
            return None
        return next((sha for sha in sorted(self.commits) if sha.lower().startswith(ref)), None)


def untrusted(label: str, text: str) -> str:
    """Wrap provider-supplied text so the model treats it as data, never as instructions."""
    safe = text.replace(UNTRUSTED_CLOSE, "<\\/untrusted_data>")
    return f'<untrusted_data source="{label}">\n{safe}\n{UNTRUSTED_CLOSE}'


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """Let an optional parameter be sent as null, which models often do instead of omitting it."""
    out = {**schema, "type": [schema["type"], "null"]}
    if "enum" in schema:
        out["enum"] = [*schema["enum"], None]
    return out


def _function(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict:
    # Providers validate tool calls against this schema and reject the whole request on a
    # mismatch, so optional parameters must accept the null a model sends for "not set".
    properties = {
        key: schema if key in required else _nullable(schema) for key, schema in properties.items()
    }
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_DEPLOYMENT_ID = {"type": "string", "description": "Opscend deployment id"}

TOOL_SPECS: list[dict[str, Any]] = [
    _function(
        "get_deployment",
        "Status, commit, branch, timing and service of one deployment.",
        {"deployment_id": _DEPLOYMENT_ID},
        ["deployment_id"],
    ),
    _function(
        "get_logs",
        "Build or runtime log lines of a deployment. Each line starts with its id in brackets; "
        "cite those ids as evidence.",
        {
            "deployment_id": _DEPLOYMENT_ID,
            "kind": {"type": "string", "enum": ["build", "runtime"]},
        },
        ["deployment_id", "kind"],
    ),
    _function(
        "list_recent_deploys",
        "Every deployment on every provider in the last 2 hours, newest first.",
        {},
        [],
    ),
    _function(
        "get_commit_diff",
        "Changed files and patches of a commit.",
        {"sha": {"type": "string", "description": "Commit sha (full or 7+ characters)"}},
        ["sha"],
    ),
    _function(
        "get_health_history",
        "Recent uptime checks of a service.",
        {"service_id": {"type": "string", "description": "Opscend service id"}},
        ["service_id"],
    ),
]

TOOL_NAMES = frozenset(spec["function"]["name"] for spec in TOOL_SPECS)


class InvestigatorTools:
    # The tools the model may call; subclasses extend this (see app/chat/tools.py).
    _names: frozenset[str] = TOOL_NAMES

    def __init__(self, session: AsyncSession, ledger: EvidenceLedger) -> None:
        self._session = session
        self.ledger = ledger

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        """Run one tool by name. Errors come back as text for the model to read."""
        if name not in self._names:
            return f"error: unknown tool '{name}'. Available: {', '.join(sorted(self._names))}"
        try:
            output = await getattr(self, name)(**{k: str(v) for k, v in arguments.items()})
        except TypeError:
            return f"error: invalid arguments for {name}"
        except ProviderError as exc:
            return f"error: provider call failed: {exc}"
        if len(output) > MAX_OUTPUT_CHARS:
            cut = output[:MAX_OUTPUT_CHARS]
            closing = (
                f"\n{UNTRUSTED_CLOSE}"
                if cut.count("<untrusted_data") > cut.count(UNTRUSTED_CLOSE)
                else ""
            )
            output = f"{cut}\n… (output truncated){closing}"
        return output

    async def _deployment(self, deployment_id: str) -> Deployment | None:
        return await self._session.scalar(
            select(Deployment)
            .where(or_(Deployment.id == deployment_id, Deployment.external_id == deployment_id))
            .limit(1)
        )

    def _describe(self, deployment: Deployment) -> dict[str, Any]:
        self.ledger.add_deployment(deployment)
        return {
            "deployment_id": deployment.id,
            "provider": deployment.provider,
            "service": deployment.service.name,
            "service_id": deployment.service_id,
            "status": deployment.status,
            "environment": deployment.environment,
            "branch": deployment.branch,
            "commit_sha": deployment.commit_sha,
            "started_at": deployment.started_at.isoformat(),
            "finished_at": deployment.finished_at.isoformat() if deployment.finished_at else None,
            "duration_ms": duration_ms(deployment.started_at, deployment.finished_at),
        }

    async def get_deployment(self, deployment_id: str) -> str:
        deployment = await self._deployment(deployment_id)
        if deployment is None:
            return f"error: no deployment with id {deployment_id}"
        info = self._describe(deployment)
        info["repo"] = deployment.service.repo
        commit = await find_commit(self._session, deployment.commit_sha)
        text = json.dumps(info, indent=1)
        message = commit.message if commit else deployment.commit_message
        if message:
            author = commit.author if commit else deployment.commit_author
            text += "\n" + untrusted("commit message", f"{message}\n(author: {author})")
        return text

    async def get_logs(self, deployment_id: str, kind: str | None = "build") -> str:
        kind = kind or "build"
        if kind not in ("build", "runtime"):
            return "error: kind must be 'build' or 'runtime'"
        deployment = await self._deployment(deployment_id)
        if deployment is None:
            return f"error: no deployment with id {deployment_id}"
        self.ledger.add_deployment(deployment)
        lines = await logs.get_logs(self._session, deployment, kind)
        if not lines:
            return f"No {kind} logs are available for deployment {deployment.id}."
        shown = _select_lines(lines)
        rendered = []
        for line in shown:
            self.ledger.logs[line.id] = (deployment.id, line.message)
            message = line.message[:MAX_LINE_CHARS]
            rendered.append(f"[{line.id}] {line.ts:%H:%M:%S} {line.level.upper():5} {message}")
        header = f"{kind} logs for deployment {deployment.id}: showing {len(shown)} of {len(lines)}"
        if len(shown) < len(lines):
            header += " (errors, warnings and the final lines are kept)"
        return f"{header}\n" + untrusted(f"{kind} logs", "\n".join(rendered))

    async def list_recent_deploys(self) -> str:
        deployments = (
            await self._session.scalars(
                select(Deployment)
                .where(Deployment.started_at >= utcnow() - RECENT_WINDOW)
                .order_by(Deployment.started_at.desc())
                .limit(40)
            )
        ).all()
        if not deployments:
            return "No deployments in the last 2 hours."
        return json.dumps([self._describe(d) for d in deployments], indent=1)

    async def get_commit_diff(self, sha: str) -> str:
        deployment = await self._session.scalar(
            select(Deployment)
            .where(Deployment.commit_sha.startswith(sha, autoescape=True))
            .limit(1)
        )
        repo = deployment.service.repo if deployment else None
        diff = await diffs.get_commit_diff(self._session, sha, repo)
        if diff is None:
            return f"No diff is available for commit {sha}."
        self.ledger.commits.add(diff.sha)
        parts = [f"commit {diff.sha} in {diff.repo}, {len(diff.files)} file(s) changed"]
        body = [f"message: {diff.message}", f"author: {diff.author}"]
        for item in diff.files:
            body.append(
                f"\n--- {item.filename} ({item.status}, +{item.additions} -{item.deletions})"
            )
            patch = item.patch or "(no text patch)"
            if len(patch) > MAX_PATCH_CHARS:
                patch = patch[:MAX_PATCH_CHARS] + "\n… (patch truncated)"
            body.append(patch)
        parts.append(untrusted("commit diff", "\n".join(body)))
        return "\n".join(parts)

    async def get_health_history(self, service_id: str) -> str:
        service = await self._session.scalar(
            select(Service)
            .where(or_(Service.id == service_id, Service.name == service_id))
            .limit(1)
        )
        if service is None:
            return f"error: no service with id {service_id}"
        checks = (
            await self._session.scalars(
                select(HealthCheck)
                .where(HealthCheck.service_id == service.id)
                .order_by(HealthCheck.checked_at.desc())
                .limit(30)
            )
        ).all()
        if not checks:
            return f"No health checks recorded for service {service.name} ({service.id})."
        self.ledger.services.add(service.id)
        failed = sum(1 for check in checks if not check.ok)
        rows = [
            f"{check.checked_at:%Y-%m-%d %H:%M:%S} "
            f"{'ok  ' if check.ok else 'FAIL'} status={check.status_code} "
            f"latency_ms={check.latency_ms}"
            for check in checks
        ]
        return (
            f"service {service.name} (service_id {service.id}), url {service.health_url}: "
            f"{failed} of {len(checks)} recent checks failed. Newest first:\n" + "\n".join(rows)
        )


def _select_lines(lines: list[LogLine]) -> list[LogLine]:
    """Keep the lines most likely to explain a failure when there are too many."""
    if len(lines) <= MAX_LOG_LINES:
        return lines
    keep: set[int] = set(range(len(lines) - 20, len(lines)))
    for index, line in enumerate(lines):
        if line.level in ("error", "warn"):
            keep.update(range(max(0, index - 2), min(len(lines), index + 3)))
    chosen = sorted(keep)
    if len(chosen) > MAX_LOG_LINES:
        chosen = chosen[-MAX_LOG_LINES:]
    return [lines[index] for index in chosen]
