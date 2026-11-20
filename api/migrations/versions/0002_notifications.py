"""notifications

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18 21:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_status", sa.String(length=16), nullable=False),
        sa.Column("email_error", sa.Text(), nullable=True),
        sa.Column("email_attempts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("notification", schema=None) as batch_op:
        for column in ("kind", "created_at", "email_status"):
            batch_op.create_index(batch_op.f(f"ix_notification_{column}"), [column], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("notification", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notification_email_status"))
        batch_op.drop_index(batch_op.f("ix_notification_created_at"))
        batch_op.drop_index(batch_op.f("ix_notification_kind"))
    op.drop_table("notification")
