"""Persist verification artifacts and deterministic ranking.

Revision ID: 0005_verification_results
Revises: 0004_repair_candidates
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_verification_results"
down_revision = "0004_repair_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("verification_runs", sa.Column("rank", sa.Integer()))
    op.add_column("verification_runs", sa.Column("score", sa.JSON()))
    op.create_unique_constraint(
        "uq_verification_runs_candidate", "verification_runs", ["candidate_id"]
    )
    op.create_table(
        "verification_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "verification_id",
            sa.Uuid(),
            sa.ForeignKey("verification_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("check_name", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("verification_id", "check_name", name="uq_verification_artifact_check"),
    )


def downgrade() -> None:
    op.drop_table("verification_artifacts")
    op.drop_constraint("uq_verification_runs_candidate", "verification_runs", type_="unique")
    op.drop_column("verification_runs", "score")
    op.drop_column("verification_runs", "rank")
