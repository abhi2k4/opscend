"""a private copy of the sample data per visitor of the public demo

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-23 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_sandbox",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_demo_sandbox_last_seen_at", "demo_sandbox", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_demo_sandbox_last_seen_at", table_name="demo_sandbox")
    op.drop_table("demo_sandbox")
