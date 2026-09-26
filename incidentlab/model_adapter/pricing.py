"""Versioned local cost estimates for model-usage reporting."""

from decimal import ROUND_HALF_UP, Decimal

from incidentlab.model_adapter.diagnosis import Usage

_PER_MILLION_TOKEN_PRICES = {
    "gpt-5.4-mini": (Decimal("0.75"), Decimal("4.50")),
}


def estimated_cost_usd(model_id: str, usage: Usage) -> Decimal:
    """Estimate standard-processing text cost; unknown models fail to a zero estimate."""

    alias = next(
        (name for name in _PER_MILLION_TOKEN_PRICES if model_id.startswith(name)),
        None,
    )
    if alias is None:
        return Decimal("0.000000")
    input_price, output_price = _PER_MILLION_TOKEN_PRICES[alias]
    cost = (
        Decimal(usage.input_tokens) * input_price + Decimal(usage.output_tokens) * output_price
    ) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
