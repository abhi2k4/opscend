"""The chat assistant's tools: the investigator's five plus broad, filtered queries.

Like the investigator's, every tool here is read-only. Each id a tool shows the model
goes into the `ChatLedger`, and an answer may only cite ids found there.
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.sql import Select

from app.core.time import duration_ms, ensure_utc, utcnow
from app.investigator.tools import (
    MAX_LINE_CHARS,
    TOOL_SPECS,
    EvidenceLedger,
    InvestigatorTools,
    _function,
    untrusted,
)
from app.models import (
    Commit,
    Deployment,
    HealthCheck,
    Incident,
    Investigation,
    LogLine,
    Service,
)
from app.services.changes import get_changes

DEFAULT_HOURS = 24 * 7
MAX_HOURS = 24 * 90
MAX_ROWS = 50
MAX_LOG_HITS = 40
MAX_STATS_DEPLOYS = 5000
MAX_SERVICES = 100
MAX_CHART_BARS = 12
MAX_TREND_BUCKETS = 92
MAX_HEALTH_CHECKS = 20000
MAX_CHANGED_FILES = 40
MAX_CHANGED_COMMITS = 30

# Deploy statuses (see `DeployStatus` in app/schemas.py).
FINISHED_BAD = "failed"
FINISHED_GOOD = "ready"


@dataclass
class ChatLedger(EvidenceLedger):
    """The investigator's ledger plus the charts built this turn."""

    # Charts the tools built this turn, by id. Only these may appear in the answer.
    charts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_chart(
        self,
        kind: str,
        title: str,
        unit: str,
        categories: list[str],
        series: list[tuple[str, str, list[float | None]]],
        subtitle: str | None = None,
    ) -> str:
        """Register a chart and return the line that tells the model how to show it.

        Returns "" when there is too little to draw (a chart of one point says nothing).
        """
        kept = [(name, tone, values) for name, tone, values in series if any(values)]
        if len(categories) < 2 or not kept:
            return ""
        digest = hashlib.sha1(f"{title}|{categories}".encode()).hexdigest()[:6]
        chart_id = f"chart_{len(self.charts) + 1}{digest}"
        self.charts[chart_id] = {
            "id": chart_id,
            "kind": kind,
            "title": title,
            "subtitle": subtitle,
            "unit": unit,
            "categories": categories,
            "series": [{"name": n, "tone": t, "values": v} for n, t, v in kept],
        }
        return (
            f'\nChart ready: "{title}". To show it, put [chart:{chart_id}] on its own line '
            "in your answer."
        )

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
        elif kind == "investigation":
            self.investigations.add(ref)
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
            "provider": {
                "type": "string",
                "description": "vercel, railway, render, fly, netlify, cloudflare or aws",
            },
            "status": {
                "type": "string",
                "enum": ["queued", "building", "ready", "failed", "canceled"],
            },
            "branch": {"type": "string"},
            "environment": {"type": "string", "description": "e.g. production, preview"},
            "commit_sha": {
                "type": "string",
                "description": "Full commit sha or its first 7+ characters: which deploys "
                "shipped this commit",
            },
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
        "deploy_trend",
        "Deploy counts over time (ready, failed, other), bucketed by hour for windows up "
        "to 48 hours and by day beyond that. Use it for questions about trends, activity "
        "or how deploys have been going. Comes with a chart.",
        {"service": _SERVICE, "since_hours": _HOURS},
        [],
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
    _function(
        "health_stats",
        "Per-service uptime from health checks over a time window: uptime percentage, "
        "p50/p95 response time, number of outages, the longest outage and whether the "
        "service is down now. Use it for uptime, availability or latency questions. "
        "Omit service to get every service in one call. Comes with a chart.",
        {"service": _SERVICE, "since_hours": _HOURS},
        [],
    ),
    _function(
        "list_investigations",
        "Investigation reports the investigator already wrote about failed deploys and "
        "incidents, newest first, with their likely cause, confidence and the reader's "
        "rating (up/down).",
        {
            "service": _SERVICE,
            "status": {"type": "string", "enum": ["queued", "running", "completed", "failed"]},
            "rating": {"type": "string", "enum": ["up", "down"]},
            "since_hours": _HOURS,
        },
        [],
    ),
    _function(
        "get_investigation",
        "The full report of one investigation: likely cause, confidence, summary, culprit "
        "commit, cited evidence, suggested fix and the reader's rating. Pass "
        "investigation_id, or deployment_id to get the latest report on that deployment. "
        "Check this before digging through logs to explain a failed deploy.",
        {
            "investigation_id": {"type": "string"},
            "deployment_id": {"type": "string"},
        },
        [],
    ),
    _function(
        "changes_since_last_good",
        "What changed between a deployment and the last successful deploy of the same "
        "service: the commits and files in between (files the failure points at are "
        "marked suspect), how many deploys failed in between and whether the commit was "
        "the same. Use it for 'what changed' questions about a deploy.",
        {"deployment_id": {"type": "string"}},
        ["deployment_id"],
    ),
]


