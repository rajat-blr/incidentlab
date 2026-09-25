import hashlib
import hmac
import json
import unittest
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from incidentlab.api.app import app
from incidentlab.contracts.models import IncidentRun, RunState


class ApiContractTests(unittest.TestCase):
    def test_public_catalog_does_not_include_private_truth(self) -> None:
        with TestClient(app) as client:
            response = client.get("/scenarios")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.json()},
            {"pool-exhaustion", "inventory-underflow"},
        )
        self.assertTrue(all(item["schema_version"] == 1 for item in response.json()))
        self.assertNotIn("root_cause_label", response.text)
        self.assertNotIn("expected_repair", response.text)

    def test_health_is_process_liveness(self) -> None:
        with TestClient(app) as client:
            response = client.get("/health")
        self.assertEqual(response.json(), {"status": "alive"})

    def test_github_webhook_rejects_invalid_signature(self) -> None:
        with patch.dict("os.environ", {"GITHUB_WEBHOOK_SECRET": "test-secret"}):
            with TestClient(app) as client:
                response = client.post(
                    "/integrations/github/webhook",
                    content=b"{}",
                    headers={"X-Hub-Signature-256": "sha256=invalid"},
                )
        self.assertEqual(response.status_code, 401)

    def test_github_webhook_accepts_minimal_installation(self) -> None:
        body = json.dumps(
            {
                "installation": {
                    "permissions": {
                        "metadata": "read",
                        "contents": "write",
                        "pull_requests": "write",
                    }
                }
            },
            separators=(",", ":"),
        ).encode()
        signature = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        with patch.dict("os.environ", {"GITHUB_WEBHOOK_SECRET": "test-secret"}):
            with TestClient(app) as client:
                response = client.post(
                    "/integrations/github/webhook",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Hub-Signature-256": signature,
                        "X-GitHub-Event": "installation",
                    },
                )
        self.assertEqual(response.status_code, 200)

    def test_runs_endpoint_returns_reviewable_run_summaries(self) -> None:
        run = IncidentRun(
            id=uuid4(),
            scenario_id="pool-exhaustion",
            scenario_version=1,
            pinned_commit="a" * 40,
            workflow_id="workflow-1",
            state=RunState.VERIFYING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        with patch("incidentlab.api.app.repository.list_runs", return_value=[run]):
            with TestClient(app) as client:
                response = client.get("/runs?state=VERIFYING")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["state"], "VERIFYING")
