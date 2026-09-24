"""Store immutable raw evidence artifacts.

Revision ID: 0003_evidence_artifacts
Revises: 0002_orchestration
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_evidence_artifacts"
down_revision = "0002_orchestration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("incident_runs.id"), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id", "source", "content_sha256", name="uq_evidence_artifacts_run_source_hash"
        ),
    )


def downgrade() -> None:
    op.drop_table("evidence_artifacts")
