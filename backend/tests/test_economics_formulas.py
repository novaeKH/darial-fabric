from decimal import Decimal
import unittest

from app.services.economics_service import (
    calculate_llm_cost_breakdown,
    effective_outcome_quantity,
    safe_roi,
)


class Endpoint:
    input_price_per_million = Decimal("10")
    output_price_per_million = Decimal("20")
    cached_input_price_per_million = Decimal("2")
    reasoning_price_per_million = Decimal("40")
    gpu_hour_price = Decimal("0")
    currency = "RUB"


class Outcome:
    def __init__(self, success, human_accepted, quantity):
        self.success = success
        self.human_accepted = human_accepted
        self.quantity = quantity


class EconomicsFormulaTests(unittest.TestCase):
    def test_cached_and_reasoning_tokens_are_not_double_counted(self):
        result = calculate_llm_cost_breakdown(
            input_tokens=1000,
            cached_tokens=400,
            output_tokens=500,
            reasoning_tokens=100,
            endpoint=Endpoint(),
        )
        expected = (
            Decimal("600") * Decimal("10")
            + Decimal("400") * Decimal("2")
            + Decimal("400") * Decimal("20")
            + Decimal("100") * Decimal("40")
        ) / Decimal("1000000")
        self.assertEqual(result.total_cost, expected.quantize(Decimal("0.000001")))
        self.assertEqual(result.billable_uncached_input_tokens, 600)
        self.assertEqual(result.billable_standard_output_tokens, 400)

    def test_special_price_falls_back_to_base_price(self):
        endpoint = Endpoint()
        endpoint.cached_input_price_per_million = Decimal("0")
        endpoint.reasoning_price_per_million = Decimal("0")
        result = calculate_llm_cost_breakdown(
            input_tokens=100,
            cached_tokens=100,
            output_tokens=50,
            reasoning_tokens=50,
            endpoint=endpoint,
        )
        expected = (
            Decimal("100") * Decimal("10")
            + Decimal("50") * Decimal("20")
        ) / Decimal("1000000")
        self.assertEqual(result.total_cost, expected.quantize(Decimal("0.000001")))

    def test_effective_outcome_uses_quantity_and_human_acceptance(self):
        self.assertEqual(effective_outcome_quantity(Outcome(True, True, 3)), 3)
        self.assertEqual(effective_outcome_quantity(Outcome(True, None, 2)), 2)
        self.assertEqual(effective_outcome_quantity(Outcome(True, False, 5)), 0)
        self.assertEqual(effective_outcome_quantity(Outcome(False, True, 5)), 0)

    def test_roi(self):
        self.assertEqual(safe_roi(business_value=300, cost=100), 2.0)
        self.assertIsNone(safe_roi(business_value=300, cost=0))


if __name__ == "__main__":
    unittest.main()
