"""chat sessions belong to a visitor in the public demo

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-23 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chat_session") as batch:
        batch.add_column(sa.Column("owner", sa.String(36), nullable=True))
        batch.create_index("ix_chat_session_owner", ["owner"])


def downgrade() -> None:
    with op.batch_alter_table("chat_session") as batch:
        batch.drop_index("ix_chat_session_owner")
        batch.drop_column("owner")
