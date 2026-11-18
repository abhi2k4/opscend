"""The raw event store: every inbound event lands here before anything else happens."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.integrations.base import RawEventIn
from app.models import RawEvent


async def record_event(
    session: AsyncSession,
    event: RawEventIn,
    *,
    source: str,
    is_demo: bool = False,
    keep_duplicate: bool = True,
) -> RawEvent | None:
    """Store one event and commit.

    The first delivery of a dedup key is stored as the original. A repeat is stored
    as a flagged duplicate (so the inspector can show it) and is never processed;
    with `keep_duplicate=False` (polling) it is dropped and None is returned.
    The unique `claim` column makes this safe when two deliveries race.
    """
    seen = await session.scalar(select(RawEvent.id).where(RawEvent.claim == event.dedup_key))
    if seen is None:
        row = _row(event, source, is_demo, duplicate=False)
        session.add(row)
        try:
            await session.commit()
            return row
        except IntegrityError:
            await session.rollback()
    if not keep_duplicate:
        return None
    row = _row(event, source, is_demo, duplicate=True)
    session.add(row)
    await session.commit()
    return row


def _row(event: RawEventIn, source: str, is_demo: bool, *, duplicate: bool) -> RawEvent:
    return RawEvent(
        provider=event.provider,
        source=source,
        event_type=event.event_type,
        dedup_key=event.dedup_key,
        claim=None if duplicate else event.dedup_key,
        duplicate=duplicate,
        payload=event.payload,
        processed_at=utcnow() if duplicate else None,
        is_demo=is_demo,
    )
