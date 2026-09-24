"""Acceptance check: normalized evidence resolves to immutable, hash-matched artifacts."""

import hashlib
import json
import time
import urllib.error
import urllib.request
import uuid

BASE_URL = "http://127.0.0.1:8000"


def request_json(method: str, path: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    call = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(call, timeout=5) as response:
        return json.load(response)


def wait_for_evidence(run_id: str, timeout: float = 60) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = request_json("GET", f"/runs/{run_id}")
        if run["state"] == "FAILED":
            raise AssertionError(f"Run failed while collecting evidence: {run}")
        evidence = request_json("GET", f"/runs/{run_id}/evidence")
        if evidence:
            return evidence
        time.sleep(0.5)
    raise AssertionError("Run did not produce evidence")


def main() -> None:
    created = request_json(
        "POST",
        "/runs",
        {
            "scenario_id": "pool-exhaustion",
            "idempotency_key": f"step6-evidence-{uuid.uuid4().hex}",
        },
    )
    run_id = created["id"]
    evidence = wait_for_evidence(run_id)
    expected = {"trace": 1, "metric": 3, "log": 2, "commit": 1}
    actual = {kind: sum(item["kind"] == kind for item in evidence) for kind in expected}
    gaps = [item for item in evidence if item["kind"] == "gap"]
    if actual != expected or gaps:
        raise AssertionError(f"Incomplete normalized evidence: counts={actual}, gaps={gaps}")
    for item in evidence:
        with urllib.request.urlopen(BASE_URL + item["artifact_ref"], timeout=5) as response:
            content = response.read()
            header_hash = response.headers["X-Content-SHA256"]
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != item["content_sha256"] or header_hash != actual_hash:
            raise AssertionError(f"Artifact hash mismatch for {item['id']}")
    request_json("POST", f"/runs/{run_id}/cancel", {"actor": "step6-evidence-check"})
    print(
        json.dumps(
            {
                "run_id": run_id,
                "evidence_count": len(evidence),
                "kinds": actual,
                "all_artifacts_hash_matched": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"HTTP {error.code}: {error.read().decode()}") from error
