"""Persist validated repair diffs and policy metadata.

Revision ID: 0004_repair_candidates
Revises: 0003_evidence_artifacts
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_repair_candidates"
down_revision = "0003_evidence_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "repair_candidates",
        sa.Column("unified_diff", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "repair_candidates",
        sa.Column("diff_sha256", sa.String(64), nullable=False, server_default="0" * 64),
    )
    op.add_column(
        "repair_candidates",
        sa.Column("policy_status", sa.String(32), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "repair_candidates",
        sa.Column("policy_version", sa.String(64), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "repair_candidates",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.alter_column("repair_candidates", "unified_diff", server_default=None)
    op.alter_column("repair_candidates", "diff_sha256", server_default=None)
    op.alter_column("repair_candidates", "policy_status", server_default=None)
    op.alter_column("repair_candidates", "policy_version", server_default=None)
    op.alter_column("repair_candidates", "created_at", server_default=None)
    op.create_unique_constraint(
        "uq_repair_candidates_run_diff",
        "repair_candidates",
        ["run_id", "diff_sha256"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_repair_candidates_run_diff", "repair_candidates", type_="unique")
    op.drop_column("repair_candidates", "created_at")
    op.drop_column("repair_candidates", "policy_version")
    op.drop_column("repair_candidates", "policy_status")
    op.drop_column("repair_candidates", "diff_sha256")
    op.drop_column("repair_candidates", "unified_diff")
