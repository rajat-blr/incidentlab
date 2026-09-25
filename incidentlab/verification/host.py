"""Trusted host-side verifier orchestration; this process owns Docker access."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from uuid import UUID

from temporalio.client import Client

from incidentlab.db import repository
from incidentlab.sandbox.runner import DockerSandboxRunner, SandboxRunResult
from incidentlab.workflow.incident import IncidentWorkflow


def verify_run_candidates(
    run_id: UUID,
    repository_path: Path,
    *,
    image: str = "incidentlab-sandbox:step8",
) -> tuple[SandboxRunResult, ...]:
    run = repository.get_run(run_id)
    if run is None:
        raise ValueError("run does not exist")
    candidates = repository.list_repair_candidates(run_id)
    if not candidates:
        raise ValueError("run has no repair candidates")
    results = []
    with tempfile.TemporaryDirectory(prefix="incidentlab-verification-") as temporary:
        runner = DockerSandboxRunner(repository_path, Path(temporary), image=image)
        for candidate in candidates:
            result = runner.run(
                candidate.target_commit,
                candidate.unified_diff,
                candidate_id=str(candidate.id),
                scenario_id=run.scenario_id,
            )
            repository.record_verification_result(
                run_id,
                result,
                f"run:{run_id}:verification:{candidate.id}",
            )
            results.append(result)
    return tuple(results)


async def signal_verification_complete(run_id: UUID) -> None:
    run = repository.get_run(run_id)
    if run is None:
        raise ValueError("run does not exist")
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233"))
    await client.get_workflow_handle(run.workflow_id).signal(
        IncidentWorkflow.verification_completed
    )


def verify_and_signal(
    run_id: UUID,
    repository_path: Path,
    *,
    image: str = "incidentlab-sandbox:step8",
) -> tuple[SandboxRunResult, ...]:
    results = verify_run_candidates(run_id, repository_path, image=image)
    asyncio.run(signal_verification_complete(run_id))
    return results
