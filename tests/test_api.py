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
        self.assertEqual(response.json()[0]["id"], "pool-exhaustion")
        self.assertEqual(response.json()[0]["schema_version"], 1)
        self.assertNotIn("root_cause_label", response.text)
        self.assertNotIn("expected_repair", response.text)

    def test_health_is_process_liveness(self) -> None:
        with TestClient(app) as client:
            response = client.get("/health")
        self.assertEqual(response.json(), {"status": "alive"})

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
