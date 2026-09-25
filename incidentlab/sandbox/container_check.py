"""Fixed incident checks copied into the sandbox image, not supplied by a patch."""

import argparse
import json
import sys
import tempfile
from pathlib import Path


def run_scenario_check(mode: str, trials: int, scenario: str) -> dict:
    sys.path.insert(0, "/workspace")
    from sample_service.demo import replay, replay_inventory_underflow

    definitions = {
        "pool-exhaustion": {
            "baseline": ([409, 409, 503], "pool_leak", replay),
            "healthy": ([409, 409, 200], "off", replay),
            "repaired": ([409, 409, 200], "pool_leak", replay),
        },
        "inventory-underflow": {
            "baseline": ([200], "inventory_underflow", replay_inventory_underflow),
            "healthy": ([409], "off", replay_inventory_underflow),
            "repaired": ([409], "inventory_underflow", replay_inventory_underflow),
        },
    }
    expected, fault_mode, replay_function = definitions[scenario][mode]
    matches = 0
    observed: list[list[int]] = []
    with tempfile.TemporaryDirectory(prefix="incidentlab-sandbox-") as temporary:
        database = Path(temporary) / "checkout.sqlite3"
        for _ in range(trials):
            statuses = [status for status, _ in replay_function(database, fault_mode)]
            observed.append(statuses)
            matches += statuses == expected
    return {
        "mode": mode,
        "fault_mode": fault_mode,
        "scenario": scenario,
        "trials": trials,
        "matches": matches,
        "expected": expected,
        "observed": observed,
    }


def run_check(mode: str, trials: int) -> dict:
    """Retain the Step 8 programmatic interface for the original scenario."""
    return run_scenario_check(mode, trials, "pool-exhaustion")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("baseline", "healthy", "repaired"))
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument(
        "--scenario",
        choices=("pool-exhaustion", "inventory-underflow"),
        default="pool-exhaustion",
    )
    args = parser.parse_args()
    if not 1 <= args.trials <= 20:
        parser.error("--trials must be between 1 and 20")
    result = run_scenario_check(args.mode, args.trials, args.scenario)
    print(json.dumps(result, sort_keys=True))
    if result["matches"] != result["trials"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
