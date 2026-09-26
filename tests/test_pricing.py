import unittest
from decimal import Decimal

from incidentlab.model_adapter.diagnosis import Usage
from incidentlab.model_adapter.pricing import estimated_cost_usd


class PricingTests(unittest.TestCase):
    def test_gpt_5_4_mini_standard_text_cost(self) -> None:
        usage = Usage(input_tokens=11_443, output_tokens=665)
        self.assertEqual(estimated_cost_usd("gpt-5.4-mini", usage), Decimal("0.011575"))

    def test_snapshot_uses_alias_price(self) -> None:
        usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
        self.assertEqual(
            estimated_cost_usd("gpt-5.4-mini-2026-03-17", usage),
            Decimal("5.250000"),
        )

    def test_unknown_model_has_no_estimate(self) -> None:
        self.assertEqual(estimated_cost_usd("custom-model", Usage(1, 1)), Decimal("0.000000"))


if __name__ == "__main__":
    unittest.main()
