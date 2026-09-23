"""IncidentLab HTTP API for scenarios and durable Step 5 runs."""

import asyncio
import os
import socket
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, text
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.service import RPCError

from incidentlab.contracts.models import (
    IncidentRun,
    RepairApprovalRequest,
    RunCancelRequest,
    RunCreateRequest,
    RunState,
    ScenarioManifest,
    ScenarioSummary,
)
from incidentlab.db import repository
from incidentlab.workflow.incident import IncidentWorkflow
from incidentlab.workflow.worker import TASK_QUEUE

app = FastAPI(title="IncidentLab", version="0.1.0")


def scenario_root() -> Path:
    return Path(os.environ.get("SCENARIO_ROOT", "scenarios"))


def repository_commit() -> str | None:
    configured = os.environ.get("REPOSITORY_COMMIT")
    if configured:
        return configured if len(configured) == 40 else None
    git_dir = Path(os.environ.get("REPOSITORY_GIT_DIR", "/repository/.git"))
    head = git_dir / "HEAD"
    if not head.is_file():
        return None
    value = head.read_text().strip()
    if not value.startswith("ref: "):
        return value if len(value) == 40 else None
    reference = value.removeprefix("ref: ")
    loose_ref = git_dir / reference
    if loose_ref.is_file():
        return loose_ref.read_text().strip()
    packed_refs = git_dir / "packed-refs"
    if packed_refs.is_file():
        for line in packed_refs.read_text().splitlines():
            if line and not line.startswith(("#", "^")):
                commit, name = line.split(" ", 1)
                if name == reference:
                    return commit
    return None


def load_scenario_summaries(root: Path) -> list[ScenarioSummary]:
    scenarios = []
    for path in sorted(root.glob("*.public.json")):
        manifest = ScenarioManifest.model_validate_json(path.read_text())
        scenarios.append(
            ScenarioSummary(
                id=manifest.id,
                version=manifest.version,
                service=manifest.service,
                description=manifest.description,
            )
        )
    return scenarios


def load_scenario(root: Path, scenario_id: str) -> ScenarioManifest | None:
    path = root / f"{scenario_id}.public.json"
    if not path.is_file():
        return None
    return ScenarioManifest.model_validate_json(path.read_text())


async def temporal_client() -> Client:
    return await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "temporal:7233"))


def require_run(run_id: UUID) -> IncidentRun:
    run = repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return run


def check_database() -> None:
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def check_temporal() -> None:
    host, port = os.environ.get("TEMPORAL_ADDRESS", "temporal:7233").rsplit(":", 1)
    with socket.create_connection((host, int(port)), timeout=2):
        pass


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    try:
        await asyncio.to_thread(check_database)
        await asyncio.to_thread(check_temporal)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=503, detail="dependency_unavailable") from error
    return {"status": "ready"}


@app.get("/scenarios", response_model=list[ScenarioSummary])
def scenarios() -> list[ScenarioSummary]:
    return load_scenario_summaries(scenario_root())


@app.post("/runs", response_model=IncidentRun, status_code=202)
async def create_run(request: RunCreateRequest) -> IncidentRun:
    manifest = load_scenario(scenario_root(), request.scenario_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="scenario_not_found")
    pinned_commit = repository_commit()
    if not pinned_commit:
        raise HTTPException(status_code=503, detail="repository_commit_not_configured")
    run, _ = await asyncio.to_thread(
        repository.create_or_get_run,
        manifest.id,
        manifest.version,
        request.idempotency_key,
        pinned_commit,
    )
    try:
        client = await temporal_client()
        await client.start_workflow(
            IncidentWorkflow.run,
            {
                "run_id": str(run.id),
                "scenario_id": run.scenario_id,
                "scenario_version": run.scenario_version,
            },
            id=run.workflow_id,
            task_queue=TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    except RPCError as error:
        raise HTTPException(status_code=503, detail="workflow_service_unavailable") from error
    return run


@app.get("/runs/{run_id}", response_model=IncidentRun)
async def read_run(run_id: UUID) -> IncidentRun:
    return await asyncio.to_thread(require_run, run_id)


@app.get("/runs/{run_id}/events")
async def read_events(run_id: UUID) -> list[dict]:
    await asyncio.to_thread(require_run, run_id)
    return await asyncio.to_thread(repository.list_events, run_id)


@app.post("/runs/{run_id}/repair-approval")
async def repair_approval(run_id: UUID, request: RepairApprovalRequest) -> dict:
    run = await asyncio.to_thread(require_run, run_id)
    existing = await asyncio.to_thread(repository.get_approval, run_id)
    if existing and existing["decision"] != request.decision:
        raise HTTPException(status_code=409, detail="approval_already_decided")
    if existing and run.state != RunState.AWAITING_REPAIR_APPROVAL:
        return {"run_id": str(run_id), "decision": existing["decision"]}
    if not existing and run.state != RunState.AWAITING_REPAIR_APPROVAL:
        raise HTTPException(status_code=409, detail="run_not_awaiting_repair_approval")
    if not existing:
        existing, _ = await asyncio.to_thread(
            repository.record_approval, run_id, request.actor, request.decision
        )
    try:
        client = await temporal_client()
        await client.get_workflow_handle(run.workflow_id).signal(
            IncidentWorkflow.repair_approval, request.decision
        )
    except RPCError as error:
        raise HTTPException(status_code=503, detail="workflow_service_unavailable") from error
    return {"run_id": str(run_id), "decision": existing["decision"]}


@app.post("/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: UUID, request: RunCancelRequest) -> dict:
    run = await asyncio.to_thread(require_run, run_id)
    if run.state == RunState.CANCELLED:
        return {"run_id": str(run_id), "cancel_requested": True}
    if run.state in {
        RunState.COMPLETED,
        RunState.CLOSED,
        RunState.FAILED,
        RunState.INCONCLUSIVE,
        RunState.NO_VERIFIED_CANDIDATE,
    }:
        raise HTTPException(status_code=409, detail="run_already_terminal")
    try:
        client = await temporal_client()
        await client.get_workflow_handle(run.workflow_id).signal(
            IncidentWorkflow.request_cancel, request.actor
        )
    except RPCError as error:
        raise HTTPException(status_code=503, detail="workflow_service_unavailable") from error
    return {"run_id": str(run_id), "cancel_requested": True}
