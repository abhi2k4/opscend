"""choose which services are monitored

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-23 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("service") as batch:
        batch.add_column(
            sa.Column("monitored", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("service") as batch:
        batch.drop_column("monitored")
