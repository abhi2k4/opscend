"""incident memory: error fingerprints and the deploy that resolved each incident

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-24 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# For incidents resolved before this migration: the first ready deploy of the service
# that started after the failed one, and no later than the incident was resolved.
# That is the same rule incidents/rules.py applies to new ones.
BACKFILL_RESOLVED_BY = """
UPDATE incident SET resolved_by_deployment_id = (
    SELECT fix.id FROM deployment AS fix, deployment AS failed
    WHERE failed.id = incident.deployment_id
      AND fix.service_id = incident.service_id
      AND fix.status = 'ready'
      AND fix.started_at > failed.started_at
      AND fix.started_at <= incident.resolved_at
    ORDER BY fix.started_at
    LIMIT 1
)
WHERE status = 'resolved' AND trigger = 'deploy_failed' AND deployment_id IS NOT NULL
"""


def upgrade() -> None:
    with op.batch_alter_table("incident") as batch:
        batch.add_column(sa.Column("signature", sa.String(16), nullable=True))
        batch.add_column(sa.Column("family", sa.String(16), nullable=True))
        batch.add_column(sa.Column("error_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("resolved_by_deployment_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("fix_kind", sa.String(16), nullable=True))
        batch.create_foreign_key(
            "fk_incident_resolved_by_deployment_id_deployment",
            "deployment",
            ["resolved_by_deployment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_incident_signature", ["signature"])
        batch.create_index("ix_incident_family", ["family"])
    op.execute(BACKFILL_RESOLVED_BY)


def downgrade() -> None:
    with op.batch_alter_table("incident") as batch:
        batch.drop_index("ix_incident_family")
        batch.drop_index("ix_incident_signature")
        batch.drop_constraint(
            "fk_incident_resolved_by_deployment_id_deployment", type_="foreignkey"
        )
        for column in (
            "fix_kind",
            "resolved_by_deployment_id",
            "error_text",
            "family",
            "signature",
        ):
            batch.drop_column(column)
