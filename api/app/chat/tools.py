"""The chat assistant's tools: the investigator's five plus broad, filtered queries.

Like the investigator's, every tool here is read-only. Each id a tool shows the model
goes into the `ChatLedger`, and an answer may only cite ids found there.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.sql import Select

from app.core.time import duration_ms, utcnow
from app.investigator.tools import (
    MAX_LINE_CHARS,
    TOOL_SPECS,
    EvidenceLedger,
    InvestigatorTools,
    _function,
    untrusted,
)
from app.models import Commit, Deployment, HealthCheck, Incident, LogLine, Service

DEFAULT_HOURS = 24 * 7
MAX_HOURS = 24 * 90
MAX_ROWS = 50
MAX_LOG_HITS = 40
MAX_STATS_DEPLOYS = 5000
MAX_SERVICES = 100

# Deploy statuses (see `DeployStatus` in app/schemas.py).
FINISHED_BAD = "failed"
FINISHED_GOOD = "ready"


@dataclass
class ChatLedger(EvidenceLedger):
    """The investigator's ledger plus the incidents shown."""

    incidents: set[str] = field(default_factory=set)

    def seed(self, citation: dict[str, Any]) -> None:
        """Allow an id cited (and verified) earlier in the same conversation."""
        kind, ref = citation.get("type"), citation.get("ref") or ""
        if kind == "deploy":
            self.deploys[ref] = ref
        elif kind == "log" and citation.get("deployment_id"):
            self.logs[ref] = (citation["deployment_id"], citation.get("detail") or "")
        elif kind == "commit":
            self.commits.add(ref)
        elif kind == "incident":
            self.incidents.add(ref)
        elif kind == "service":
            self.services.add(ref)


_SERVICE = {"type": "string", "description": "Service name or service_id; omit for all services"}
_HOURS = {
    "type": "integer",
    "description": f"How far back to look, in hours (default {DEFAULT_HOURS}, max {MAX_HOURS})",
}
_LIMIT = {"type": "integer", "description": f"Max rows (default 20, max {MAX_ROWS})"}

CHAT_TOOL_SPECS: list[dict[str, Any]] = [
    *TOOL_SPECS,
    _function(
        "list_services",
        "Every service with its provider, repo, latest deploy, latest health check and "
        "whether it has an open incident.",
        {},
        [],
    ),
    _function(
        "search_deployments",
        "Deployments matching filters, newest first.",
        {
            "service": _SERVICE,
            "provider": {"type": "string", "enum": ["vercel", "railway", "github"]},
            "status": {
                "type": "string",
                "enum": ["queued", "building", "ready", "failed", "canceled"],
            },
            "branch": {"type": "string"},
            "environment": {"type": "string", "description": "e.g. production, preview"},
            "since_hours": _HOURS,
            "limit": _LIMIT,
        },
        [],
    ),
    _function(
        "search_logs",
        "Case-insensitive text search over stored build and runtime log lines of all "
        "deployments (logs are stored once a deploy has finished and its logs were read). "
        "Each line starts with its id in brackets; cite those ids.",
        {
            "query": {"type": "string", "description": "Text to find, e.g. ECONNREFUSED"},
            "service": _SERVICE,
            "kind": {"type": "string", "enum": ["build", "runtime"]},
            "level": {"type": "string", "enum": ["error", "warn", "info", "debug"]},
            "since_hours": _HOURS,
        },
        ["query"],
    ),
    _function(
        "list_incidents",
        "Incidents (failed deploys, failing health checks), newest first.",
        {
            "service": _SERVICE,
            "status": {"type": "string", "enum": ["open", "resolved"]},
            "since_hours": _HOURS,
        },
        [],
    ),
    _function(
        "list_commits",
        "Commits seen on GitHub, newest first.",
        {
            "repo": {"type": "string", "description": "owner/name, or part of it"},
            "author": {"type": "string", "description": "Part of the author name"},
            "query": {"type": "string", "description": "Text in the commit message"},
            "since_hours": _HOURS,
            "limit": _LIMIT,
        },
        [],
    ),
    _function(
        "deploy_stats",
        "Per-service deploy counts by status, failure rate, average build time and mean "
        "time to recovery (failed deploy → next successful one) over a time window. "
        "Omit service to get every service in one call.",
        {"service": _SERVICE, "since_hours": _HOURS},
        [],
    ),
]


