"""Add recorded live trials to the browser's saved demonstration dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incidentlab.reporting import render_markdown
from scripts.evaluate_live import Api

EVENT_STAGES = (
    "run_created",
    "reproduction_recorded",
    "diagnosis_recorded",
    "repair_approval",
    "repair_policy_decision",
    "verification_recorded",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluation", type=Path)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--scenarios", nargs="+", help="First verified trial per scenario")
    selection.add_argument(
        "--all-trials", action="store_true", help="Include failures and full audits"
    )
    parser.add_argument("--dataset", type=Path, default=Path("frontend/src/demo-data/dataset.json"))
    args = parser.parse_args()
    evaluation = json.loads((args.evaluation / "report.json").read_text())
    dataset = json.loads(args.dataset.read_text())
    api = Api(evaluation["config"]["base_url"], args.evaluation / "artifacts")
    manifest = args.evaluation / "artifact-manifest.json"
    api.artifacts = json.loads(manifest.read_text()) if manifest.exists() else {}
    # Validate every requested scenario before changing the dataset.
    selected = []
    for scenario in args.scenarios or []:
        trial = next(
            (
                row
                for row in evaluation["trials"]
                if row["scenario_id"] == scenario and row["verified_repair"]
            ),
            None,
        )
        if trial is None:
            parser.error(f"no verified live trial for {scenario}")
        selected.append(trial["report"])
    if args.all_trials:
        selected = [trial["report"] for trial in evaluation["trials"]]
    for report in selected:
        run = report["run"]
        items = report["evidence"] + [c for v in report["verifications"] for c in v["checks"]]
        artifacts = {}
        for item in items:
            artifact_path = args.evaluation / "artifacts" / f"{item['content_sha256']}.txt"
            if not artifact_path.exists() and not api.artifact_valid(item):
                raise ValueError("artifact hash mismatch")
            content = artifact_path.read_bytes()
            if hashlib.sha256(content).hexdigest() != item["content_sha256"]:
                raise ValueError("artifact hash mismatch")
            artifacts[item["artifact_ref"]] = content.decode()
        # Guided replays use six visible stages; retain the original event data at each stage.
        events = report["events"] if args.all_trials else [
            next(e for e in report["events"] if e["kind"] == kind) for kind in EVENT_STAGES
        ]
        dataset["run_data"][run["id"]] = {
            **{
                key: report[key]
                for key in (
                    "evidence",
                    "hypotheses",
                    "candidates",
                    "verifications",
                    "model_usage",
                )
            },
            "events": events,
            "artifacts": artifacts,
            "report_markdown": render_markdown(report),
        }
        dataset["runs"] = [r for r in dataset["runs"] if r["id"] != run["id"]] + [run]
        manifest = json.loads(Path(f"scenarios/{run['scenario_id']}.public.json").read_text())
        summary = {
            "schema_version": 1,
            **{
                key: manifest[key]
                for key in (
                    "id",
                    "version",
                    "service",
                    "description",
                )
            },
        }
        dataset["scenarios"] = [s for s in dataset["scenarios"] if s["id"] != run["scenario_id"]]
        dataset["scenarios"].append(summary)
    args.dataset.write_text(json.dumps(dataset, indent=2) + "\n")
    print(f"Exported {len(selected)} recorded live runs into {args.dataset}")


if __name__ == "__main__":
    main()
