"""Deleting old high-volume rows so the database stays small and fast.

Log lines and health checks are the only tables that grow without bound. Pruning
logs never breaks evidence: an investigation report keeps its quotes, and a log
fetched again from the provider gets the same deterministic id.
"""

import logging
from datetime import timedelta

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.time import utcnow
from app.models import HealthCheck, LogLine

log = logging.getLogger(__name__)

BATCH = 5000


async def prune_old_data() -> dict[str, int]:
    """Delete rows older than OPSCEND_RETENTION_DAYS, in batches. Returns counts."""
    days = get_settings().retention_days
    if days <= 0:
        return {}
    cutoff = utcnow() - timedelta(days=days)
    counts = {
        "log_line": await _prune(LogLine, LogLine.id, LogLine.ts < cutoff),
        "health_check": await _prune(HealthCheck, HealthCheck.id, HealthCheck.checked_at < cutoff),
    }
    if any(counts.values()):
        log.info("pruned rows older than %d days: %s", days, counts)
    return counts


async def _prune(model, id_column, condition) -> int:  # noqa: ANN001
    """Short transactions, so pruning never holds long locks against ingestion."""
    total = 0
    while True:
        async with session_scope() as session:
            ids = (await session.scalars(select(id_column).where(condition).limit(BATCH))).all()
            if not ids:
                return total
            await session.execute(delete(model).where(id_column.in_(ids)))
            await session.commit()
            total += len(ids)
