"""charts attached to chat answers

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-22 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chat_message") as batch:
        batch.add_column(sa.Column("charts", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_message") as batch:
        batch.drop_column("charts")
