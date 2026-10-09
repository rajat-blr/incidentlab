"""Run all four controlled incidents, healthy controls, and offline evaluation."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incidentlab.evaluation import EvaluationConfig, run_evaluation
from sample_service.demo import replay_scenario
from sample_service.scenarios import SCENARIOS, matches_results


def main() -> None:
    output = Path("evaluation-results/demo")
    scenarios = {}
    with tempfile.TemporaryDirectory(prefix="incidentlab-release-demo-") as temporary:
        root = Path(temporary)
        for scenario_id in SCENARIOS:
            database = root / f"{scenario_id}.sqlite3"
            failure = replay_scenario(database, scenario_id)
            recovery = replay_scenario(database, scenario_id, healthy=True)
            scenarios[scenario_id] = {
                "failure": failure,
                "healthy_control": recovery,
                "reproduced": matches_results(scenario_id, failure, healthy=False),
                "recovered": matches_results(scenario_id, recovery, healthy=True),
            }
        evaluation = run_evaluation(output, EvaluationConfig(trials=1, seed=7))
    print(
        json.dumps(
            {
                "scenarios": scenarios,
                "evaluation_report": str(output / "report.json"),
                "adversarial_cases_contained": sum(
                    item["contained"] for item in evaluation["adversarial"]
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if not all(item["reproduced"] and item["recovered"] for item in scenarios.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
