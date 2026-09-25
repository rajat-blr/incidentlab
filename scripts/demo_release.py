"""Run the release demo: two incidents, recovery controls, and evaluation export."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incidentlab.evaluation import EvaluationConfig, run_evaluation
from sample_service.demo import replay, replay_inventory_underflow


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="incidentlab-release-demo-") as temporary:
        root = Path(temporary)
        pool_failure = replay(root / "pool-failure.sqlite3", "pool_leak")
        pool_recovery = replay(root / "pool-recovery.sqlite3", "off")
        underflow_failure = replay_inventory_underflow(
            root / "underflow-failure.sqlite3", "inventory_underflow"
        )
        underflow_recovery = replay_inventory_underflow(root / "underflow-recovery.sqlite3", "off")
        output = Path("evaluation-results/demo")
        evaluation = run_evaluation(output, EvaluationConfig(trials=1, seed=7))
    result = {
        "pool_exhaustion": {
            "failure": [status for status, _ in pool_failure],
            "recovery_after_reset": [status for status, _ in pool_recovery],
        },
        "inventory_underflow": {
            "failure": underflow_failure,
            "recovery_after_reset": underflow_recovery,
        },
        "evaluation_report": str(output / "report.json"),
        "adversarial_cases_contained": sum(item["contained"] for item in evaluation["adversarial"]),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    expected = (
        result["pool_exhaustion"]["failure"] == [409, 409, 503]
        and result["pool_exhaustion"]["recovery_after_reset"] == [409, 409, 200]
        and underflow_failure[0][1].get("remaining_inventory") == -1
        and underflow_recovery[0][0] == 409
    )
    if not expected:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
