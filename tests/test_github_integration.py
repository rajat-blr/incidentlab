import hashlib
import hmac
import unittest
from datetime import UTC, datetime
from uuid import uuid4

from incidentlab.contracts.models import (
    IncidentRun,
    RepairCandidate,
    RunState,
    VerificationCheck,
    VerificationRun,
)
from incidentlab.github_integration import (
    GitHubIntegrationError,
    create_or_get_draft_pull_request,
    validate_installation_permissions,
    verify_webhook_signature,
)


class FakeGitHubClient:
    def __init__(self) -> None:
        self.pull_request = None
        self.branch_writes = 0
        self.pr_writes = 0

    def find_pull_request(self, branch: str) -> dict | None:
        return self.pull_request

    def ensure_candidate_branch(self, branch: str, base_sha: str, unified_diff: str) -> None:
        self.branch_writes += 1

    def create_draft_pull_request(
        self, branch: str, base_branch: str, title: str, body: str
    ) -> dict:
        self.pr_writes += 1
        self.pull_request = {"number": 17, "html_url": "https://example.test/pr/17", "draft": True}
        return self.pull_request


def verified_inputs():
    now = datetime.now(UTC)
    run_id, candidate_id = uuid4(), uuid4()
    run = IncidentRun(
        id=run_id,
        scenario_id="pool-exhaustion",
        scenario_version=1,
        pinned_commit="a" * 40,
        workflow_id="workflow",
        state=RunState.COMPLETED,
        created_at=now,
        updated_at=now,
    )
    candidate = RepairCandidate(
        id=candidate_id,
        run_id=run_id,
        target_commit=run.pinned_commit,
        unified_diff="diff --git a/sample_service/app.py b/sample_service/app.py\n",
        explanation="Return the connection",
        expected_behavior="No pool exhaustion",
        changed_paths=["sample_service/app.py"],
        generator_id="test",
        diff_sha256="b" * 64,
        policy_status="accepted",
        policy_version="repair-policy-v1",
    )
    check = VerificationCheck(
        name="build",
        outcome="PASS",
        started_at=now,
        finished_at=now,
        exit_code=0,
        artifact_ref="/verification/artifacts/1",
        content_sha256="c" * 64,
    )
    verification = VerificationRun(
        id=uuid4(),
        candidate_id=candidate_id,
        environment_digest="sha256:" + "d" * 64,
        checks=[check],
        outcome="PASS",
        score_version="verification-score-v1",
        rank=1,
        started_at=now,
        finished_at=now,
    )
    return run, candidate, verification


class GitHubIntegrationTests(unittest.TestCase):
    def test_webhook_signature_is_constant_time_verified(self) -> None:
        body, secret = b'{"action":"created"}', "secret"
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(secret, body, signature))
        self.assertFalse(verify_webhook_signature(secret, body + b"x", signature))

    def test_permissions_are_minimal_and_forbid_deployment_write(self) -> None:
        validate_installation_permissions(
            {"metadata": "read", "contents": "write", "pull_requests": "write"}
        )
        with self.assertRaises(GitHubIntegrationError):
            validate_installation_permissions(
                {
                    "metadata": "read",
                    "contents": "write",
                    "pull_requests": "write",
                    "deployments": "write",
                }
            )

    def test_retries_return_one_existing_draft(self) -> None:
        client = FakeGitHubClient()
        run, candidate, verification = verified_inputs()
        first = create_or_get_draft_pull_request(
            client, run, candidate, verification, "http://localhost/report"
        )
        second = create_or_get_draft_pull_request(
            client, run, candidate, verification, "http://localhost/report"
        )
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(client.branch_writes, 1)
        self.assertEqual(client.pr_writes, 1)
        self.assertTrue(second.draft)

    def test_unverified_candidate_is_never_published(self) -> None:
        client = FakeGitHubClient()
        run, candidate, verification = verified_inputs()
        failed = verification.model_copy(update={"outcome": "FAIL"})
        with self.assertRaises(GitHubIntegrationError):
            create_or_get_draft_pull_request(
                client, run, candidate, failed, "http://localhost/report"
            )
        self.assertEqual(client.branch_writes, 0)


if __name__ == "__main__":
    unittest.main()
