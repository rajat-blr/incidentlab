import sqlite3
import tempfile
import unittest
from pathlib import Path

from incidentlab.sandbox.container_check import run_scenario_check
from sample_service.demo import replay_scenario
from sample_service.scenarios import matches_results


class GatewayScenarioTests(unittest.TestCase):
    def test_an_unavailable_upstream_is_not_a_pool_exhaustion_reproduction(self):
        results = [
            (409, {"error": "out_of_stock"}),
            (409, {"error": "out_of_stock"}),
            (503, {"error": "inventory_unavailable"}),
        ]
        self.assertFalse(matches_results("pool-exhaustion", results, healthy=False))

    def test_upstream_error_preserves_body_but_fault_changes_http_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "checkout.sqlite3"
            for _ in range(2):
                faulty = replay_scenario(database, "upstream-error-masking")
                healthy = replay_scenario(database, "upstream-error-masking", healthy=True)
                self.assertEqual(faulty, [(200, {"error": "out_of_stock"})])
                self.assertEqual(healthy, [(409, {"error": "out_of_stock"})])
                with sqlite3.connect(database) as connection:
                    self.assertEqual(
                        connection.execute("SELECT quantity FROM inventory").fetchone()[0], 10
                    )

    def test_cached_mutation_skips_purchase_and_reset_clears_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "checkout.sqlite3"
            for _ in range(2):
                faulty = replay_scenario(database, "mutation-response-cache")
                self.assertTrue(matches_results("mutation-response-cache", faulty, healthy=False))
                with sqlite3.connect(database) as connection:
                    self.assertEqual(
                        connection.execute("SELECT quantity FROM inventory").fetchone()[0], 9
                    )
                healthy = replay_scenario(database, "mutation-response-cache", healthy=True)
                self.assertTrue(matches_results("mutation-response-cache", healthy, healthy=True))
                with sqlite3.connect(database) as connection:
                    self.assertEqual(
                        connection.execute("SELECT quantity FROM inventory").fetchone()[0], 8
                    )

    def test_trusted_checks_reject_unrepaired_gateway_faults(self):
        for scenario in ("upstream-error-masking", "mutation-response-cache"):
            with self.subTest(scenario=scenario):
                self.assertEqual(run_scenario_check("baseline", 1, scenario)["matches"], 1)
                self.assertEqual(run_scenario_check("healthy", 1, scenario)["matches"], 1)
                self.assertEqual(run_scenario_check("repaired", 1, scenario)["matches"], 0)


if __name__ == "__main__":
    unittest.main()
