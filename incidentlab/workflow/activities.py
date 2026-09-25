"""Temporal Activities. Side effects live here, outside deterministic workflow code."""

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from incidentlab.contracts.models import RunState
from incidentlab.db import repository
from incidentlab.evidence.collection import collect_git_metadata, collect_telemetry, combine
from incidentlab.model_adapter.diagnosis import PROMPT_VERSION, DiagnosisError, diagnose
from incidentlab.model_adapter.gemini_adapter import GeminiDiagnosisAdapter
from incidentlab.model_adapter.gemini_repair_adapter import GeminiRepairAdapter
from incidentlab.model_adapter.repair import PROMPT_VERSION as REPAIR_PROMPT_VERSION
from incidentlab.model_adapter.repair import RepairError, generate_repairs
from incidentlab.policy.context import RepositoryContextError, read_pinned_source
from sample_service.observed_replay import replay_with_telemetry


@activity.defn(name="transition_run")
async def transition_run_activity(data: dict) -> dict:
    await asyncio.to_thread(
        repository.transition_run,
        UUID(data["run_id"]),
        RunState(data["state"]),
        data["effect_key"],
        data.get("details"),
    )
    return {"state": data["state"]}


@activity.defn(name="reproduce_incident")
async def reproduce_incident_activity(data: dict) -> dict:
    activity.heartbeat("resetting scenario")
    with tempfile.TemporaryDirectory(prefix="incidentlab-run-") as temporary:
        root = Path(temporary)
        payload = await asyncio.to_thread(
            replay_with_telemetry,
            root / "checkout.sqlite3",
            data["run_id"],
            root,
        )
    statuses = payload["statuses"]
    activity.heartbeat("replay completed")
    if statuses != [409, 409, 503] or payload["failure"] != "database_pool_timeout":
        raise ApplicationError("scenario did not reproduce", non_retryable=True)
    await asyncio.to_thread(
        repository.record_output,
        UUID(data["run_id"]),
        "reproduction",
        payload,
        data["effect_key"],
    )
    return payload


async def _placeholder(data: dict, column: str, payload: dict) -> dict:
    activity.heartbeat(f"recording {column}")
    await asyncio.to_thread(
        repository.record_output,
        UUID(data["run_id"]),
        column,
        payload,
        data["effect_key"],
    )
    return payload


@activity.defn(name="collect_evidence_placeholder")
async def collect_evidence_placeholder(data: dict) -> dict:
    """The legacy activity name is retained so Step 5 workflow histories remain replayable."""
    run_id = UUID(data["run_id"])
    run = await asyncio.to_thread(repository.get_run, run_id)
    if run is None:
        raise ApplicationError("run not found", non_retryable=True)
    start = datetime.fromisoformat(data.get("observed_start") or datetime.now(UTC).isoformat())
    end = datetime.fromisoformat(data.get("observed_end") or start.isoformat())
    telemetry = await asyncio.to_thread(
        collect_telemetry,
        run_id,
        start,
        end,
        data.get("request_ids", []),
    )
    git = await asyncio.to_thread(
        collect_git_metadata,
        run_id,
        data.get("pinned_commit") or run.pinned_commit,
        Path(os.environ.get("REPOSITORY_GIT_DIR", "/repository/.git")),
    )
    bundle = combine(telemetry, git)
    await asyncio.to_thread(
        repository.record_evidence_bundle,
        run_id,
        bundle,
        data["effect_key"],
    )
    return {
        "status": "collected",
        "artifact_count": len(bundle.artifacts),
        "evidence_count": len(bundle.items),
        "gap_count": sum(item.kind == "gap" for item in bundle.items),
    }


@activity.defn(name="diagnose_placeholder")
async def diagnose_placeholder(data: dict) -> dict:
    """The legacy activity name is retained so existing workflow histories remain replayable."""
    run_id = UUID(data["run_id"])
    evidence = await asyncio.to_thread(repository.list_evidence, run_id)
    try:
        adapter = GeminiDiagnosisAdapter()
        try:
            result = await asyncio.to_thread(
                diagnose,
                run_id,
                evidence,
                adapter,
                repository.get_evidence_artifact,
            )
        finally:
            adapter.close()
    except DiagnosisError as error:
        await asyncio.to_thread(
            repository.record_diagnosis_rejection,
            run_id,
            type(error).__name__,
            str(error),
            f"{data['effect_key']}:rejected",
        )
        raise ApplicationError(str(error), non_retryable=True) from error
    await asyncio.to_thread(
        repository.record_diagnosis,
        run_id,
        result,
        adapter.provider,
        adapter.model_id,
        PROMPT_VERSION,
        data["effect_key"],
    )
    return {
        "status": "validated",
        "hypothesis_count": len(result.hypotheses),
        "tool_call_count": result.tool_call_count,
        "model_id": adapter.model_id,
        "prompt_version": PROMPT_VERSION,
    }


