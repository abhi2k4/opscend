"""chat sessions, and indexes for cross-deploy queries

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-20 15:00:00

The chat assistant filters by service, time range and status across every deploy,
where the rest of the app mostly looks things up by deployment id. On Postgres the
log search also gets a trigram index, so `message ILIKE '%ECONNREFUSED%'` stays fast
on millions of lines. That needs the pg_trgm extension; if the database user may not
create it, the migration skips the index and search still works, just slower.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

TRGM_INDEX = "ix_log_line_message_trgm"


def upgrade() -> None:
    op.create_table(
        "chat_session",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_session_updated_at", "chat_session", ["updated_at"])
    op.create_table(
        "chat_message",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["chat_session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "index", name="uq_chat_message_order"),
    )
    op.create_index("ix_chat_message_session_id", "chat_message", ["session_id"])

    op.create_index("ix_deployment_service_started", "deployment", ["service_id", "started_at"])
    op.create_index("ix_health_check_service_checked", "health_check", ["service_id", "checked_at"])
    op.create_index("ix_log_line_ts", "log_line", ["ts"])
    op.create_index("ix_commit_author", "commit", ["author"])

    if op.get_bind().dialect.name == "postgresql":
        _create_trigram_index()


def _create_trigram_index() -> None:
    bind = op.get_bind()
    savepoint = bind.begin_nested()
    try:
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        bind.execute(
            sa.text(f"CREATE INDEX {TRGM_INDEX} ON log_line USING gin (message gin_trgm_ops)")
        )
        savepoint.commit()
    except sa.exc.DBAPIError as exc:
        savepoint.rollback()
        log.warning("skipping the log search index (pg_trgm unavailable): %s", exc.orig)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP INDEX IF EXISTS {TRGM_INDEX}")
    op.drop_index("ix_commit_author", table_name="commit")
    op.drop_index("ix_log_line_ts", table_name="log_line")
    op.drop_index("ix_health_check_service_checked", table_name="health_check")
    op.drop_index("ix_deployment_service_started", table_name="deployment")
    op.drop_index("ix_chat_message_session_id", table_name="chat_message")
    op.drop_table("chat_message")
    op.drop_index("ix_chat_session_updated_at", table_name="chat_session")
    op.drop_table("chat_session")
