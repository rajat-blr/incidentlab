"""Fixed incident checks copied into the trusted image, not supplied by a patch."""

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

# Expectations live in the trusted image, never in candidate manifests.
DEFINITIONS = {
    "pool-exhaustion": {
        "traffic": (("widget", 99), ("widget", 99), ("widget", 1)),
        "faults": ("pool_leak", "off"),
        "baseline": ([409, 409, 503], [None, None, None], 10),
        "healthy": ([409, 409, 200], [None, None, 9], 9),
    },
    "inventory-underflow": {
        "traffic": (("widget", 11),),
        "faults": ("inventory_underflow", "off"),
        "baseline": ([200], [-1], -1),
        "healthy": ([409], [None], 10),
    },
    "upstream-error-masking": {
        "traffic": (("widget", 99),),
        "faults": ("off", "status_masking"),
        "baseline": ([200], [None], 10),
        "healthy": ([409], [None], 10),
    },
    "mutation-response-cache": {
        "traffic": (("widget", 1), ("widget", 1)),
        "faults": ("off", "mutation_cache"),
        "baseline": ([200, 200], [9, 9], 9),
        "healthy": ([200, 200], [9, 8], 8),
    },
}


def run_scenario_check(mode: str, trials: int, scenario: str) -> dict:
    sys.path.insert(0, "/workspace")
    from sample_service.demo import replay_traffic

    definition = DEFINITIONS[scenario]
    expected = definition["baseline" if mode == "baseline" else "healthy"]
    fault_mode, gateway_fault = ("off", "off") if mode == "healthy" else definition["faults"]
    matches = 0
    observed = []
    with tempfile.TemporaryDirectory(prefix="incidentlab-sandbox-") as temporary:
        database = Path(temporary) / "checkout.sqlite3"
        for _ in range(trials):
            results = replay_traffic(database, fault_mode, definition["traffic"], gateway_fault)
            with sqlite3.connect(database) as connection:
                stock = connection.execute("SELECT quantity FROM inventory WHERE sku='widget'")
                quantity = stock.fetchone()[0]
            actual = (
                [status for status, _ in results],
                [body.get("remaining_inventory") for _, body in results],
                quantity,
            )
            valid = actual == expected
            if scenario == "upstream-error-masking":
                valid = valid and results[-1][1].get("error") == "out_of_stock"
            if scenario == "pool-exhaustion" and mode == "baseline":
                valid = valid and results[-1][1].get("error") == "database_pool_timeout"
            observed.append(actual)
            matches += valid
    return {
        "mode": mode,
        "fault_mode": fault_mode,
        "gateway_fault_mode": gateway_fault,
        "scenario": scenario,
        "trials": trials,
        "matches": matches,
        "expected": expected,
        "observed": observed,
    }


def run_check(mode: str, trials: int) -> dict:
    return run_scenario_check(mode, trials, "pool-exhaustion")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("baseline", "healthy", "repaired"))
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--scenario", choices=tuple(DEFINITIONS), default="pool-exhaustion")
    parser.add_argument("--preserve-inactive", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.trials <= 20:
        parser.error("--trials must be between 1 and 20")
    result = run_scenario_check(args.mode, args.trials, args.scenario)
    inactive = [
        run_scenario_check("baseline", 1, other)
        for other in DEFINITIONS
        if other != args.scenario and args.preserve_inactive
    ]
    print(json.dumps({**result, "inactive_scenarios": inactive}, sort_keys=True))
    if any(r["matches"] != r["trials"] for r in [result, *inactive]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