@activity.defn(name="generate_repair_placeholder")
async def generate_repair_placeholder(data: dict) -> dict:
    """The legacy name remains stable while the activity performs real generation."""
    run_id = UUID(data["run_id"])
    approval = await asyncio.to_thread(repository.get_approval, run_id)
    if approval is None or approval["decision"] != "approved":
        error = RepairError("repair generation requires recorded approval")
        await asyncio.to_thread(
            repository.record_repair_rejection,
            run_id,
            "approval",
            str(error),
            f"{data['effect_key']}:rejected",
        )
        raise ApplicationError(str(error), non_retryable=True) from error
    run = await asyncio.to_thread(repository.get_run, run_id)
    hypotheses = await asyncio.to_thread(repository.list_hypotheses, run_id)
    reproduction = await asyncio.to_thread(repository.get_run_output, run_id, "reproduction")
    if run is None or not hypotheses or reproduction is None:
        error = RepairError("repair inputs are incomplete")
        await asyncio.to_thread(
            repository.record_repair_rejection,
            run_id,
            "inputs",
            str(error),
            f"{data['effect_key']}:rejected",
        )
        raise ApplicationError(str(error), non_retryable=True) from error
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    hypothesis = min(
        hypotheses,
        key=lambda item: (confidence_order[item.confidence], str(item.id)),
    )
    try:
        source = await asyncio.to_thread(
            read_pinned_source,
            Path(os.environ.get("REPOSITORY_GIT_DIR", "/repository/.git")),
            run.pinned_commit,
            "sample_service/app.py",
        )
        adapter = GeminiRepairAdapter()
        try:
            result = await asyncio.to_thread(
                generate_repairs,
                run_id,
                run.pinned_commit,
                hypothesis,
                reproduction,
                source,
                adapter,
            )
        finally:
            adapter.close()
    except (RepairError, RepositoryContextError) as error:
        await asyncio.to_thread(
            repository.record_repair_rejection,
            run_id,
            type(error).__name__,
            str(error),
            f"{data['effect_key']}:rejected",
        )
        raise ApplicationError(str(error), non_retryable=True) from error
    await asyncio.to_thread(
        repository.record_repair_generation,
        run_id,
        result,
        adapter.provider,
        adapter.model_id,
        REPAIR_PROMPT_VERSION,
        data["effect_key"],
    )
    if not result.candidates:
        raise ApplicationError(
            "all generated repair candidates were rejected by policy",
            non_retryable=True,
        )
    return {
        "status": "validated",
        "candidate_count": len(result.candidates),
        "rejected_count": sum(not decision.accepted for decision in result.decisions),
        "model_id": adapter.model_id,
        "prompt_version": REPAIR_PROMPT_VERSION,
    }


@activity.defn(name="verify_placeholder")
async def verify_placeholder(data: dict) -> dict:
    activity.heartbeat("verification placeholder started")
    await asyncio.sleep(0.25)
    return await _placeholder(
        data,
        "verification_placeholder",
        {
            "status": "INCONCLUSIVE",
            "reason": "Independent verifier persistence and ranking arrive in PRD Step 10.",
        },
    )


@activity.defn(name="finalize_verification")
async def finalize_verification(data: dict) -> dict:
    try:
        return await asyncio.to_thread(
            repository.finalize_verification_ranking,
            UUID(data["run_id"]),
            data["effect_key"],
        )
    except ValueError as error:
        raise ApplicationError(str(error), non_retryable=True) from error


@activity.defn(name="report_placeholder")
async def report_placeholder(data: dict) -> dict:
    return await _placeholder(
        data,
        "report_placeholder",
        {"status": "placeholder", "format": "internal-json"},
    )
