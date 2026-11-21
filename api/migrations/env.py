"""Alembic environment: async engine, URL from app settings."""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models import Base

target_metadata = Base.metadata

# Postgres-only indexes created by hand in migrations (not declared on the models),
# so autogenerate must not offer to drop them.
UNMODELED_INDEXES = {"ix_log_line_message_trgm"}


def _include_object(obj, name, type_, reflected, compare_to) -> bool:  # noqa: ANN001
    return not (type_ == "index" and reflected and name in UNMODELED_INDEXES)


def _configure(**kwargs) -> None:  # noqa: ANN003
    context.configure(
        target_metadata=target_metadata,
        include_object=_include_object,
        render_as_batch=True,  # lets SQLite apply ALTERs
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=get_settings().database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
        await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
