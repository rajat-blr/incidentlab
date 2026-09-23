import unittest

from fastapi.testclient import TestClient

from incidentlab.api.app import app


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