def _int(value: str | None, default: int, maximum: int) -> int:
    try:
        number = int(float(value)) if value not in (None, "") else default
    except ValueError:
        number = default
    return max(1, min(number, maximum))


def _more(shown: int, limit: int) -> str:
    """Tell the model a result was cut off, so it does not treat it as complete."""
    if shown < limit:
        return ""
    return f" (showing the first {limit}; there may be more, narrow the filters)"


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
        query = (
            select(Service)
            .where(Service.monitored.is_(True))
            .order_by(Service.name)
            .limit(MAX_SERVICES)
        )
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
        known = (
            await self._session.scalars(
                select(Service.name).where(Service.monitored.is_(True)).limit(MAX_SERVICES)
            )
        ).all()
        return f"error: no service matches '{ref}'. Known services: {', '.join(known) or 'none'}"

    def _since(self, since_hours: str | None) -> datetime:
        return utcnow() - timedelta(hours=_int(since_hours, DEFAULT_HOURS, MAX_HOURS))

    async def _scoped(self, query: Select, column, service: str | None) -> Select | str:  # noqa: ANN001
        if not service:
            # Services with monitoring turned off stay out of every answer.
            return query.where(column.in_(select(Service.id).where(Service.monitored.is_(True))))
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
        commit_sha: str | None = None,
        since_hours: str | None = None,
        limit: str | None = None,
    ) -> str:
        query = select(Deployment).where(Deployment.started_at >= self._since(since_hours))
        if commit_sha:
            sha = commit_sha.strip().lower()
            if len(sha) < 7:
                return "error: commit_sha needs at least 7 characters"
            query = query.where(Deployment.commit_sha.like(f"{_escape_like(sha)}%", escape="/"))
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
        cap = _int(limit, 20, MAX_ROWS)
        rows = (
            await self._session.scalars(scoped.order_by(Deployment.started_at.desc()).limit(cap))
        ).all()
        if not rows:
            return "No deployments match those filters."
        described = [self._describe(d) for d in rows]
        messages = "\n".join(
            f"{d.id}: {_first_line(d.commit_message)}" for d in rows if d.commit_message
        )
        text = f"{len(rows)} deployment(s), newest first{_more(len(rows), cap)}:\n"
        text += json.dumps(described, indent=1)
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
        return f"{len(out)} incident(s), newest first{_more(len(out), MAX_ROWS)}:\n" + json.dumps(
            out, indent=1
        )

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
        cap = _int(limit, 20, MAX_ROWS)
        rows = (
            await self._session.scalars(stmt.order_by(Commit.committed_at.desc()).limit(cap))
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
        header = f"{len(rows)} commit(s), newest first{_more(len(rows), cap)}:\n"
        return header + untrusted("commits", "\n".join(lines))

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
        shown = stats[:MAX_CHART_BARS]
        chart = self.ledger.add_chart(
            "bars",
            "Deploys by service",
            "deploys",
            [item["service"] for item in shown],
            _status_series([item["by_status"] for item in shown]),
            subtitle=_window(hours),
        )
        return f"{header}, most failures first:\n" + json.dumps(stats, indent=1) + chart

    async def deploy_trend(self, service: str | None = None, since_hours: str | None = None) -> str:
        hours = _int(since_hours, DEFAULT_HOURS, MAX_HOURS)
        now = utcnow()
        query = select(Deployment).where(Deployment.started_at >= now - timedelta(hours=hours))
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
        hourly = hours <= 48
        step = timedelta(hours=1) if hourly else timedelta(days=1)
        start = (now - timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0)
        if not hourly:
            start = start.replace(hour=0)
        buckets: list[dict[str, int]] = []
        labels: list[str] = []
        at = start
        while at <= now and len(labels) < MAX_TREND_BUCKETS:
            labels.append(f"{at:%H:00}" if hourly else f"{at:%b} {at.day}")
            buckets.append({})
            at += step
        for deployment in rows:
            index = min(int((ensure_utc(deployment.started_at) - start) / step), len(buckets) - 1)
            if index >= 0:
                bucket = buckets[index]
                bucket[deployment.status] = bucket.get(deployment.status, 0) + 1
        lines = [
            f"{label}: " + (", ".join(f"{n} {status}" for status, n in sorted(b.items())) or "none")
            for label, b in zip(labels, buckets, strict=True)
        ]
        scope = f" for {service}" if service else ""
        chart = self.ledger.add_chart(
            "bars",
            f"Deploys per {'hour' if hourly else 'day'}{scope}",
            "deploys",
            labels,
            _status_series(buckets),
            subtitle=f"{_window(hours)} · UTC",
        )
        return (
            f"Deploys per {'hour' if hourly else 'day'} over the last {hours} hours (UTC), "
            f"{len(rows)} in total:\n" + "\n".join(lines) + chart
        )

    async def health_stats(self, service: str | None = None, since_hours: str | None = None) -> str:
        hours = _int(since_hours, DEFAULT_HOURS, MAX_HOURS)
        query = select(HealthCheck).where(
            HealthCheck.checked_at >= utcnow() - timedelta(hours=hours)
        )
        scoped = await self._scoped(query, HealthCheck.service_id, service)
        if isinstance(scoped, str):
            return scoped
        rows = (
            await self._session.scalars(
                scoped.order_by(HealthCheck.checked_at).limit(MAX_HEALTH_CHECKS)
            )
        ).all()
        if not rows:
            return (
                f"No health checks in the last {hours} hours. Uptime is only measured for "
                "services with a health check URL."
            )
        by_service: dict[str, list[HealthCheck]] = {}
        for check in rows:
            by_service.setdefault(check.service_id, []).append(check)
        names = {
            s.id: s.name
            for s in (
                await self._session.scalars(select(Service).where(Service.id.in_(by_service)))
            ).all()
        }
        stats = []
        for service_id, checks in by_service.items():
            self.ledger.services.add(service_id)
            stats.append(
                {"service": names.get(service_id, service_id), **_health(service_id, checks)}
            )
        stats.sort(key=lambda item: item["uptime_percent"])
        header = f"Health over the last {hours} hours (UTC), least available first"
        if len(rows) == MAX_HEALTH_CHECKS:
            header += f" (first {MAX_HEALTH_CHECKS} checks only)"
        shown = stats[:MAX_CHART_BARS]
        chart = self.ledger.add_chart(
            "bars",
            "Uptime by service",
            "%",
            [item["service"] for item in shown],
            [("Uptime", "ok", [item["uptime_percent"] for item in shown])],
            subtitle=_window(hours),
        )
        return f"{header}:\n" + json.dumps(stats, indent=1) + chart

    async def list_investigations(
        self,
        service: str | None = None,
        status: str | None = None,
        rating: str | None = None,
        since_hours: str | None = None,
    ) -> str:
        query = select(Investigation).where(Investigation.created_at >= self._since(since_hours))
        if status:
            query = query.where(Investigation.status == status.lower())
        if rating in ("up", "down"):
            query = query.where(Investigation.feedback_rating == rating)
        if service:
            services = await self._services(service)
            if isinstance(services, str):
                return services
            query = query.join(Deployment, Deployment.id == Investigation.deployment_id).where(
                Deployment.service_id.in_([s.id for s in services])
            )
        rows = (
            await self._session.scalars(
                query.order_by(Investigation.created_at.desc()).limit(MAX_ROWS)
            )
        ).all()
        if not rows:
            return "No investigations match those filters."
        out, causes = [], []
        for item in rows:
            self.ledger.investigations.add(item.id)
            if item.deployment_id:
                self.ledger.deploys[item.deployment_id] = item.deployment_id
            report = item.report or {}
            out.append(
                {
                    "investigation_id": item.id,
                    "service": item.service_name,
                    "deployment_id": item.deployment_id,
                    "incident_id": item.incident_id,
                    "status": item.status,
                    "confidence": report.get("confidence"),
                    "inconclusive": report.get("inconclusive"),
                    "rating": item.feedback_rating,
                    "created_at": _iso(item.created_at),
                }
            )
            if report.get("likely_cause"):
                causes.append(f"{item.id}: {_first_line(report['likely_cause'], 200)}")
        text = f"{len(out)} investigation(s), newest first{_more(len(out), MAX_ROWS)}:\n"
        text += json.dumps(out, indent=1)
        if causes:
            text += "\nLikely causes:\n" + untrusted("report text", "\n".join(causes))
        return text

    async def get_investigation(
        self, investigation_id: str | None = None, deployment_id: str | None = None
    ) -> str:
        if investigation_id:
            item = await self._session.get(Investigation, investigation_id.strip())
        elif deployment_id:
            target = self.ledger.deploys.get(deployment_id.strip(), deployment_id.strip())
            item = await self._session.scalar(
                select(Investigation)
                .where(Investigation.deployment_id == target)
                .order_by(Investigation.created_at.desc())
                .limit(1)
            )
        else:
            return "error: pass investigation_id or deployment_id"
        if item is None:
            return (
                "No investigation found. One can be started from the deployment's page in Opscend."
            )
        self.ledger.investigations.add(item.id)
        if item.deployment_id:
            self.ledger.deploys[item.deployment_id] = item.deployment_id
        meta: dict[str, Any] = {
            "investigation_id": item.id,
            "service": item.service_name,
            "deployment_id": item.deployment_id,
            "incident_id": item.incident_id,
            "status": item.status,
            "created_at": _iso(item.created_at),
            "rating": item.feedback_rating,
        }
        if item.status != "completed" or not item.report:
            meta["error"] = item.error
            return json.dumps(meta, indent=1) + "\nThis investigation has no report yet."
        report = item.report
        meta.update(
            confidence=report.get("confidence"),
            inconclusive=report.get("inconclusive"),
            culprit_commit_sha=report.get("culprit_commit_sha"),
        )
        if report.get("culprit_commit_sha"):
            self.ledger.commits.add(report["culprit_commit_sha"])
        evidence = []
        for ref in report.get("evidence") or []:
            kind, key, quote = ref.get("type"), ref.get("ref") or "", ref.get("quote") or ""
            if kind == "log" and ref.get("deployment_id"):
                self.ledger.logs[key] = (ref["deployment_id"], quote)
            elif kind == "commit":
                self.ledger.commits.add(key)
            elif kind == "deploy":
                self.ledger.deploys[key] = key
            evidence.append(f"[{kind}:{key}] {quote[:MAX_LINE_CHARS]}")
        body = "\n".join(
            [
                f"Likely cause: {report.get('likely_cause') or ''}",
                f"Summary: {report.get('summary') or ''}",
                f"Suggested fix: {report.get('suggested_fix') or 'none'}",
                f"Missing information: {report.get('missing') or 'none'}",
                "Evidence:",
                *evidence,
            ]
        )
        text = json.dumps(meta, indent=1) + "\n" + untrusted("investigation report", body)
        if item.feedback_rating == "down":
            note = f": {item.feedback_note}" if item.feedback_note else ""
            text += (
                "\nA reader rated this report as wrong" + note + ". Say so, and do not present "
                "its conclusion as fact."
            )
        return text

    async def changes_since_last_good(self, deployment_id: str) -> str:
        target = self.ledger.deploys.get(deployment_id.strip(), deployment_id.strip())
        deployment = await self._session.get(Deployment, target)
        if deployment is None:
            deployment = await self._session.scalar(
                select(Deployment).where(Deployment.external_id == deployment_id.strip()).limit(1)
            )
        if deployment is None:
            return f"error: no deployment with id '{deployment_id}'"
        self.ledger.add_deployment(deployment)
        changes = await get_changes(self._session, deployment)
        if changes.baseline is None:
            return changes.note or "No earlier successful deploy to compare against."
        self.ledger.deploys[changes.baseline.id] = changes.baseline.id
        if changes.baseline.commit_sha:
            self.ledger.commits.add(changes.baseline.commit_sha)
        summary: dict[str, Any] = {
            "deployment_id": deployment.id,
            "last_good_deployment_id": changes.baseline.id,
            "last_good_started_at": _iso(changes.baseline.started_at),
            "same_commit": changes.same_commit,
            "failed_deploys_in_between": changes.failed_between,
            "duration_change_ms": changes.duration_delta_ms,
            "source": changes.source,
            "commit_count": len(changes.commits),
            "file_count": len(changes.files),
            "files": [
                {
                    "filename": f.filename,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    **({"suspect": f.suspect_reason, "line": f.line} if f.suspect else {}),
                }
                for f in changes.files[:MAX_CHANGED_FILES]
            ],
        }
        lines = []
        for commit in changes.commits[:MAX_CHANGED_COMMITS]:
            self.ledger.commits.add(commit.sha)
            lines.append(f"{commit.sha} {commit.author}: {_first_line(commit.message, 160)}")
        text = json.dumps(summary, indent=1)
        if len(changes.files) > MAX_CHANGED_FILES or changes.truncated:
            text += f"\nOnly the first {MAX_CHANGED_FILES} files are listed."
        if lines:
            more = (
                f" (the first {MAX_CHANGED_COMMITS} of {len(changes.commits)})"
                if len(changes.commits) > MAX_CHANGED_COMMITS
                else ""
            )
            text += f"\nCommits, newest first{more}:\n" + untrusted("commits", "\n".join(lines))
        if changes.note:
            text += f"\nNote: {changes.note}"
        return text

    async def get_health_history(self, service_id: str) -> str:
        text = await super().get_health_history(service_id)
        service = await self._session.scalar(
            select(Service)
            .where(or_(Service.id == service_id, Service.name == service_id))
            .limit(1)
        )
        if service is None:
            return text
        checks = (
            await self._session.scalars(
                select(HealthCheck)
                .where(HealthCheck.service_id == service.id)
                .order_by(HealthCheck.checked_at.desc())
                .limit(30)
            )
        ).all()
        checks = list(reversed(checks))
        return text + self.ledger.add_chart(
            "line",
            f"Response time of {service.name}",
            "ms",
            [f"{check.checked_at:%H:%M}" for check in checks],
            [
                (
                    "Response time",
                    "info",
                    [check.latency_ms if check.ok else None for check in checks],
                )
            ],
            subtitle=f"last {len(checks)} health checks · failed checks leave a gap · UTC",
        )


def _percentile(values: list[int], pct: float) -> int | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered), math.ceil(pct / 100 * len(ordered))) - 1)]


