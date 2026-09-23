"""Add idempotent workflow effects and placeholder outputs.

Revision ID: 0002_orchestration
Revises: 0001_initial
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_orchestration"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("effect_key", sa.String(255), nullable=True))
    op.execute("UPDATE audit_events SET effect_key = id::text WHERE effect_key IS NULL")
    op.alter_column("audit_events", "effect_key", nullable=False)
    op.create_unique_constraint("uq_audit_events_effect_key", "audit_events", ["effect_key"])
    op.create_unique_constraint("uq_approvals_run_action", "approvals", ["run_id", "action"])
    op.create_table(
        "run_outputs",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("incident_runs.id"), primary_key=True),
        sa.Column("reproduction", sa.JSON()),
        sa.Column("evidence_placeholder", sa.JSON()),
        sa.Column("diagnosis_placeholder", sa.JSON()),
        sa.Column("repair_placeholder", sa.JSON()),
        sa.Column("verification_placeholder", sa.JSON()),
        sa.Column("report_placeholder", sa.JSON()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("run_outputs")
    op.drop_constraint("uq_approvals_run_action", "approvals", type_="unique")
    op.drop_constraint("uq_audit_events_effect_key", "audit_events", type_="unique")
    op.drop_column("audit_events", "effect_key")