def _int(value: str | None, default: int, maximum: int) -> int:
    try:
        number = int(float(value)) if value not in (None, "") else default
    except ValueError:
        number = default
    return max(1, min(number, maximum))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _escape_like(text: str) -> str:
    return text.replace("/", "//").replace("%", "/%").replace("_", "/_")


def _first_line(text: str | None, limit: int = 120) -> str:
    return (text or "").strip().splitlines()[0][:limit] if (text or "").strip() else ""


class ChatTools(InvestigatorTools):
    _names = frozenset(spec["function"]["name"] for spec in CHAT_TOOL_SPECS)
    ledger: ChatLedger

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        # Models send null or "" for filters they do not want; treat those as absent.
        present = {k: v for k, v in arguments.items() if v is not None and v != ""}
        return await super().call(name, present)

    # ── helpers

    async def _services(self, ref: str | None) -> list[Service] | str:
        """Services matching an id or name; an error string when nothing matches."""
        query = select(Service).order_by(Service.name).limit(MAX_SERVICES)
        if not ref:
            return list((await self._session.scalars(query)).all())
        ref = ref.strip()
        exact = (
            await self._session.scalars(
                query.where(or_(Service.id == ref, func.lower(Service.name) == ref.lower()))
            )
        ).all()
        if exact:
            return list(exact)
        partial = (
            await self._session.scalars(
                query.where(Service.name.ilike(f"%{_escape_like(ref)}%", escape="/"))
            )
        ).all()
        if partial:
            return list(partial)
        known = (await self._session.scalars(select(Service.name).limit(MAX_SERVICES))).all()
        return f"error: no service matches '{ref}'. Known services: {', '.join(known) or 'none'}"

    def _since(self, since_hours: str | None) -> datetime:
        return utcnow() - timedelta(hours=_int(since_hours, DEFAULT_HOURS, MAX_HOURS))

    async def _scoped(self, query: Select, column, service: str | None) -> Select | str:  # noqa: ANN001
        if not service:
            return query
        services = await self._services(service)
        if isinstance(services, str):
            return services
        return query.where(column.in_([s.id for s in services]))

    # ── tools

    async def list_services(self) -> str:
        services = await self._services(None)
        assert not isinstance(services, str)
        if not services:
            return "No services are connected yet."
        open_incidents = set(
            (
                await self._session.scalars(
                    select(Incident.service_id).where(Incident.status == "open")
                )
            ).all()
        )
        rows = []
        for service in services:
            self.ledger.services.add(service.id)
            latest = await self._session.scalar(
                select(Deployment)
                .where(Deployment.service_id == service.id)
                .order_by(Deployment.started_at.desc())
                .limit(1)
            )
            check = await self._session.scalar(
                select(HealthCheck)
                .where(HealthCheck.service_id == service.id)
                .order_by(HealthCheck.checked_at.desc())
                .limit(1)
            )
            if latest is not None:
                self.ledger.add_deployment(latest)
            rows.append(
                {
                    "service_id": service.id,
                    "name": service.name,
                    "provider": service.provider,
                    "repo": service.repo,
                    "latest_deploy": {
                        "deployment_id": latest.id,
                        "status": latest.status,
                        "started_at": _iso(latest.started_at),
                    }
                    if latest
                    else None,
                    "health": (
                        {"ok": check.ok, "checked_at": _iso(check.checked_at)} if check else None
                    ),
                    "open_incident": service.id in open_incidents,
                }
            )
        return json.dumps(rows, indent=1)

    async def search_deployments(
        self,
        service: str | None = None,
        provider: str | None = None,
        status: str | None = None,
        branch: str | None = None,
        environment: str | None = None,
        since_hours: str | None = None,
        limit: str | None = None,
    ) -> str:
        query = select(Deployment).where(Deployment.started_at >= self._since(since_hours))
        if provider:
            query = query.where(Deployment.provider == provider.lower())
        if status:
            query = query.where(Deployment.status == status.lower())
        if branch:
            query = query.where(Deployment.branch == branch)
        if environment:
            query = query.where(func.lower(Deployment.environment) == environment.lower())
        scoped = await self._scoped(query, Deployment.service_id, service)
        if isinstance(scoped, str):
            return scoped
        rows = (
            await self._session.scalars(
                scoped.order_by(Deployment.started_at.desc()).limit(_int(limit, 20, MAX_ROWS))
            )
        ).all()
        if not rows:
            return "No deployments match those filters."
        described = [self._describe(d) for d in rows]
        messages = "\n".join(
            f"{d.id}: {_first_line(d.commit_message)}" for d in rows if d.commit_message
        )
        text = f"{len(rows)} deployment(s), newest first:\n" + json.dumps(described, indent=1)
        if messages:
            text += "\n" + untrusted("commit messages", messages)
        return text

    async def search_logs(
        self,
        query: str = "",
        service: str | None = None,
        kind: str | None = None,
        level: str | None = None,
        since_hours: str | None = None,
    ) -> str:
        needle = query.strip()
        if len(needle) < 2:
            return "error: query must be at least 2 characters"
        stmt = (
            select(LogLine, Deployment)
            .join(Deployment, Deployment.id == LogLine.deployment_id)
            .where(
                LogLine.ts >= self._since(since_hours),
                LogLine.message.ilike(f"%{_escape_like(needle)}%", escape="/"),
            )
        )
        if kind in ("build", "runtime"):
            stmt = stmt.where(LogLine.kind == kind)
        if level:
            stmt = stmt.where(LogLine.level == level.lower())
        scoped = await self._scoped(stmt, Deployment.service_id, service)
        if isinstance(scoped, str):
            return scoped
        hits = (
            await self._session.execute(scoped.order_by(LogLine.ts.desc()).limit(MAX_LOG_HITS))
        ).all()
        if not hits:
            return f"No stored log lines contain '{needle}' in that window."
        by_deploy: dict[str, list[str]] = {}
        headers: dict[str, str] = {}
        for line, deployment in hits:
            self.ledger.add_deployment(deployment)
            self.ledger.logs[line.id] = (deployment.id, line.message)
            headers[deployment.id] = (
                f"deployment {deployment.id} ({deployment.service.name}, {deployment.status}, "
                f"{deployment.started_at:%Y-%m-%d %H:%M})"
            )
            by_deploy.setdefault(deployment.id, []).append(
                f"[{line.id}] {line.ts:%Y-%m-%d %H:%M:%S} {line.kind} {line.level.upper():5} "
                f"{line.message[:MAX_LINE_CHARS]}"
            )
        body = "\n\n".join(f"{headers[d]}\n" + "\n".join(lines) for d, lines in by_deploy.items())
        more = " (limit reached, narrow the search)" if len(hits) == MAX_LOG_HITS else ""
        return (
            f"{len(hits)} matching line(s) across {len(by_deploy)} deployment(s){more}:\n"
            + untrusted("log search results", body)
        )

    async def list_incidents(
        self,
        service: str | None = None,
        status: str | None = None,
        since_hours: str | None = None,
    ) -> str:
        query = select(Incident).where(Incident.opened_at >= self._since(since_hours))
        if status in ("open", "resolved"):
            query = query.where(Incident.status == status)
        scoped = await self._scoped(query, Incident.service_id, service)
        if isinstance(scoped, str):
            return scoped
        rows = (
            await self._session.scalars(scoped.order_by(Incident.opened_at.desc()).limit(MAX_ROWS))
        ).all()
        if not rows:
            return "No incidents match those filters."
        out = []
        for incident in rows:
            self.ledger.incidents.add(incident.id)
            self.ledger.services.add(incident.service_id)
            if incident.deployment_id:
                self.ledger.deploys[incident.deployment_id] = incident.deployment_id
            out.append(
                {
                    "incident_id": incident.id,
                    "service": incident.service.name,
                    "service_id": incident.service_id,
                    "trigger": incident.trigger,
                    "status": incident.status,
                    "title": incident.title,
                    "deployment_id": incident.deployment_id,
                    "opened_at": _iso(incident.opened_at),
                    "resolved_at": _iso(incident.resolved_at),
                    "duration_ms": duration_ms(incident.opened_at, incident.resolved_at),
                }
            )
        return json.dumps(out, indent=1)

    async def list_commits(
        self,
        repo: str | None = None,
        author: str | None = None,
        query: str | None = None,
        since_hours: str | None = None,
        limit: str | None = None,
    ) -> str:
        stmt = select(Commit).where(Commit.committed_at >= self._since(since_hours))
        if repo:
            stmt = stmt.where(Commit.repo.ilike(f"%{_escape_like(repo.strip())}%", escape="/"))
        if author:
            stmt = stmt.where(Commit.author.ilike(f"%{_escape_like(author.strip())}%", escape="/"))
        if query:
            stmt = stmt.where(Commit.message.ilike(f"%{_escape_like(query.strip())}%", escape="/"))
        rows = (
            await self._session.scalars(
                stmt.order_by(Commit.committed_at.desc()).limit(_int(limit, 20, MAX_ROWS))
            )
        ).all()
        if not rows:
            return "No commits match those filters."
        lines = []
        for commit in rows:
            self.ledger.commits.add(commit.sha)
            lines.append(
                f"{commit.sha} {commit.repo} {commit.committed_at:%Y-%m-%d %H:%M} "
                f"{commit.author}: {_first_line(commit.message, 160)}"
            )
        return f"{len(rows)} commit(s), newest first:\n" + untrusted("commits", "\n".join(lines))

    async def deploy_stats(self, service: str | None = None, since_hours: str | None = None) -> str:
        hours = _int(since_hours, DEFAULT_HOURS, MAX_HOURS)
        query = select(Deployment).where(Deployment.started_at >= utcnow() - timedelta(hours=hours))
        scoped = await self._scoped(query, Deployment.service_id, service)
        if isinstance(scoped, str):
            return scoped
        rows = (
            await self._session.scalars(
                scoped.order_by(Deployment.started_at).limit(MAX_STATS_DEPLOYS)
            )
        ).all()
        if not rows:
            return f"No deployments in the last {hours} hours."
        by_service: dict[str, list[Deployment]] = {}
        for deployment in rows:
            by_service.setdefault(deployment.service_id, []).append(deployment)
        stats = [_service_stats(deploys, hours) for deploys in by_service.values()]
        for item in stats:
            self.ledger.services.add(item["service_id"])
            if item["last_failure"]:
                self.ledger.deploys[item["last_failure"]["deployment_id"]] = item["last_failure"][
                    "deployment_id"
                ]
        stats.sort(key=lambda item: item["failed"], reverse=True)
        truncated = len(rows) == MAX_STATS_DEPLOYS
        header = f"Deploy stats over the last {hours} hours"
        header += f" (first {MAX_STATS_DEPLOYS} deploys only)" if truncated else ""
        return f"{header}, most failures first:\n" + json.dumps(stats, indent=1)