def _health(service_id: str, checks: list[HealthCheck]) -> dict[str, Any]:
    """Uptime, latency and outages from one service's checks, given oldest first.

    An outage is a run of failed checks; it lasts from the first failed check until the
    next passing one (or until now, if it is still going on).
    """
    ok = [c for c in checks if c.ok]
    latencies = [c.latency_ms for c in ok if c.latency_ms is not None]
    outages: list[float] = []
    down_since: datetime | None = None
    for check in checks:
        if not check.ok and down_since is None:
            down_since = ensure_utc(check.checked_at)
        elif check.ok and down_since is not None:
            outages.append((ensure_utc(check.checked_at) - down_since).total_seconds())
            down_since = None
    ongoing = down_since is not None
    if down_since is not None:
        outages.append((utcnow() - down_since).total_seconds())
    return {
        "service_id": service_id,
        "checks": len(checks),
        "failed_checks": len(checks) - len(ok),
        "uptime_percent": round(100 * len(ok) / len(checks), 2),
        "p50_latency_ms": _percentile(latencies, 50),
        "p95_latency_ms": _percentile(latencies, 95),
        "outages": len(outages),
        "longest_outage_minutes": round(max(outages) / 60, 1) if outages else 0,
        "down_now": ongoing,
        "down_since": _iso(down_since) if ongoing else None,
        "last_check_at": _iso(checks[-1].checked_at),
    }


def _window(hours: int) -> str:
    return f"last {hours} hours" if hours <= 48 else f"last {round(hours / 24)} days"


def _status_series(rows: list[dict[str, int]]) -> list[tuple[str, str, list[float | None]]]:
    """Ready, failed and everything else, one value per row of status counts."""
    ready = [float(row.get(FINISHED_GOOD, 0)) for row in rows]
    failed = [float(row.get(FINISHED_BAD, 0)) for row in rows]
    other = [
        float(sum(n for status, n in row.items() if status not in (FINISHED_GOOD, FINISHED_BAD)))
        for row in rows
    ]
    return [("Ready", "ok", ready), ("Failed", "err", failed), ("Other", "muted", other)]


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
