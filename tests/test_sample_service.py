import tempfile
import unittest
from pathlib import Path

from sample_service.app import CheckoutService
from sample_service.demo import replay, replay_inventory_underflow
from sample_service.reset import reset_database


class CheckoutIncidentTests(unittest.TestCase):
    def test_inventory_underflow_is_distinct_and_resettable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "checkout.sqlite3"
            faulty = replay_inventory_underflow(database, "inventory_underflow")
            healthy = replay_inventory_underflow(database, "off")
        self.assertEqual(faulty, [(200, {"sku": "widget", "remaining_inventory": -1})])
        self.assertEqual(healthy, [(409, {"error": "out_of_stock"})])

    def test_fault_reproduces_and_reset_restores_healthy_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "checkout.sqlite3"
            faulty = replay(database, "pool_leak")
            healthy = replay(database, "off")
            self.assertEqual([status for status, _ in faulty], [409, 409, 503])
            self.assertEqual(faulty[-1][1]["error"], "database_pool_timeout")
            self.assertEqual([status for status, _ in healthy], [409, 409, 200])
            self.assertEqual(healthy[-1][1]["remaining_inventory"], 9)

    def test_valid_checkout_and_unknown_sku_return_connections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "checkout.sqlite3"
            reset_database(database)
            service = CheckoutService(database)
            try:
                self.assertEqual(service.checkout("missing", 1)[0], 404)
                self.assertEqual(service.checkout("widget", 1)[0], 200)
                self.assertEqual(service.pool.available, service.pool.size)
            finally:
                service.pool.close()


if __name__ == "__main__":
    unittest.main()
