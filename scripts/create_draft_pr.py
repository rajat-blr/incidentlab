"""Create or retrieve one approved draft PR for a verified IncidentLab run."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incidentlab.db import repository
from incidentlab.github_integration import GitHubRestClient, create_or_get_draft_pull_request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=UUID)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--base-branch", default="main")
    args = parser.parse_args()
    if os.environ.get("GITHUB_INTEGRATION_ENABLED", "false").lower() != "true":
        parser.error("GITHUB_INTEGRATION_ENABLED must be true")
    run = repository.get_run(args.run_id)
    if run is None:
        parser.error("run not found")
    verifications = sorted(
        (item for item in repository.list_verifications(args.run_id) if item.outcome == "PASS"),
        key=lambda item: item.rank or 999,
    )
    candidates = {item.id: item for item in repository.list_repair_candidates(args.run_id)}
    if not verifications or verifications[0].candidate_id not in candidates:
        parser.error("run has no verified repair candidate")
    approval, _ = repository.record_approval(
        args.run_id,
        args.approved_by,
        "approved",
        "github-draft-pr-v1",
        action="create_draft_pr",
    )
    if approval["decision"] != "approved":
        parser.error("draft PR approval was previously rejected")
    repository_name = os.environ.get("GITHUB_REPOSITORY", "")
    client = GitHubRestClient(
        repository_name,
        os.environ.get("GITHUB_INSTALLATION_TOKEN", ""),
        Path.cwd(),
    )
    result = create_or_get_draft_pull_request(
        client,
        run,
        candidates[verifications[0].candidate_id],
        verifications[0],
        f"http://127.0.0.1:5173/runs/{run.id}",
        base_branch=args.base_branch,
    )
    repository.record_integration_event(
        args.run_id,
        "draft_pr_created" if result.created else "draft_pr_reused",
        args.approved_by,
        f"run:{run.id}:draft-pr:{result.number}",
        {"number": result.number, "url": result.url, "draft": result.draft},
    )
    print(result.url)


if __name__ == "__main__":
    main()
