"""Live acceptance: persist before/after facts and rank verified candidates."""

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://incidentlab:incidentlab-local@127.0.0.1:55432/incidentlab",
)
os.environ.setdefault("TEMPORAL_ADDRESS", "127.0.0.1:7233")

from incidentlab.verification.host import verify_and_signal

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


def get_bytes(path: str) -> tuple[bytes, str]:
    with urllib.request.urlopen(BASE_URL + path, timeout=10) as response:
        return response.read(), response.headers["X-Content-SHA256"]


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
            "idempotency_key": f"step10-live-{uuid.uuid4().hex}",
        },
    )
    if not isinstance(created, dict):
        raise AssertionError(f"Unexpected create response: {created}")
    run_id = created["id"]
    wait_for_state(run_id, {"AWAITING_REPAIR_APPROVAL", "FAILED"})
    request(
        "POST",
        f"/runs/{run_id}/repair-approval",
        {"actor": "step10-verification-check", "decision": "approved"},
    )
    waiting = wait_for_state(run_id, {"VERIFYING", "FAILED"})
    if waiting["state"] != "VERIFYING":
        raise AssertionError(f"Run failed before verification: {waiting}")

    sandbox_results = verify_and_signal(uuid.UUID(run_id), Path.cwd(), image=IMAGE)
    final = wait_for_state(
        run_id,
        {"COMPLETED", "NO_VERIFIED_CANDIDATE", "INCONCLUSIVE", "FAILED"},
    )
    if final["state"] != "COMPLETED":
        raise AssertionError(f"Expected a verified candidate: {final}")

    verifications = request("GET", f"/runs/{run_id}/verifications")
    if not isinstance(verifications, list) or len(verifications) != len(sandbox_results):
        raise AssertionError("Every candidate must have one persisted verification")
    if [item["rank"] for item in verifications] != list(range(1, len(verifications) + 1)):
        raise AssertionError("Verification ranks are not contiguous")
    if verifications[0]["outcome"] != "PASS":
        raise AssertionError("Top-ranked candidate did not pass mandatory gates")
    artifact_count = 0
    for verification in verifications:
        if verification["score_version"] != "verification-score-v1":
            raise AssertionError("Unexpected score version")
        for check in verification["checks"]:
            content, header_digest = get_bytes(check["artifact_ref"])
            digest = hashlib.sha256(content).hexdigest()
            if digest != check["content_sha256"] or digest != header_digest:
                raise AssertionError("Persisted verification artifact hash mismatch")
            artifact_count += 1

    events = request("GET", f"/runs/{run_id}/events")
    if not isinstance(events, list):
        raise AssertionError("Unexpected events response")
    kinds = [event["kind"] for event in events]
    if "verification_recorded" not in kinds or "verification_ranking_recorded" not in kinds:
        raise AssertionError("Verification audit events are incomplete")
    print(
        json.dumps(
            {
                "run_id": run_id,
                "final_state": final["state"],
                "candidate_count": len(verifications),
                "top_outcome": verifications[0]["outcome"],
                "score_version": verifications[0]["score_version"],
                "raw_artifact_count": artifact_count,
                "all_artifact_hashes_valid": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"HTTP {error.code}: {error.read().decode()}") from error
