"""UTC time helpers. Every timestamp in Opscend is timezone-aware UTC."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; treat them as the UTC they were stored as."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def from_epoch_ms(value: int | float | None) -> datetime | None:
    return datetime.fromtimestamp(value / 1000, UTC) if value else None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def duration_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((ensure_utc(end) - ensure_utc(start)).total_seconds() * 1000))
