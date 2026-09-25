"""Fixed incident checks copied into the sandbox image, not supplied by a patch."""

import argparse
import json
import sys
import tempfile
from pathlib import Path


def run_check(mode: str, trials: int) -> dict:
    sys.path.insert(0, "/workspace")
    from sample_service.demo import replay

    expected = {
        "baseline": [409, 409, 503],
        "healthy": [409, 409, 200],
        "repaired": [409, 409, 200],
    }[mode]
    fault_mode = "off" if mode == "healthy" else "pool_leak"
    matches = 0
    observed: list[list[int]] = []
    with tempfile.TemporaryDirectory(prefix="incidentlab-sandbox-") as temporary:
        database = Path(temporary) / "checkout.sqlite3"
        for _ in range(trials):
            statuses = [status for status, _ in replay(database, fault_mode)]
            observed.append(statuses)
            matches += statuses == expected
    return {
        "mode": mode,
        "fault_mode": fault_mode,
        "trials": trials,
        "matches": matches,
        "expected": expected,
        "observed": observed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("baseline", "healthy", "repaired"))
    parser.add_argument("--trials", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.trials <= 20:
        parser.error("--trials must be between 1 and 20")
    result = run_check(args.mode, args.trials)
    print(json.dumps(result, sort_keys=True))
    if result["matches"] != result["trials"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
