"""Declarative base and portable column types (work on SQLite and Postgres alike)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from app.core.time import ensure_utc


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetime, even on SQLite which drops the offset."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:  # noqa: ANN001
        return ensure_utc(value) if value is not None else None

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:  # noqa: ANN001
        return ensure_utc(value) if value is not None else None


def new_id() -> str:
    return str(uuid.uuid4())
