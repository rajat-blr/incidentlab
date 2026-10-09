"""Evaluate fresh live API runs; retain every trial, including provider failures."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sample_service.scenarios import SCENARIOS

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "CLOSED", "INCONCLUSIVE", "NO_VERIFIED_CANDIDATE"}
VERSION = "live-evaluation-v1"


class Api:
    def __init__(self, base_url: str, artifact_root: Path | None = None):
        self.base_url = base_url.rstrip("/")
        self.artifact_root = artifact_root
        self.artifacts: dict[str, dict[str, str]] = {}

    def request(self, path: str, body: dict | None = None):
        call = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(call, timeout=15) as response:
            return json.load(response)

    def artifact_valid(self, item: dict) -> bool:
        with urllib.request.urlopen(self.base_url + item["artifact_ref"], timeout=15) as response:
            content = response.read()
        digest = hashlib.sha256(content).hexdigest()
        if self.artifact_root is not None:
            self.artifact_root.mkdir(parents=True, exist_ok=True)
            (self.artifact_root / f"{digest}.txt").write_bytes(content)
            self.artifacts[item["artifact_ref"]] = {
                "path": f"artifacts/{digest}.txt",
                "sha256": digest,
            }
            (self.artifact_root.parent / "artifact-manifest.json").write_text(
                json.dumps(self.artifacts, indent=2, sort_keys=True) + "\n"
            )
        return digest == item["content_sha256"]


def score_report(report: dict, expected_model: str) -> dict:
    evidence = {item["id"]: item for item in report["evidence"]}
    hypotheses = report["hypotheses"]
    citations = [
        citation
        for hypothesis in hypotheses
        for citation in hypothesis["supporting_evidence_ids"]
        + hypothesis["contradicting_evidence_ids"]
    ]
    valid = sum(citation in evidence for citation in citations)
    gap_support = any(
        evidence.get(citation, {}).get("kind") == "gap"
        for hypothesis in hypotheses
        for citation in hypothesis["supporting_evidence_ids"]
    )
    usage = report["model_usage"]
    diagnosis_live = any(
        item["provider"] == "openai"
        and item["model_id"] == expected_model
        and item["prompt_version"].startswith("diagnosis-")
        for item in usage
    )
    repair_live = any(
        item["provider"] == "openai"
        and item["model_id"] == expected_model
        and item["prompt_version"].startswith("repair-")
        for item in usage
    )
    citations_valid = (
        bool(hypotheses and citations and valid == len(citations))
        and not gap_support
        and diagnosis_live
    )
    return {
        "reproduced": any(event["kind"] == "reproduction_recorded" for event in report["events"]),
        "citations_valid": citations_valid,
        "citation_count": len(citations),
        "resolved_citation_count": valid,
        "verified_repair": citations_valid
        and repair_live
        and report["run"]["state"] == "COMPLETED"
        and any(item["outcome"] == "PASS" for item in report["verifications"]),
        "model_ids": sorted({item["model_id"] for item in usage}),
        "prompt_versions": sorted({item["prompt_version"] for item in usage}),
        "input_tokens": sum(item["input_tokens"] for item in usage),
        "output_tokens": sum(item["output_tokens"] for item in usage),
        "estimated_cost_usd": sum(item["estimated_cost_usd"] for item in usage),
    }


def summary(rows: list[dict]) -> list[dict]:
    result = []
    for scenario in [*dict.fromkeys(row["scenario_id"] for row in rows), "all"]:
        selected = rows if scenario == "all" else [r for r in rows if r["scenario_id"] == scenario]
        count = len(selected)
        result.append(
            {
                "scenario_id": scenario,
                "trials": count,
                "reproduction_rate": sum(r["reproduced"] for r in selected) / count,
                "citation_validity": sum(r["citations_valid"] for r in selected) / count,
                "verified_repair_rate": sum(r["verified_repair"] for r in selected) / count,
                "failure_count": sum(r["failure_category"] is not None for r in selected),
                "citation_count": sum(r["citation_count"] for r in selected),
                "resolved_citation_count": sum(r["resolved_citation_count"] for r in selected),
            }
        )
    return result


def evaluate_trial(api: Api, scenario: str, trial: int, model: str, timeout: float) -> dict:
    row = {
        "scenario_id": scenario,
        "trial": trial,
        "run_id": None,
        "pinned_commit": None,
        "state": "NOT_CREATED",
        "reproduced": False,
        "citations_valid": False,
        "citation_count": 0,
        "resolved_citation_count": 0,
        "verified_repair": False,
        "failure_category": None,
    }
    started = time.monotonic()
    prefix = None
    try:
        run = api.request(
            "/runs",
            {
                "scenario_id": scenario,
                "idempotency_key": f"{VERSION}-{uuid4().hex}",
            },
        )
        row.update(run_id=run["id"], pinned_commit=run["pinned_commit"])
        prefix = f"/runs/{run['id']}"
        approved = False
        while time.monotonic() - started < timeout:
            run = api.request(prefix)
            row["state"] = run["state"]
            if run["state"] in TERMINAL:
                break
            if run["state"] == "AWAITING_REPAIR_APPROVAL" and not approved:
                # The evaluator is an explicitly named automated reviewer, not a human.
                api.request(
                    prefix + "/repair-approval",
                    {
                        "actor": VERSION,
                        "decision": "approved",
                    },
                )
                approved = True
            time.sleep(1)
        else:
            row["failure_category"] = "evaluation_timeout"
            api.request(prefix + "/cancel", {"actor": VERSION})
    except (OSError, ValueError) as error:
        row["failure_category"] = type(error).__name__
    finally:
        if prefix:
            try:
                report = api.request(prefix + "/report")
                row["report"] = report
                row["state"] = report["run"]["state"]
                row.update(score_report(report, model))
                # Resolved IDs alone are insufficient: check cited bytes and verifier logs.
                cited = {
                    citation
                    for h in report["hypotheses"]
                    for citation in h["supporting_evidence_ids"] + h["contradicting_evidence_ids"]
                }
                for item in report["evidence"]:
                    if item["id"] in cited and not api.artifact_valid(item):
                        row["citations_valid"] = False
                        row["verified_repair"] = False
                        row["failure_category"] = "citation_artifact_hash_mismatch"
                for verification in report["verifications"]:
                    for check in verification["checks"]:
                        if not api.artifact_valid(check):
                            row["verified_repair"] = False
                            row["failure_category"] = "verification_artifact_hash_mismatch"
                if not row["verified_repair"] and not row["failure_category"]:
                    rejections = [
                        event for event in report["events"] if event["kind"].endswith("_rejected")
                    ]
                    if rejections:
                        details = rejections[-1]["details"]
                        row["failure_category"] = details.get("category", "model_rejected")
                        row["failure_detail"] = details.get("detail")
                    else:
                        row["failure_category"] = (
                            report["run"].get("failure_category") or row["state"]
                        )
            except (OSError, ValueError, KeyError) as error:
                # Missing artifacts or unreadable reports cannot become success.
                row["citations_valid"] = False
                row["verified_repair"] = False
                row["failure_category"] = row["failure_category"] or type(error).__name__
        row["duration_ms"] = round((time.monotonic() - started) * 1000)
    return row


def write_results(output: Path, rows: list[dict], config: dict, started_at: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "evaluation_version": VERSION,
        "started_at": started_at,
        "config": config,
        "summary": summary(rows),
        "trials": rows,
        "limitations": [
            "Four controlled scenarios across inventory and its gateway; "
            "no generalization to unrelated applications.",
            "Citation validity checks IDs, gap handling and artifact integrity, "
            "not semantic entailment.",
            "Approval is performed by the evaluator, not a human reviewer.",
            "Provider retries inside an activity are part of one trial; "
            "recorded usage may omit rejected calls.",
        ],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (output / "failures.json").write_text(
        json.dumps(
            {
                "evaluation_version": VERSION,
                "failures": [row for row in rows if row["failure_category"]],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    flat_rows = [{k: v for k, v in row.items() if k != "report"} for row in rows]
    fields = list(dict.fromkeys(key for row in flat_rows for key in row))
    with (output / "metrics.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(flat_rows)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--model", required=True, help="Expected worker model; mismatches do not pass"
    )
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--scenarios", nargs="+", choices=tuple(SCENARIOS), default=list(SCENARIOS))
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--output", type=Path, default=Path("evaluation-results/live"))
    args = parser.parse_args()
    if not 1 <= args.trials <= 50 or args.timeout <= 0:
        parser.error("trials must be 1–50 and timeout must be positive")
    api = Api(args.base_url, args.output / "artifacts")
    api.request("/ready")  # Preflight errors are not model trials.
    config = {**vars(args), "output": str(args.output)}
    started_at = datetime.now(UTC).isoformat()
    rows = []
    for scenario in dict.fromkeys(args.scenarios):
        for trial in range(1, args.trials + 1):
            row = evaluate_trial(api, scenario, trial, args.model, args.timeout)
            rows.append(row)
            report = write_results(args.output, rows, config, started_at)
            print(json.dumps({k: v for k, v in row.items() if k != "report"}), flush=True)
    print(json.dumps(report["summary"], indent=2))
    if any(row["failure_category"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
