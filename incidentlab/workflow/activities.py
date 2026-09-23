"""Temporal Activities. Side effects live here, outside deterministic workflow code."""

import asyncio
import tempfile
from pathlib import Path
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from incidentlab.contracts.models import RunState
from incidentlab.db import repository
from sample_service.demo import replay


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
        results = await asyncio.to_thread(replay, Path(temporary) / "checkout.sqlite3", "pool_leak")
    statuses = [status for status, _ in results]
    activity.heartbeat("replay completed")
    if statuses != [409, 409, 503] or results[-1][1].get("error") != "database_pool_timeout":
        raise ApplicationError("scenario did not reproduce", non_retryable=True)
    payload = {"statuses": statuses, "failure": "database_pool_timeout"}
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
    return await _placeholder(
        data,
        "evidence_placeholder",
        {"status": "placeholder", "note": "Real collectors arrive in PRD Step 6."},
    )


@activity.defn(name="diagnose_placeholder")
async def diagnose_placeholder(data: dict) -> dict:
    return await _placeholder(
        data,
        "diagnosis_placeholder",
        {
            "status": "placeholder",
            "summary": "Connection pool exhausted after rejected checkout requests.",
            "source": "deterministic-step-5",
        },
    )


@activity.defn(name="generate_repair_placeholder")
async def generate_repair_placeholder(data: dict) -> dict:
    return await _placeholder(
        data,
        "repair_placeholder",
        {"status": "placeholder", "candidate_count": 1, "source": "deterministic-step-5"},
    )


@activity.defn(name="verify_placeholder")
async def verify_placeholder(data: dict) -> dict:
    activity.heartbeat("verification placeholder started")
    await asyncio.sleep(0.25)
    return await _placeholder(
        data,
        "verification_placeholder",
        {"status": "INCONCLUSIVE", "reason": "Sandbox verification arrives in PRD Step 8."},
    )


@activity.defn(name="report_placeholder")
async def report_placeholder(data: dict) -> dict:
    return await _placeholder(
        data,
        "report_placeholder",
        {"status": "placeholder", "format": "internal-json"},
    )