def _service_stats(deploys: list[Deployment], hours: int) -> dict[str, Any]:
    """Counts and timings for one service's deploys, given oldest first."""
    counts: dict[str, int] = {}
    for deployment in deploys:
        counts[deployment.status] = counts.get(deployment.status, 0) + 1
    good, bad = counts.get(FINISHED_GOOD, 0), counts.get(FINISHED_BAD, 0)
    builds = [
        duration_ms(d.started_at, d.finished_at)
        for d in deploys
        if d.status == FINISHED_GOOD and d.finished_at
    ]
    recoveries = []
    last_failure: Deployment | None = None
    for index, deployment in enumerate(deploys):
        if deployment.status != FINISHED_BAD:
            continue
        last_failure = deployment
        fixed = next((d for d in deploys[index + 1 :] if d.status == FINISHED_GOOD), None)
        if fixed is not None and fixed.finished_at:
            recoveries.append((fixed.finished_at - deployment.started_at).total_seconds())
    service = deploys[0].service
    return {
        "service": service.name,
        "service_id": service.id,
        "provider": service.provider,
        "total": len(deploys),
        "by_status": counts,
        "failed": bad,
        "failure_rate": round(bad / (good + bad), 3) if good + bad else None,
        "deploys_per_day": round(len(deploys) / (hours / 24), 2),
        "avg_build_seconds": round(mean(b for b in builds if b) / 1000, 1) if any(builds) else None,
        "mean_time_to_recovery_minutes": round(mean(recoveries) / 60, 1) if recoveries else None,
        "last_failure": {
            "deployment_id": last_failure.id,
            "started_at": _iso(last_failure.started_at),
        }
        if last_failure
        else None,
    }
