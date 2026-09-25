"""Trusted verifier daemon that drains runs waiting for sandbox verification."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path

from incidentlab.contracts.models import RunState
from incidentlab.db import repository
from incidentlab.verification.host import signal_verification_complete, verify_run_candidates

LOGGER = logging.getLogger("incidentlab.verifier")


def ensure_sandbox_image(repository_path: Path, image: str) -> None:
    result = subprocess.run(
        [
            "docker",
            "build",
            "--file",
            str(repository_path / "Dockerfile.sandbox"),
            "--tag",
            image,
            str(repository_path),
        ],
        check=False,
    )
    if result.returncode:
        raise RuntimeError("could not build the trusted sandbox image")


def drain_once(repository_path: Path, runtime_root: Path, image: str) -> int:
    processed = 0
    for run in repository.list_runs(state=RunState.VERIFYING, limit=50):
        candidates = repository.list_repair_candidates(run.id)
        completed = {item.candidate_id for item in repository.list_verifications(run.id)}
        if not candidates:
            LOGGER.warning("run %s is VERIFYING without candidates", run.id)
            continue
        if any(candidate.id not in completed for candidate in candidates):
            LOGGER.info("verifying %s (%s)", run.id, run.scenario_id)
            verify_run_candidates(
                run.id,
                repository_path,
                image=image,
                runtime_root=runtime_root,
            )
        asyncio.run(signal_verification_complete(run.id))
        processed += 1
        LOGGER.info("signaled verification completion for %s", run.id)
    return processed


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    repository_path = Path(os.environ["HOST_REPOSITORY_PATH"]).resolve()
    runtime_root = Path(os.environ["VERIFIER_RUNTIME_ROOT"]).resolve()
    image = os.environ.get("SANDBOX_IMAGE", "incidentlab-sandbox:step8")
    interval = max(1.0, float(os.environ.get("VERIFIER_POLL_SECONDS", "2")))
    ensure_sandbox_image(repository_path, image)
    LOGGER.info("trusted verifier ready")
    while True:
        try:
            processed = drain_once(repository_path, runtime_root, image)
            time.sleep(0.25 if processed else interval)
        except Exception:
            LOGGER.exception("verification pass failed; retrying")
            time.sleep(interval)


if __name__ == "__main__":
    main()
