"""Inline citations in chat answers.

A chart is placed the same way, as `[chart:<id>]`, and is kept only if a tool built a
chart with that id during this answer.

The model cites what it saw as `[deploy:<id>]`, `[log:<id>]`, `[commit:<sha>]`,
`[incident:<id>]` or `[service:<id>]`. Each one is checked against the ledger: a
verified marker is rewritten to its canonical id and described from the database;
anything the tools never showed is removed, so an answer cannot link to invented ids.
"""

import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Commit, Deployment, Incident, Service

from .tools import CHAT_TOOL_SPECS, ChatLedger

CITATION = re.compile(r"\[(deploy|log|commit|incident|service):\s*([^\]\s]{1,80})\s*\]")
# Models bend the marker format: fullwidth brackets ("【log:…】"), no prefix on log ids
# ("[log_ab12cd34ef]"), several ids in one bracket ("[log:a, log:b]", "[log_a; log_b]")
# and non-ASCII hyphens inside ids. All of these are normalized before verification.
BRACKETS = str.maketrans({"【": "[", "】": "]", "［": "[", "］": "]"})
HYPHENS = re.compile(r"[\u2010-\u2015\u2212]")
GROUP = re.compile(r"\[([^\[\]\n]{1,600})\]")
PART = re.compile(r"^(?:(deploy|log|commit|incident|service):\s*)?(\S{1,80})$")
BARE_LOG = re.compile(r"^log_[0-9a-f]{10}$")
# Made-up marker types such as "[deploy_stats:0]" are removed.
STRAY = re.compile(r"\[([a-z][a-z_]{2,30}):[^\]\s]{1,80}\]")
TYPES = ("deploy", "log", "commit", "incident", "service")
CHART = re.compile(r"\s*\[chart:\s*([^\]\s]{1,40})\s*\]\s*")
MAX_CHARTS = 3
# Tool names cited as if they were sources ("[deploy_stats]") are removed too.
TOOL_REF = re.compile(
    r"\[(?:" + "|".join(spec["function"]["name"] for spec in CHAT_TOOL_SPECS) + r")\]"
)
MAX_DETAIL_CHARS = 200


async def resolve(
    session: AsyncSession, content: str, ledger: ChatLedger
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the answer with only verified markers, their descriptions, and its charts."""
    content = GROUP.sub(_split_group, content.translate(BRACKETS))
    content = STRAY.sub(
        lambda m: m.group(0) if m.group(1) in TYPES or m.group(1) == "chart" else "", content
    )
    content = TOOL_REF.sub("", content)
    citations: dict[tuple[str, str], dict[str, Any]] = {}
    replacements: dict[str, str] = {}
    for match in CITATION.finditer(content):
        kind, raw = match.group(1), match.group(2)
        if match.group(0) in replacements:
            continue
        citation = await _verify(session, kind, raw, ledger)
        if citation is None:
            replacements[match.group(0)] = ""
            continue
        citations.setdefault((citation["type"], citation["ref"]), citation)
        replacements[match.group(0)] = f"[{citation['type']}:{citation['ref']}]"

    def _swap(match: re.Match[str]) -> str:
        return replacements.get(match.group(0), "")

    cleaned = CITATION.sub(_swap, content)
    # Tidy what removed markers leave behind ("failed ." / double spaces); [^\S\n] is any
    # whitespace but a newline, including the narrow no-break spaces some models emit.
    cleaned = re.sub(r"[^\S\n]+([.,;:)])", r"\1", cleaned)
    cleaned = re.sub(r"[^\S\n]{2,}", " ", cleaned).strip()
    cleaned, charts = _place_charts(cleaned, ledger)
    return cleaned, list(citations.values()), charts


def _place_charts(content: str, ledger: ChatLedger) -> tuple[str, list[dict[str, Any]]]:
    """Keep each chart a tool really built, once, on a line of its own; drop the rest."""
    charts: dict[str, dict[str, Any]] = {}

    def _swap(match: re.Match[str]) -> str:
        chart_id = match.group(1).strip("`'\"")
        chart = ledger.charts.get(chart_id)
        if chart is None or chart_id in charts or len(charts) >= MAX_CHARTS:
            return " "
        charts[chart_id] = chart
        return f"\n\n[chart:{chart_id}]\n\n"

    placed = CHART.sub(_swap, content)
    placed = re.sub(r"\n{3,}", "\n\n", placed)
    placed = re.sub(r"[^\S\n]+([.,;:)])", r"\1", placed)
    return placed.strip(), list(charts.values())


def _split_group(match: re.Match[str]) -> str:
    """Rewrite one bracket into canonical markers when every part of it is a citation."""
    parts = [p.strip() for p in re.split(r"[,;]", match.group(1))]
    markers = []
    for part in parts:
        hit = PART.match(HYPHENS.sub("-", part))
        if hit is None:
            return match.group(0)
        kind, ref = hit.group(1), hit.group(2)
        if kind is None:
            if not BARE_LOG.match(ref):
                return match.group(0)
            kind = "log"
        markers.append(f"[{kind}:{ref}]")
    return " ".join(markers)


def _citation(kind: str, ref: str, label: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "ref": ref,
        "label": label,
        "detail": extra.get("detail"),
        "deployment_id": extra.get("deployment_id"),
        "url": extra.get("url"),
    }


async def _verify(
    session: AsyncSession, kind: str, raw: str, ledger: ChatLedger
) -> dict[str, Any] | None:
    ref = raw.strip().strip("`'\"")
    if kind == "deploy":
        deployment_id = ledger.deploys.get(ref)
        deployment = await session.get(Deployment, deployment_id) if deployment_id else None
        if deployment is None:
            return None
        sha = (deployment.commit_sha or "")[:7]
        label = f"{deployment.service.name} · {deployment.status}" + (f" · {sha}" if sha else "")
        return _citation("deploy", deployment.id, label, deployment_id=deployment.id)
    if kind == "log":
        if ref not in ledger.logs:
            return None
        deployment_id, text = ledger.logs[ref]
        return _citation(
            "log", ref, ref, detail=text[:MAX_DETAIL_CHARS], deployment_id=deployment_id
        )
    if kind == "commit":
        sha = ledger.resolve_commit(ref)
        if sha is None:
            return None
        deployment = await session.scalar(
            select(Deployment).where(Deployment.commit_sha == sha).limit(1)
        )
        repo = deployment.service.repo if deployment else None
        if repo is None:
            repo = await session.scalar(select(Commit.repo).where(Commit.sha == sha).limit(1))
        url = f"https://github.com/{repo}/commit/{sha}" if repo else None
        return _citation(
            "commit",
            sha,
            sha[:7],
            url=url,
            deployment_id=deployment.id if deployment else None,
        )
    if kind == "incident":
        incident = await session.get(Incident, ref) if ref in ledger.incidents else None
        if incident is None:
            return None
        return _citation(
            "incident", incident.id, incident.title, deployment_id=incident.deployment_id
        )
    service = await session.scalar(
        select(Service).where(or_(Service.id == ref, Service.name == ref)).limit(1)
    )
    if service is None or service.id not in ledger.services:
        return None
    return _citation("service", service.id, service.name)
