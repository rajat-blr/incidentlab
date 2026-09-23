"""Acceptance check: duplicate start, worker crash, resume, approval, and no duplicate effects."""

import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid

BASE_URL = "http://127.0.0.1:8000"


def request(method: str, path: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    call = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(call, timeout=5) as response:
        return json.load(response)


def wait_for_state(run_id: str, expected: set[str], timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = request("GET", f"/runs/{run_id}")
        if run["state"] in expected:
            return run
        time.sleep(0.25)
    raise AssertionError(f"Run did not reach {expected}: {run}")


def main() -> None:
    key = f"step5-restart-{uuid.uuid4().hex}"
    body = {"scenario_id": "pool-exhaustion", "idempotency_key": key}
    first = request("POST", "/runs", body)
    second = request("POST", "/runs", body)
    if first["id"] != second["id"]:
        raise AssertionError("Duplicate idempotency key created two runs")
    run_id = first["id"]
    wait_for_state(run_id, {"AWAITING_REPAIR_APPROVAL"})

    subprocess.run(["docker", "compose", "kill", "worker"], check=True)
    try:
        approval = {"actor": "step5-restart-check", "decision": "approved"}
        request("POST", f"/runs/{run_id}/repair-approval", approval)
        request("POST", f"/runs/{run_id}/repair-approval", approval)
    finally:
        subprocess.run(["docker", "compose", "start", "worker"], check=True)

    final = wait_for_state(run_id, {"COMPLETED", "FAILED", "CANCELLED"})
    if final["state"] != "COMPLETED":
        raise AssertionError(f"Restarted run did not complete: {final}")
    events = request("GET", f"/runs/{run_id}/events")
    states = [event["details"]["state"] for event in events if event["kind"] == "state_changed"]
    if len(states) != len(set(states)):
        raise AssertionError(f"Duplicate state side effects: {states}")
    print(
        json.dumps(
            {
                "run_id": run_id,
                "final_state": final["state"],
                "states": states,
                "event_count": len(events),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"HTTP {error.code}: {error.read().decode()}") from error
