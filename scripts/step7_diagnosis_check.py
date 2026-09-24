"""Live acceptance check for evidence-grounded Gemini diagnosis."""

import json
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
    with urllib.request.urlopen(call, timeout=10) as response:
        return json.load(response)


def wait_for_state(run_id: str, expected: set[str], timeout: float = 120) -> dict:
    deadline = time.monotonic() + timeout
    run: dict = {}
    while time.monotonic() < deadline:
        result = request("GET", f"/runs/{run_id}")
        if not isinstance(result, dict):
            raise AssertionError(f"Unexpected run response: {result}")
        run = result
        if run["state"] in expected:
            return run
        time.sleep(0.5)
    raise AssertionError(f"Run did not reach {expected}: {run}")


def main() -> None:
    body = {
        "scenario_id": "pool-exhaustion",
        "idempotency_key": f"step7-live-{uuid.uuid4().hex}",
    }
    created = request("POST", "/runs", body)
    if not isinstance(created, dict):
        raise AssertionError(f"Unexpected create response: {created}")
    run_id = created["id"]

    reached = wait_for_state(
        run_id,
        {"AWAITING_REPAIR_APPROVAL", "FAILED", "CANCELLED"},
    )
    if reached["state"] != "AWAITING_REPAIR_APPROVAL":
        raise AssertionError(f"Diagnosis did not reach approval: {reached}")

    evidence = request("GET", f"/runs/{run_id}/evidence")
    hypotheses = request("GET", f"/runs/{run_id}/hypotheses")
    events = request("GET", f"/runs/{run_id}/events")
    if not isinstance(evidence, list) or not isinstance(hypotheses, list):
        raise AssertionError("Unexpected evidence or hypothesis response")
    if not isinstance(events, list):
        raise AssertionError("Unexpected events response")
    if not 1 <= len(hypotheses) <= 3:
        raise AssertionError(f"Expected 1-3 hypotheses, got {len(hypotheses)}")

    evidence_by_id = {item["id"]: item for item in evidence}
    for hypothesis in hypotheses:
        cited = hypothesis["supporting_evidence_ids"] + hypothesis["contradicting_evidence_ids"]
        missing = sorted(set(cited) - evidence_by_id.keys())
        if missing:
            raise AssertionError(f"Hypothesis cites missing evidence: {missing}")
        gaps = [
            evidence_id
            for evidence_id in hypothesis["supporting_evidence_ids"]
            if evidence_by_id[evidence_id]["kind"] == "gap"
        ]
        if gaps:
            raise AssertionError(f"Hypothesis uses gaps as support: {gaps}")
        if not hypothesis["model_id"] or hypothesis["prompt_version"] != "diagnosis-v1":
            raise AssertionError(f"Missing model provenance: {hypothesis}")

    if not any(event["kind"] == "diagnosis_recorded" for event in events):
        raise AssertionError("Missing diagnosis_recorded audit event")

    request(
        "POST",
        f"/runs/{run_id}/repair-approval",
        {"actor": "step7-diagnosis-check", "decision": "rejected"},
    )
    final = wait_for_state(run_id, {"CLOSED", "FAILED", "CANCELLED"}, timeout=30)
    if final["state"] != "CLOSED":
        raise AssertionError(f"Rejected run did not close: {final}")

    print(
        json.dumps(
            {
                "run_id": run_id,
                "final_state": final["state"],
                "evidence_count": len(evidence),
                "hypothesis_count": len(hypotheses),
                "model_ids": sorted({item["model_id"] for item in hypotheses}),
                "all_citations_resolved": True,
                "gaps_used_as_support": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"HTTP {error.code}: {error.read().decode()}") from error
