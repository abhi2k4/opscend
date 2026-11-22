"""What changed between a deployment and the last one of its service that went live."""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.core.time import duration_ms
from app.integrations.base import CommitSource, Comparison, ProviderError
from app.integrations.connect import adapter_for
from app.models import Commit, CommitDiff, Deployment, Integration
from app.schemas import Capability
from app.services.presenters import deployment_out

log = logging.getLogger(__name__)

MAX_COMMITS = 100
SAME_COMMIT = (
    "Same commit as the last deploy that went live, so the code did not change. "
    "Look at environment variables, configuration or the platform itself."
)
NO_BASELINE = "No earlier successful deploy of this service is on record to compare against."
NO_SOURCE = (
    "Commits are listed from what Opscend has stored. Connect GitHub with access to this "
    "repo to see the exact commits and files."
)


async def baseline_for(session: AsyncSession, deployment: Deployment) -> Deployment | None:
    """The newest ready deploy of the same service (and environment) before this one."""
    query = (
        select(Deployment)
        .where(
            Deployment.service_id == deployment.service_id,
            Deployment.status == "ready",
            Deployment.started_at < deployment.started_at,
            Deployment.id != deployment.id,
        )
        .order_by(Deployment.started_at.desc())
        .limit(1)
    )
    if deployment.environment:
        same_env = await session.scalar(
            query.where(Deployment.environment == deployment.environment)
        )
        if same_env is not None:
            return same_env
    return await session.scalar(query)


async def _compare(
    session: AsyncSession, repo: str, base: str, head: str
) -> tuple[Comparison | None, str | None]:
    """Ask a connected source for the exact range. Returns (comparison, why not)."""
    integrations = await session.scalars(
        select(Integration).where(Integration.is_demo.is_(False), Integration.status != "error")
    )
    for integration in integrations:
        if Capability.COMMIT_DIFF not in integration.capabilities:
            continue
        adapter = adapter_for(integration)
        if not isinstance(adapter, CommitSource):
            continue
        try:
            return await adapter.compare(repo, base, head), None
        except ProviderError as exc:
            log.info("compare %s %s...%s failed: %s", repo, base[:7], head[:7], exc)
            return None, f"The exact comparison is unavailable ({exc}). {NO_SOURCE}"
        finally:
            await adapter.aclose()
    return None, NO_SOURCE


async def _from_history(
    session: AsyncSession, deployment: Deployment, baseline: Deployment
) -> tuple[list[schemas.Commit], list[schemas.ChangedFile]]:
    """Stored commits of the repo made after the baseline shipped, plus their stored diffs."""
    repo = deployment.service.repo
    if not repo:
        return [], []
    base_commit = (
        await session.scalar(
            select(Commit).where(Commit.repo == repo, Commit.sha == baseline.commit_sha).limit(1)
        )
        if baseline.commit_sha
        else None
    )
    head_commit = (
        await session.scalar(
            select(Commit).where(Commit.repo == repo, Commit.sha == deployment.commit_sha).limit(1)
        )
        if deployment.commit_sha
        else None
    )
    after = base_commit.committed_at if base_commit else baseline.started_at
    until = head_commit.committed_at if head_commit else deployment.started_at
    rows = (
        await session.scalars(
            select(Commit)
            .where(Commit.repo == repo, Commit.committed_at > after, Commit.committed_at <= until)
            .order_by(Commit.committed_at.desc())
            .limit(MAX_COMMITS)
        )
    ).all()
    commits = [schemas.Commit.model_validate(row) for row in rows]
    if not commits:
        return [], []

    merged: dict[str, schemas.ChangedFile] = {}
    diffs = await session.scalars(
        select(CommitDiff).where(
            CommitDiff.repo == repo, CommitDiff.sha.in_([c.sha for c in commits])
        )
    )
    for diff in diffs:
        for item in diff.files:
            seen = merged.get(item["filename"])
            if seen is None:
                merged[item["filename"]] = schemas.ChangedFile(
                    filename=item["filename"],
                    status=item.get("status", "modified"),
                    additions=item.get("additions", 0),
                    deletions=item.get("deletions", 0),
                )
            else:
                seen.additions += item.get("additions", 0)
                seen.deletions += item.get("deletions", 0)
    return commits, sorted(merged.values(), key=lambda f: f.filename)


async def get_changes(session: AsyncSession, deployment: Deployment) -> schemas.DeploymentChanges:
    baseline = await baseline_for(session, deployment)
    if baseline is None:
        return schemas.DeploymentChanges(
            baseline=None,
            same_commit=False,
            failed_between=0,
            duration_delta_ms=None,
            commits=[],
            files=[],
            source="none",
            truncated=False,
            note=NO_BASELINE,
            compare_url=None,
        )

    failed_between = await session.scalar(
        select(func.count(Deployment.id)).where(
            Deployment.service_id == deployment.service_id,
            Deployment.status == "failed",
            Deployment.started_at > baseline.started_at,
            Deployment.started_at < deployment.started_at,
        )
    )
    this_ms = duration_ms(deployment.started_at, deployment.finished_at)
    base_ms = duration_ms(baseline.started_at, baseline.finished_at)
    repo, base, head = deployment.service.repo, baseline.commit_sha, deployment.commit_sha
    same_commit = bool(base and head and base == head)
    result = schemas.DeploymentChanges(
        baseline=deployment_out(baseline),
        same_commit=same_commit,
        failed_between=failed_between or 0,
        duration_delta_ms=this_ms - base_ms
        if this_ms is not None and base_ms is not None
        else None,
        commits=[],
        files=[],
        source="none",
        truncated=False,
        note=SAME_COMMIT if same_commit else None,
        compare_url=(
            f"https://github.com/{repo}/compare/{base}...{head}"
            if repo and base and head and not same_commit
            else None
        ),
    )
    if same_commit:
        return result

    integration = await session.get(Integration, deployment.service.integration_id)
    is_demo = bool(integration and integration.is_demo)
    comparison, why_not = (None, None)
    if repo and base and head and not is_demo:
        comparison, why_not = await _compare(session, repo, base, head)
    if comparison is not None:
        result.source = "compare"
        result.commits = [
            schemas.Commit.model_validate(commit.model_dump())
            for commit in reversed(comparison.commits)  # newest first, like the fallback
        ]
        result.files = comparison.files
        result.truncated = comparison.truncated
        return result

    result.commits, result.files = await _from_history(session, deployment, baseline)
    result.source = "history" if result.commits else "none"
    if not is_demo:
        result.note = why_not or (NO_SOURCE if repo else "This service is not linked to a repo.")
    return result
