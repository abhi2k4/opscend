"""reader feedback on investigation reports

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-22 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("investigation") as batch:
        batch.add_column(sa.Column("feedback_rating", sa.String(length=8), nullable=True))
        batch.add_column(sa.Column("feedback_note", sa.Text(), nullable=True))
        batch.add_column(sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("investigation") as batch:
        batch.drop_column("feedback_at")
        batch.drop_column("feedback_note")
        batch.drop_column("feedback_rating")
