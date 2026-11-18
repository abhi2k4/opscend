"""Commit diffs: stored ones first, then GitHub (cached afterwards)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.integrations.base import CommitSource
from app.integrations.connect import adapter_for
from app.models import CommitDiff, Integration
from app.schemas import Capability


async def get_commit_diff(
    session: AsyncSession, sha: str, repo: str | None
) -> schemas.CommitDiff | None:
    """Return the diff for a commit, or None when no source can provide it.

    `sha` may be abbreviated (7+ characters). May raise `ProviderError`.
    """
    if len(sha) < 7:
        return None
    query = select(CommitDiff).where(CommitDiff.sha.startswith(sha, autoescape=True))
    if repo:
        query = query.where(CommitDiff.repo == repo)
    stored = await session.scalar(query.limit(1))
    if stored is not None:
        return schemas.CommitDiff.model_validate(stored)
    if repo is None:
        return None

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
            diff = await adapter.get_commit_diff(repo, sha)
        finally:
            await adapter.aclose()
        session.add(CommitDiff(**diff.model_dump()))
        await session.commit()
        return diff
    return None
