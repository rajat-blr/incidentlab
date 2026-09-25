"""Run all accepted candidates for one VERIFYING run and persist their facts."""

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incidentlab.verification.host import verify_and_signal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=UUID)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--image", default="incidentlab-sandbox:step8")
    args = parser.parse_args()
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://incidentlab:incidentlab-local@127.0.0.1:55432/incidentlab",
    )
    results = verify_and_signal(
        args.run_id,
        args.repository,
        image=args.image,
    )
    print(
        json.dumps(
            {
                "run_id": str(args.run_id),
                "candidate_count": len(results),
                "derived_outcomes_pending_ranking": [result.outcome for result in results],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
