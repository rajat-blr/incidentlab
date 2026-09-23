"""SQLAlchemy Core metadata for durable run records."""

import sqlalchemy as sa

metadata = sa.MetaData()

incident_runs = sa.Table(
    "incident_runs",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("scenario_id", sa.String(128), nullable=False),
    sa.Column("scenario_version", sa.Integer(), nullable=False),
    sa.Column("pinned_commit", sa.String(40), nullable=False),
    sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
    sa.Column("workflow_id", sa.String(255), nullable=False, unique=True),
    sa.Column("state", sa.String(48), nullable=False),
    sa.Column("failure_category", sa.String(128)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)

evidence_items = sa.Table(
    "evidence_items",
    metadata,
    sa.Column("id", sa.String(128), primary_key=True),
    sa.Column("run_id", sa.Uuid(), sa.ForeignKey("incident_runs.id"), nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("source", sa.String(255), nullable=False),
    sa.Column("retrieval_method", sa.String(255), nullable=False),
    sa.Column("observed_start", sa.DateTime(timezone=True), nullable=False),
    sa.Column("observed_end", sa.DateTime(timezone=True), nullable=False),
    sa.Column("service", sa.String(128), nullable=False),
    sa.Column("summary", sa.Text(), nullable=False),
    sa.Column("artifact_ref", sa.Text(), nullable=False),
    sa.Column("content_sha256", sa.String(64), nullable=False),
)

hypotheses = sa.Table(
    "hypotheses",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("run_id", sa.Uuid(), sa.ForeignKey("incident_runs.id"), nullable=False),
    sa.Column("summary", sa.Text(), nullable=False),
    sa.Column("mechanism", sa.Text(), nullable=False),
    sa.Column("supporting_evidence_ids", sa.JSON(), nullable=False),
    sa.Column("contradicting_evidence_ids", sa.JSON(), nullable=False),
    sa.Column("confidence", sa.String(16), nullable=False),
    sa.Column("proposed_checks", sa.JSON(), nullable=False),
    sa.Column("validation_status", sa.String(32), nullable=False),
    sa.Column("model_id", sa.String(255)),
    sa.Column("prompt_version", sa.String(64)),
)

approvals = sa.Table(
    "approvals",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("run_id", sa.Uuid(), sa.ForeignKey("incident_runs.id"), nullable=False),
    sa.Column("actor", sa.String(128), nullable=False),
    sa.Column("action", sa.String(64), nullable=False),
    sa.Column("decision", sa.String(16), nullable=False),
    sa.Column("policy_version", sa.String(64), nullable=False),
    sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("run_id", "action", name="uq_approvals_run_action"),
)

repair_candidates = sa.Table(
    "repair_candidates",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("run_id", sa.Uuid(), sa.ForeignKey("incident_runs.id"), nullable=False),
    sa.Column("target_commit", sa.String(40), nullable=False),
    sa.Column("diff_artifact_ref", sa.Text(), nullable=False),
    sa.Column("changed_paths", sa.JSON(), nullable=False),
    sa.Column("generator_id", sa.String(255), nullable=False),
    sa.Column("explanation", sa.Text(), nullable=False),
    sa.Column("expected_behavior", sa.Text(), nullable=False),
)

verification_runs = sa.Table(
    "verification_runs",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("candidate_id", sa.Uuid(), sa.ForeignKey("repair_candidates.id"), nullable=False),
    sa.Column("environment_digest", sa.String(255), nullable=False),
    sa.Column("checks", sa.JSON(), nullable=False),
    sa.Column("outcome", sa.String(24), nullable=False),
    sa.Column("score_version", sa.String(64), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
)

audit_events = sa.Table(
    "audit_events",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("run_id", sa.Uuid(), sa.ForeignKey("incident_runs.id"), nullable=False),
    sa.Column("kind", sa.String(128), nullable=False),
    sa.Column("actor", sa.String(128), nullable=False),
    sa.Column("correlation_id", sa.String(128), nullable=False),
    sa.Column("effect_key", sa.String(255), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("details", sa.JSON(), nullable=False),
    sa.UniqueConstraint("effect_key", name="uq_audit_events_effect_key"),
)

run_outputs = sa.Table(
    "run_outputs",
    metadata,
    sa.Column("run_id", sa.Uuid(), sa.ForeignKey("incident_runs.id"), primary_key=True),
    sa.Column("reproduction", sa.JSON()),
    sa.Column("evidence_placeholder", sa.JSON()),
    sa.Column("diagnosis_placeholder", sa.JSON()),
    sa.Column("repair_placeholder", sa.JSON()),
    sa.Column("verification_placeholder", sa.JSON()),
    sa.Column("report_placeholder", sa.JSON()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)

model_usage = sa.Table(
    "model_usage",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("run_id", sa.Uuid(), sa.ForeignKey("incident_runs.id"), nullable=False),
    sa.Column("provider", sa.String(128), nullable=False),
    sa.Column("model_id", sa.String(255), nullable=False),
    sa.Column("prompt_version", sa.String(64), nullable=False),
    sa.Column("input_tokens", sa.Integer(), nullable=False),
    sa.Column("output_tokens", sa.Integer(), nullable=False),
    sa.Column("latency_ms", sa.Integer(), nullable=False),
    sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=False),
)
