"""Durable PostgreSQL operations used by the API and Temporal Activities."""

import hashlib
import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from incidentlab.contracts.models import (
    EvidenceArtifact,
    EvidenceItem,
    Hypothesis,
    IncidentRun,
    RepairCandidate,
    RunState,
    VerificationRun,
)
from incidentlab.db.tables import (
    approvals,
    audit_events,
    evidence_artifacts,
    evidence_items,
    hypotheses,
    incident_runs,
    model_usage,
    repair_candidates,
    run_outputs,
    verification_artifacts,
    verification_runs,
)
from incidentlab.evidence.collection import EvidenceBundle
from incidentlab.model_adapter.diagnosis import DiagnosisResult
from incidentlab.model_adapter.repair import RepairGenerationResult
from incidentlab.sandbox.runner import SandboxRunResult
from incidentlab.verification import (
    SCORE_VERSION,
    RankingFact,
    changed_line_count,
    derive_outcome,
    rank_candidates,
    terminal_state,
)


@lru_cache
def engine() -> sa.Engine:
    return sa.create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


def _run_from_row(row: sa.RowMapping) -> IncidentRun:
    return IncidentRun(
        id=row["id"],
        scenario_id=row["scenario_id"],
        scenario_version=row["scenario_version"],
        pinned_commit=row["pinned_commit"],
        workflow_id=row["workflow_id"],
        state=row["state"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create_or_get_run(
    scenario_id: str, scenario_version: int, idempotency_key: str, pinned_commit: str
) -> tuple[IncidentRun, bool]:
    run_id = uuid5(NAMESPACE_URL, f"incidentlab:{idempotency_key}")
    workflow_id = f"incidentlab-run-{run_id}"
    now = datetime.now(UTC)
    with engine().begin() as connection:
        created = connection.execute(
            insert(incident_runs)
            .values(
                id=run_id,
                scenario_id=scenario_id,
                scenario_version=scenario_version,
                pinned_commit=pinned_commit,
                idempotency_key=idempotency_key,
                workflow_id=workflow_id,
                state=RunState.CREATED.value,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[incident_runs.c.idempotency_key])
            .returning(incident_runs.c.id)
        ).scalar_one_or_none()
        row = (
            connection.execute(
                sa.select(incident_runs).where(incident_runs.c.idempotency_key == idempotency_key)
            )
            .mappings()
            .one()
        )
        if created is not None:
            _insert_event(
                connection,
                run_id,
                "run_created",
                "api",
                idempotency_key,
                f"run:{run_id}:created",
                {"scenario_id": scenario_id, "scenario_version": scenario_version},
                now,
            )
    return _run_from_row(row), created is not None


def get_run(run_id: UUID) -> IncidentRun | None:
    with engine().connect() as connection:
        row = (
            connection.execute(sa.select(incident_runs).where(incident_runs.c.id == run_id))
            .mappings()
            .one_or_none()
        )
    return _run_from_row(row) if row else None


def list_runs(*, state: RunState | None = None, limit: int = 50) -> list[IncidentRun]:
    statement = sa.select(incident_runs).order_by(incident_runs.c.created_at.desc()).limit(limit)
    if state is not None:
        statement = statement.where(incident_runs.c.state == state.value)
    with engine().connect() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_run_from_row(row) for row in rows]


def list_events(run_id: UUID) -> list[dict]:
    with engine().connect() as connection:
        rows = (
            connection.execute(
                sa.select(audit_events)
                .where(audit_events.c.run_id == run_id)
                .order_by(audit_events.c.created_at, audit_events.c.id)
            )
            .mappings()
            .all()
        )
    return [
        {
            "id": str(row["id"]),
            "run_id": str(row["run_id"]),
            "kind": row["kind"],
            "actor": row["actor"],
            "correlation_id": row["correlation_id"],
            "created_at": row["created_at"].isoformat(),
            "details": row["details"],
        }
        for row in rows
    ]


def list_evidence(run_id: UUID) -> list[EvidenceItem]:
    with engine().connect() as connection:
        rows = (
            connection.execute(
                sa.select(evidence_items)
                .where(evidence_items.c.run_id == run_id)
                .order_by(evidence_items.c.kind, evidence_items.c.id)
            )
            .mappings()
            .all()
        )
    return [EvidenceItem.model_validate(dict(row)) for row in rows]


def get_evidence_artifact(artifact_id: UUID) -> tuple[EvidenceArtifact, bytes] | None:
    with engine().connect() as connection:
        row = (
            connection.execute(
                sa.select(evidence_artifacts).where(evidence_artifacts.c.id == artifact_id)
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return None
    metadata = EvidenceArtifact(
        id=row["id"],
        run_id=row["run_id"],
        source=row["source"],
        media_type=row["media_type"],
        content_sha256=row["content_sha256"],
        byte_size=len(row["content"]),
        retrieved_at=row["retrieved_at"],
    )
    return metadata, row["content"]


def list_hypotheses(run_id: UUID) -> list[Hypothesis]:
    with engine().connect() as connection:
        rows = (
            connection.execute(
                sa.select(hypotheses).where(hypotheses.c.run_id == run_id).order_by(hypotheses.c.id)
            )
            .mappings()
            .all()
        )
    values = []
    for row in rows:
        data = dict(row)
        data.pop("validation_status")
        values.append(Hypothesis.model_validate(data))
    return values


def list_repair_candidates(run_id: UUID) -> list[RepairCandidate]:
    with engine().connect() as connection:
        rows = (
            connection.execute(
                sa.select(repair_candidates)
                .where(repair_candidates.c.run_id == run_id)
                .order_by(repair_candidates.c.created_at, repair_candidates.c.id)
            )
            .mappings()
            .all()
        )
    values = []
    for row in rows:
        data = dict(row)
        data.pop("diff_artifact_ref")
        data.pop("created_at")
        values.append(RepairCandidate.model_validate(data))
    return values


def list_verifications(run_id: UUID) -> list[VerificationRun]:
    with engine().connect() as connection:
        rows = (
            connection.execute(
                sa.select(verification_runs)
                .join(
                    repair_candidates,
                    verification_runs.c.candidate_id == repair_candidates.c.id,
                )
                .where(repair_candidates.c.run_id == run_id)
                .order_by(
                    verification_runs.c.rank.asc().nulls_last(),
                    verification_runs.c.candidate_id,
                )
            )
            .mappings()
            .all()
        )
    return [VerificationRun.model_validate(dict(row)) for row in rows]


def get_verification_artifact(artifact_id: UUID) -> tuple[dict, bytes] | None:
    with engine().connect() as connection:
        row = (
            connection.execute(
                sa.select(verification_artifacts).where(verification_artifacts.c.id == artifact_id)
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return None
    return (
        {
            "media_type": row["media_type"],
            "content_sha256": row["content_sha256"],
        },
        row["content"],
    )


def get_run_output(run_id: UUID, column: str) -> dict | None:
    if column not in run_outputs.c:
        raise ValueError("invalid output column")
    with engine().connect() as connection:
        return connection.execute(
            sa.select(run_outputs.c[column]).where(run_outputs.c.run_id == run_id)
        ).scalar_one_or_none()


def _insert_event(
    connection: sa.Connection,
    run_id: UUID,
    kind: str,
    actor: str,
    correlation_id: str,
    effect_key: str,
    details: dict,
    created_at: datetime,
) -> bool:
    inserted = connection.execute(
        insert(audit_events)
        .values(
            id=uuid4(),
            run_id=run_id,
            kind=kind,
            actor=actor,
            correlation_id=correlation_id,
            effect_key=effect_key,
            created_at=created_at,
            details=details,
        )
        .on_conflict_do_nothing(index_elements=[audit_events.c.effect_key])
        .returning(audit_events.c.id)
    ).scalar_one_or_none()
    return inserted is not None


def transition_run(
    run_id: UUID, state: RunState, effect_key: str, details: dict | None = None
) -> bool:
    now = datetime.now(UTC)
    with engine().begin() as connection:
        inserted = _insert_event(
            connection,
            run_id,
            "state_changed",
            "workflow",
            str(run_id),
            effect_key,
            {"state": state.value, **(details or {})},
            now,
        )
        if inserted:
            values = {"state": state.value, "updated_at": now}
            if state == RunState.FAILED:
                values["failure_category"] = (details or {}).get("failure_category", "unknown")
            connection.execute(
                incident_runs.update().where(incident_runs.c.id == run_id).values(**values)
            )
    return inserted


def record_output(run_id: UUID, column: str, payload: dict, effect_key: str) -> bool:
    if column not in {
        "reproduction",
        "evidence_placeholder",
        "diagnosis_placeholder",
        "repair_placeholder",
        "verification_placeholder",
        "report_placeholder",
    }:
        raise ValueError("invalid output column")
    now = datetime.now(UTC)
    with engine().begin() as connection:
        inserted = _insert_event(
            connection,
            run_id,
            f"{column}_recorded",
            "worker",
            str(run_id),
            effect_key,
            payload,
            now,
        )
        if inserted:
            statement = insert(run_outputs).values(
                run_id=run_id, updated_at=now, **{column: payload}
            )
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[run_outputs.c.run_id],
                    set_={column: payload, "updated_at": now},
                )
            )
    return inserted


def record_evidence_bundle(run_id: UUID, bundle: EvidenceBundle, effect_key: str) -> bool:
    """Atomically save exact artifacts, normalized items, and the durable activity effect."""
    now = datetime.now(UTC)
    artifacts = tuple(bundle.artifacts)
    items = tuple(bundle.items)
    artifacts_by_id = {artifact.id: artifact for artifact in artifacts}
    for item in items:
        referenced = UUID(item.artifact_ref.rsplit("/", 1)[-1])
        if referenced not in artifacts_by_id:
            raise ValueError(f"evidence {item.id} references an artifact outside its bundle")
        artifact = artifacts_by_id[referenced]
        if item.content_sha256 != artifact.content_sha256:
            raise ValueError(f"evidence {item.id} hash does not match its artifact")
    with engine().begin() as connection:
        inserted = _insert_event(
            connection,
            run_id,
            "evidence_recorded",
            "worker",
            str(run_id),
            effect_key,
            {"artifact_count": len(artifacts), "evidence_count": len(items)},
            now,
        )
        if not inserted:
            return False
        for artifact in artifacts:
            connection.execute(
                insert(evidence_artifacts)
                .values(
                    id=artifact.id,
                    run_id=run_id,
                    source=artifact.source,
                    media_type=artifact.media_type,
                    content=artifact.content,
                    content_sha256=artifact.content_sha256,
                    retrieved_at=artifact.retrieved_at,
                )
                .on_conflict_do_nothing(index_elements=[evidence_artifacts.c.id])
            )
        for item in items:
            connection.execute(
                insert(evidence_items)
                .values(**item.model_dump(exclude={"schema_version"}))
                .on_conflict_do_nothing(index_elements=[evidence_items.c.id])
            )
    return True


def record_diagnosis(
    run_id: UUID,
    diagnosis: DiagnosisResult,
    provider: str,
    model_id: str,
    prompt_version: str,
    effect_key: str,
) -> bool:
    now = datetime.now(UTC)
    result_hypotheses = tuple(diagnosis.hypotheses)
    usage = diagnosis.usage
    with engine().begin() as connection:
        inserted = _insert_event(
            connection,
            run_id,
            "diagnosis_recorded",
            "worker",
            str(run_id),
            effect_key,
            {
                "hypothesis_count": len(result_hypotheses),
                "tool_call_count": diagnosis.tool_call_count,
                "model_id": model_id,
                "prompt_version": prompt_version,
            },
            now,
        )
        if not inserted:
            return False
        for index, request in enumerate(diagnosis.tool_requests):
            _insert_event(
                connection,
                run_id,
                "diagnosis_tool_call",
                "worker",
                str(run_id),
                f"{effect_key}:tool:{index}",
                request.model_dump(mode="json"),
                now,
            )
        for hypothesis in result_hypotheses:
            connection.execute(
                insert(hypotheses)
                .values(
                    id=hypothesis.id,
                    run_id=run_id,
                    summary=hypothesis.summary,
                    mechanism=hypothesis.mechanism,
                    supporting_evidence_ids=hypothesis.supporting_evidence_ids,
                    contradicting_evidence_ids=hypothesis.contradicting_evidence_ids,
                    confidence=hypothesis.confidence,
                    proposed_checks=[
                        check.model_dump(mode="json") for check in hypothesis.proposed_checks
                    ],
                    validation_status="validated",
                    model_id=hypothesis.model_id,
                    prompt_version=hypothesis.prompt_version,
                )
                .on_conflict_do_nothing(index_elements=[hypotheses.c.id])
            )
        usage_id = uuid5(NAMESPACE_URL, f"incidentlab:{run_id}:{prompt_version}:usage")
        connection.execute(
            insert(model_usage)
            .values(
                id=usage_id,
                run_id=run_id,
                provider=provider,
                model_id=model_id,
                prompt_version=prompt_version,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                latency_ms=usage.latency_ms,
                estimated_cost_usd=0,
            )
            .on_conflict_do_nothing(index_elements=[model_usage.c.id])
        )
    return True


def record_diagnosis_rejection(run_id: UUID, category: str, detail: str, effect_key: str) -> bool:
    now = datetime.now(UTC)
    with engine().begin() as connection:
        return _insert_event(
            connection,
            run_id,
            "diagnosis_rejected",
            "worker",
            str(run_id),
            effect_key,
            {"category": category[:128], "detail": detail[:500]},
            now,
        )


def record_repair_generation(
    run_id: UUID,
    generation: RepairGenerationResult,
    provider: str,
    model_id: str,
    prompt_version: str,
    effect_key: str,
) -> bool:
    now = datetime.now(UTC)
    with engine().begin() as connection:
        inserted = _insert_event(
            connection,
            run_id,
            "repair_generation_recorded",
            "worker",
            str(run_id),
            effect_key,
            {
                "candidate_count": len(generation.candidates),
                "rejected_count": sum(not decision.accepted for decision in generation.decisions),
                "model_id": model_id,
                "prompt_version": prompt_version,
            },
            now,
        )
        if not inserted:
            return False
        for index, decision in enumerate(generation.decisions):
            _insert_event(
                connection,
                run_id,
                "repair_policy_decision",
                "policy",
                str(run_id),
                f"{effect_key}:policy:{index}",
                {
                    "accepted": decision.accepted,
                    "category": decision.category,
                    "detail": decision.detail[:500],
                    "diff_sha256": decision.diff_sha256,
                },
                now,
            )
        for candidate in generation.candidates:
            connection.execute(
                insert(repair_candidates)
                .values(
                    id=candidate.id,
                    run_id=candidate.run_id,
                    target_commit=candidate.target_commit,
                    diff_artifact_ref=f"db://repair-candidates/{candidate.id}/diff",
                    changed_paths=candidate.changed_paths,
                    generator_id=candidate.generator_id,
                    explanation=candidate.explanation,
                    expected_behavior=candidate.expected_behavior,
                    unified_diff=candidate.unified_diff,
                    diff_sha256=candidate.diff_sha256,
                    policy_status=candidate.policy_status,
                    policy_version=candidate.policy_version,
                    created_at=now,
                )
                .on_conflict_do_nothing(index_elements=[repair_candidates.c.id])
            )
        usage_id = uuid5(NAMESPACE_URL, f"incidentlab:{run_id}:{prompt_version}:usage")
        connection.execute(
            insert(model_usage)
            .values(
                id=usage_id,
                run_id=run_id,
                provider=provider,
                model_id=model_id,
                prompt_version=prompt_version,
                input_tokens=generation.usage.input_tokens,
                output_tokens=generation.usage.output_tokens,
                latency_ms=generation.usage.latency_ms,
                estimated_cost_usd=0,
            )
            .on_conflict_do_nothing(index_elements=[model_usage.c.id])
        )
    return True


def record_repair_rejection(run_id: UUID, category: str, detail: str, effect_key: str) -> bool:
    now = datetime.now(UTC)
    with engine().begin() as connection:
        return _insert_event(
            connection,
            run_id,
            "repair_generation_rejected",
            "worker",
            str(run_id),
            effect_key,
            {"category": category[:128], "detail": detail[:500]},
            now,
        )


def record_verification_result(
    run_id: UUID,
    result: SandboxRunResult,
    effect_key: str,
) -> bool:
    """Persist raw check artifacts and derive outcome without trusting the manifest result."""
    candidate_id = UUID(result.candidate_id)
    verification_id = uuid5(
        NAMESPACE_URL,
        f"incidentlab:{candidate_id}:verification:{result.environment_digest}",
    )
    if len({check.name for check in result.checks}) != len(result.checks):
        raise ValueError("verification contains duplicate check names")
    artifacts: list[tuple[UUID, str, bytes, str]] = []
    persisted_checks: list[dict] = []
    for check in result.checks:
        path = Path(check.artifact_ref)
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != check.content_sha256:
            raise ValueError(f"verification artifact hash mismatch for {check.name}")
        artifact_id = uuid5(
            NAMESPACE_URL,
            f"incidentlab:{verification_id}:artifact:{check.name}:{digest}",
        )
        artifacts.append((artifact_id, check.name, content, digest))
        persisted_checks.append(
            {
                "schema_version": 1,
                "name": check.name,
                "outcome": check.outcome,
                "started_at": check.started_at,
                "finished_at": check.finished_at,
                "exit_code": check.exit_code,
                "failure_reason": check.failure_reason,
                "artifact_ref": f"/verification/artifacts/{artifact_id}",
                "content_sha256": digest,
            }
        )
    outcome = derive_outcome(result.checks)
    started_at = min(datetime.fromisoformat(check.started_at) for check in result.checks)
    finished_at = max(datetime.fromisoformat(check.finished_at) for check in result.checks)
    now = datetime.now(UTC)
    with engine().begin() as connection:
        candidate = connection.execute(
            sa.select(repair_candidates.c.id).where(
                repair_candidates.c.id == candidate_id,
                repair_candidates.c.run_id == run_id,
            )
        ).scalar_one_or_none()
        if candidate is None:
            raise ValueError("verification candidate does not belong to the run")
        inserted = _insert_event(
            connection,
            run_id,
            "verification_recorded",
            "verifier",
            str(run_id),
            effect_key,
            {
                "candidate_id": str(candidate_id),
                "outcome": outcome,
                "check_count": len(persisted_checks),
                "environment_digest": result.environment_digest,
            },
            now,
        )
        if not inserted:
            return False
        connection.execute(
            insert(verification_runs).values(
                id=verification_id,
                candidate_id=candidate_id,
                environment_digest=result.environment_digest,
                checks=persisted_checks,
                outcome=outcome,
                score_version=SCORE_VERSION,
                started_at=started_at,
                finished_at=finished_at,
            )
        )
        for artifact_id, check_name, content, digest in artifacts:
            connection.execute(
                insert(verification_artifacts).values(
                    id=artifact_id,
                    verification_id=verification_id,
                    check_name=check_name,
                    media_type="text/plain; charset=utf-8",
                    content=content,
                    content_sha256=digest,
                    created_at=now,
                )
            )
    return True


def finalize_verification_ranking(run_id: UUID, effect_key: str) -> dict:
    """Rank every candidate from persisted facts and return the workflow terminal state."""
    now = datetime.now(UTC)
    with engine().begin() as connection:
        candidate_rows = (
            connection.execute(
                sa.select(
                    repair_candidates.c.id,
                    repair_candidates.c.unified_diff,
                    repair_candidates.c.changed_paths,
                ).where(repair_candidates.c.run_id == run_id)
            )
            .mappings()
            .all()
        )
        verification_rows = (
            connection.execute(
                sa.select(verification_runs)
                .join(
                    repair_candidates,
                    verification_runs.c.candidate_id == repair_candidates.c.id,
                )
                .where(repair_candidates.c.run_id == run_id)
            )
            .mappings()
            .all()
        )
        if not candidate_rows or len(verification_rows) != len(candidate_rows):
            raise ValueError("verification is incomplete for one or more candidates")
        by_candidate = {row["candidate_id"]: row for row in verification_rows}
        facts = [
            RankingFact(
                candidate_id=row["id"],
                outcome=by_candidate[row["id"]]["outcome"],
                changed_lines=changed_line_count(row["unified_diff"]),
                changed_files=len(row["changed_paths"]),
            )
            for row in candidate_rows
        ]
        ranked = rank_candidates(facts)
        for item in ranked:
            connection.execute(
                verification_runs.update()
                .where(verification_runs.c.candidate_id == item.candidate_id)
                .values(rank=item.rank, score=item.score, score_version=SCORE_VERSION)
            )
        outcomes = [row["outcome"] for row in verification_rows]
        state = terminal_state(outcomes)
        _insert_event(
            connection,
            run_id,
            "verification_ranking_recorded",
            "verifier",
            str(run_id),
            effect_key,
            {
                "candidate_count": len(ranked),
                "verified_count": outcomes.count("PASS"),
                "terminal_state": state,
                "score_version": SCORE_VERSION,
            },
            now,
        )
    return {
        "terminal_state": state,
        "candidate_count": len(ranked),
        "verified_count": outcomes.count("PASS"),
        "score_version": SCORE_VERSION,
    }


def record_approval(
    run_id: UUID, actor: str, decision: str, policy_version: str = "approval-v1"
) -> tuple[dict, bool]:
    now = datetime.now(UTC)
    approval_id = uuid5(NAMESPACE_URL, f"incidentlab:{run_id}:generate_repair")
    with engine().begin() as connection:
        created = connection.execute(
            insert(approvals)
            .values(
                id=approval_id,
                run_id=run_id,
                actor=actor,
                action="generate_repair",
                decision=decision,
                policy_version=policy_version,
                decided_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_approvals_run_action")
            .returning(approvals.c.id)
        ).scalar_one_or_none()
        row = (
            connection.execute(
                sa.select(approvals).where(
                    approvals.c.run_id == run_id, approvals.c.action == "generate_repair"
                )
            )
            .mappings()
            .one()
        )
        if created is not None:
            _insert_event(
                connection,
                run_id,
                "repair_approval",
                actor,
                str(run_id),
                f"run:{run_id}:repair-approval",
                {"decision": decision, "policy_version": policy_version},
                now,
            )
    return dict(row), created is not None


def get_approval(run_id: UUID) -> dict | None:
    with engine().connect() as connection:
        row = (
            connection.execute(
                sa.select(approvals).where(
                    approvals.c.run_id == run_id, approvals.c.action == "generate_repair"
                )
            )
            .mappings()
            .one_or_none()
        )
    return dict(row) if row else None
