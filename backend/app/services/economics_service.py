from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

MILLION = Decimal("1000000")
SECONDS_PER_HOUR = Decimal("3600")
MONEY_QUANT = Decimal("0.000001")


def as_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


@dataclass(frozen=True)
class LLMCostBreakdown:
    input_tokens_reported: int
    output_tokens_reported: int
    cached_tokens: int
    reasoning_tokens: int
    billable_uncached_input_tokens: int
    billable_standard_output_tokens: int
    input_cost: Decimal
    cached_input_cost: Decimal
    output_cost: Decimal
    reasoning_cost: Decimal
    gpu_cost: Decimal
    total_cost: Decimal
    currency: str

    def as_metadata(self) -> dict[str, Any]:
        return {
            "pricing_method": "server_calculated",
            "token_semantics": {
                "cached_tokens_are_subset_of_input": True,
                "reasoning_tokens_are_subset_of_output": True,
            },
            "reported": {
                "input_tokens": self.input_tokens_reported,
                "output_tokens": self.output_tokens_reported,
                "cached_tokens": self.cached_tokens,
                "reasoning_tokens": self.reasoning_tokens,
            },
            "billable": {
                "uncached_input_tokens": self.billable_uncached_input_tokens,
                "cached_input_tokens": self.cached_tokens,
                "standard_output_tokens": self.billable_standard_output_tokens,
                "reasoning_output_tokens": self.reasoning_tokens,
            },
            "cost": {
                "input": float(self.input_cost),
                "cached_input": float(self.cached_input_cost),
                "output": float(self.output_cost),
                "reasoning": float(self.reasoning_cost),
                "gpu": float(self.gpu_cost),
                "total": float(self.total_cost),
                "currency": self.currency,
            },
        }


def calculate_llm_cost_breakdown(
    *,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
    gpu_seconds: float = 0,
    endpoint: Any,
) -> LLMCostBreakdown:
    """Calculate a server-side LLM cost without double-counting token subsets.

    Darial uses the following convention:
    - cached_tokens are a subset of input_tokens;
    - reasoning_tokens are a subset of output_tokens;
    - if a special cached/reasoning tariff is zero, the corresponding base
      input/output tariff is used instead of treating those tokens as free.
    """
    input_tokens = max(int(input_tokens or 0), 0)
    output_tokens = max(int(output_tokens or 0), 0)
    cached_tokens = min(max(int(cached_tokens or 0), 0), input_tokens)
    reasoning_tokens = min(max(int(reasoning_tokens or 0), 0), output_tokens)

    uncached_input = input_tokens - cached_tokens
    standard_output = output_tokens - reasoning_tokens

    input_price = as_decimal(endpoint.input_price_per_million)
    output_price = as_decimal(endpoint.output_price_per_million)
    cached_price = as_decimal(endpoint.cached_input_price_per_million)
    reasoning_price = as_decimal(endpoint.reasoning_price_per_million)
    gpu_hour_price = as_decimal(endpoint.gpu_hour_price)

    if cached_price <= 0:
        cached_price = input_price
    if reasoning_price <= 0:
        reasoning_price = output_price

    input_cost = as_decimal(uncached_input) * input_price / MILLION
    cached_cost = as_decimal(cached_tokens) * cached_price / MILLION
    output_cost = as_decimal(standard_output) * output_price / MILLION
    reasoning_cost = as_decimal(reasoning_tokens) * reasoning_price / MILLION
    gpu_cost = as_decimal(gpu_seconds) * gpu_hour_price / SECONDS_PER_HOUR

    total = (
        input_cost + cached_cost + output_cost + reasoning_cost + gpu_cost
    ).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

    return LLMCostBreakdown(
        input_tokens_reported=input_tokens,
        output_tokens_reported=output_tokens,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
        billable_uncached_input_tokens=uncached_input,
        billable_standard_output_tokens=standard_output,
        input_cost=input_cost.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP),
        cached_input_cost=cached_cost.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP),
        output_cost=output_cost.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP),
        reasoning_cost=reasoning_cost.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP),
        gpu_cost=gpu_cost.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP),
        total_cost=total,
        currency=str(getattr(endpoint, "currency", "RUB") or "RUB"),
    )


def effective_outcome_quantity(outcome: Any) -> float:
    """Count only successful outcomes not explicitly rejected by a human."""
    if not bool(getattr(outcome, "success", False)):
        return 0.0
    if getattr(outcome, "human_accepted", None) is False:
        return 0.0
    return max(float(getattr(outcome, "quantity", 0) or 0), 0.0)


def safe_roi(*, business_value: float, cost: float) -> float | None:
    if cost <= 0:
        return None
    return (business_value - cost) / cost
