"""notification dedup and sync failure streaks

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20 10:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notification", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dedup_key", sa.String(length=255), nullable=True))
        batch_op.create_index(batch_op.f("ix_notification_dedup_key"), ["dedup_key"], unique=False)
    with op.batch_alter_table("integration", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("sync_failures", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("integration", schema=None) as batch_op:
        batch_op.drop_column("sync_failures")
    with op.batch_alter_table("notification", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notification_dedup_key"))
        batch_op.drop_column("dedup_key")
