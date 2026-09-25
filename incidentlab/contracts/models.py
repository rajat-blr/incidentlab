"""Version 1 contracts for the PRD's core entities."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1


class RunState(StrEnum):
    CREATED = "CREATED"
    REPRODUCING = "REPRODUCING"
    COLLECTING = "COLLECTING"
    DIAGNOSING = "DIAGNOSING"
    AWAITING_REPAIR_APPROVAL = "AWAITING_REPAIR_APPROVAL"
    GENERATING = "GENERATING"
    VERIFYING = "VERIFYING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    NO_VERIFIED_CANDIDATE = "NO_VERIFIED_CANDIDATE"
    INCONCLUSIVE = "INCONCLUSIVE"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ScenarioTrafficStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sku: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    expected_status: int = Field(ge=100, le=599)


class ScenarioManifest(Contract):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    version: int = Field(ge=1)
    service: str = Field(min_length=1)
    description: str = Field(min_length=1)
    reset_command: str
    fault_mode: str
    traffic: list[ScenarioTrafficStep] = Field(min_length=1)
    failure_signal: dict[str, str | int]
    healthy_signal: dict[str, str | int]


class ScenarioSummary(Contract):
    id: str
    version: int
    service: str
    description: str


class RunCreateRequest(Contract):
    scenario_id: str
    idempotency_key: str = Field(min_length=1, max_length=128)


class RepairApprovalRequest(Contract):
    actor: str = Field(min_length=1, max_length=128)
    decision: Literal["approved", "rejected"]


class RunCancelRequest(Contract):
    actor: str = Field(min_length=1, max_length=128)


class IncidentRun(Contract):
    id: UUID
    scenario_id: str
    scenario_version: int
    pinned_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    workflow_id: str
    state: RunState
    created_at: datetime
    updated_at: datetime


class EvidenceItem(Contract):
    id: str = Field(min_length=1)
    run_id: UUID
    kind: Literal["metric", "trace", "log", "commit", "source", "gap"]
    source: str = Field(min_length=1)
    retrieval_method: str = Field(min_length=1)
    observed_start: datetime
    observed_end: datetime
    service: str
    summary: str
    artifact_ref: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid_window(self) -> "EvidenceItem":
        if self.observed_end < self.observed_start:
            raise ValueError("observed_end must be at or after observed_start")
        return self


class EvidenceArtifact(Contract):
    id: UUID
    run_id: UUID
    source: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    retrieved_at: datetime


class EvidenceLookup(Contract):
    tool: Literal["query_metric", "fetch_trace", "search_logs", "search_repository"]
    evidence_id: str = Field(min_length=1, max_length=128)


class HypothesisDraft(Contract):
    summary: str = Field(min_length=1, max_length=500)
    mechanism: str = Field(min_length=1, max_length=2000)
    supporting_evidence_ids: list[str] = Field(min_length=1, max_length=12)
    contradicting_evidence_ids: list[str] = Field(default_factory=list, max_length=12)
    confidence: Literal["low", "medium", "high"]
    proposed_checks: list[EvidenceLookup] = Field(default_factory=list, max_length=2)

    @field_validator("supporting_evidence_ids", "contradicting_evidence_ids")
    @classmethod
    def unique_citations(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence IDs must be unique")
        return value

    @model_validator(mode="after")
    def distinct_citations(self) -> "HypothesisDraft":
        if set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids):
            raise ValueError("evidence cannot both support and contradict a hypothesis")
        return self


class DiagnosisDraft(Contract):
    hypotheses: list[HypothesisDraft] = Field(min_length=1, max_length=3)
    follow_up_queries: list[EvidenceLookup] = Field(default_factory=list, max_length=2)


class Hypothesis(Contract):
    id: UUID
    run_id: UUID
    summary: str = Field(min_length=1)
    mechanism: str = Field(min_length=1)
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    confidence: Literal["low", "medium", "high"]
    proposed_checks: list[EvidenceLookup] = Field(default_factory=list, max_length=2)
    model_id: str | None = None
    prompt_version: str | None = None

    @field_validator("supporting_evidence_ids", "contradicting_evidence_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence IDs must be unique")
        return value

    @model_validator(mode="after")
    def distinct_sides(self) -> "Hypothesis":
        if set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids):
            raise ValueError("evidence cannot both support and contradict a hypothesis")
        return self


class Approval(Contract):
    id: UUID
    run_id: UUID
    actor: str = Field(min_length=1)
    action: Literal["generate_repair", "create_draft_pr"]
    decision: Literal["approved", "rejected"]
    policy_version: str
    decided_at: datetime


class RepairCandidate(Contract):
    id: UUID
    run_id: UUID
    target_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    unified_diff: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    expected_behavior: str = Field(min_length=1)
    changed_paths: list[str] = Field(min_length=1)
    generator_id: str
    diff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_status: Literal["accepted"]
    policy_version: str = Field(min_length=1)


class RepairCandidateDraft(Contract):
    unified_diff: str = Field(min_length=1, max_length=65536)
    explanation: str = Field(min_length=1, max_length=2000)
    expected_behavior: str = Field(min_length=1, max_length=1000)


class RepairGenerationDraft(Contract):
    candidates: list[RepairCandidateDraft] = Field(min_length=1, max_length=2)


class VerificationCheck(Contract):
    name: Literal[
        "baseline_replay",
        "patch_apply",
        "build",
        "static",
        "unit",
        "integration",
        "incident_replay",
        "performance",
    ]
    outcome: Literal["PASS", "FAIL", "INCONCLUSIVE"]
    started_at: datetime
    finished_at: datetime
    exit_code: int | None
    artifact_ref: str | None
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class VerificationRun(Contract):
    id: UUID
    candidate_id: UUID
    environment_digest: str
    checks: list[VerificationCheck]
    outcome: Literal["PASS", "FAIL", "INCONCLUSIVE"]
    score_version: str


class AuditEvent(Contract):
    id: UUID
    run_id: UUID
    kind: str
    actor: str
    correlation_id: str
    created_at: datetime
    details: dict[str, str | int | bool | None]


class ModelUsage(Contract):
    id: UUID
    run_id: UUID
    provider: str
    model_id: str
    prompt_version: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)
