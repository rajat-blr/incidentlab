"""Run the versioned offline evaluation suite and export comparable metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incidentlab.evaluation import EvaluationConfig, run_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("evaluation-results/latest"))
    args = parser.parse_args()
    report = run_evaluation(args.output, EvaluationConfig(trials=args.trials, seed=args.seed))
    print(json.dumps({"output": str(args.output), "summary": report["summary"]}, indent=2))
    if report["adversarial"] and not all(item["contained"] for item in report["adversarial"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
