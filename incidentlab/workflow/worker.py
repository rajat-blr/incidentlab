"""Temporal worker process for IncidentLab runs."""

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from incidentlab.workflow.activities import (
    collect_evidence_placeholder,
    diagnose_placeholder,
    generate_repair_placeholder,
    report_placeholder,
    reproduce_incident_activity,
    transition_run_activity,
    verify_placeholder,
)
from incidentlab.workflow.incident import IncidentWorkflow

TASK_QUEUE = "incidentlab-runs-v1"


async def run_worker() -> None:
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "temporal:7233"))
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[IncidentWorkflow],
        activities=[
            transition_run_activity,
            reproduce_incident_activity,
            collect_evidence_placeholder,
            diagnose_placeholder,
            generate_repair_placeholder,
            verify_placeholder,
            report_placeholder,
        ],
    )
    await worker.run()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
