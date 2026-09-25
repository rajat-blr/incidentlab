"""Live acceptance: approved Gemini repair passes policy and reaches the verifier."""

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incidentlab.sandbox.runner import DockerSandboxRunner

BASE_URL = "http://127.0.0.1:8000"
IMAGE = "incidentlab-sandbox:step8"


def request(method: str, path: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    call = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(call, timeout=10) as response:
        return json.load(response)


def wait_for_state(run_id: str, expected: set[str], timeout: float = 120) -> dict:
    deadline = time.monotonic() + timeout
    run: dict = {}
    while time.monotonic() < deadline:
        value = request("GET", f"/runs/{run_id}")
        if not isinstance(value, dict):
            raise AssertionError(f"Unexpected run response: {value}")
        run = value
        if run["state"] in expected:
            return run
        time.sleep(0.5)
    raise AssertionError(f"Run did not reach {expected}: {run}")


def wait_for_candidates(run_id: str, timeout: float = 90) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = request("GET", f"/runs/{run_id}/candidates")
        if not isinstance(candidates, list):
            raise AssertionError(f"Unexpected candidate response: {candidates}")
        if candidates:
            return candidates
        run = request("GET", f"/runs/{run_id}")
        if isinstance(run, dict) and run["state"] in {"FAILED", "CANCELLED", "CLOSED"}:
            raise AssertionError(f"Run terminated before producing a candidate: {run}")
        time.sleep(0.5)
    raise AssertionError("Approved run did not produce a repair candidate")


def main() -> None:
    subprocess.run(
        ["docker", "build", "-f", "Dockerfile.sandbox", "-t", IMAGE, "."],
        check=True,
    )
    created = request(
        "POST",
        "/runs",
        {
            "scenario_id": "pool-exhaustion",
            "idempotency_key": f"step9-live-{uuid.uuid4().hex}",
        },
    )
    if not isinstance(created, dict):
        raise AssertionError(f"Unexpected create response: {created}")
    run_id = created["id"]
    wait_for_state(run_id, {"AWAITING_REPAIR_APPROVAL", "FAILED"})
    before = request("GET", f"/runs/{run_id}/candidates")
    if before != []:
        raise AssertionError("Repair candidate existed before human approval")

    request(
        "POST",
        f"/runs/{run_id}/repair-approval",
        {"actor": "step9-repair-check", "decision": "approved"},
    )
    candidates = wait_for_candidates(run_id)
    if not 1 <= len(candidates) <= 2:
        raise AssertionError(f"Expected one or two candidates, got {len(candidates)}")
    for candidate in candidates:
        digest = hashlib.sha256(candidate["unified_diff"].encode()).hexdigest()
        if digest != candidate["diff_sha256"]:
            raise AssertionError("Candidate diff hash does not match its content")
        if candidate["changed_paths"] != ["sample_service/app.py"]:
            raise AssertionError(f"Candidate escaped the path allowlist: {candidate}")
        if candidate["policy_status"] != "accepted":
            raise AssertionError(f"Candidate was not policy accepted: {candidate}")

    verifier_results = []
    with tempfile.TemporaryDirectory(prefix="incidentlab-step9-artifacts-") as temporary:
        runner = DockerSandboxRunner(Path.cwd(), Path(temporary), image=IMAGE)
        for candidate in candidates:
            verifier_results.append(
                runner.run(
                    candidate["target_commit"],
                    candidate["unified_diff"],
                    candidate_id=candidate["id"],
                )
            )
    if not verifier_results:
        raise AssertionError("No accepted candidate reached the independent verifier")

    request(
        "POST",
        f"/runs/{run_id}/cancel",
        {"actor": "step9-repair-check"},
    )
    final = wait_for_state(run_id, {"FAILED", "CANCELLED"}, timeout=30)
    if final["state"] != "CANCELLED":
        raise AssertionError(f"Step 9 handoff did not cancel cleanly: {final}")
    events = request("GET", f"/runs/{run_id}/events")
    if not isinstance(events, list):
        raise AssertionError("Unexpected events response")
    kinds = [event["kind"] for event in events]
    required = {"repair_approval", "repair_generation_recorded", "repair_policy_decision"}
    if not required.issubset(kinds):
        raise AssertionError(f"Missing repair audit events: {required - set(kinds)}")
    if kinds.index("repair_approval") > kinds.index("repair_generation_recorded"):
        raise AssertionError("Repair generation was recorded before approval")

    print(
        json.dumps(
            {
                "run_id": run_id,
                "final_state": final["state"],
                "candidate_count": len(candidates),
                "candidate_hashes_valid": True,
                "policy_version": candidates[0]["policy_version"],
                "verifier_outcomes": [result.outcome for result in verifier_results],
                "accepted_candidates_reached_verifier": len(verifier_results),
                "approval_preceded_generation": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"HTTP {error.code}: {error.read().decode()}") from error
