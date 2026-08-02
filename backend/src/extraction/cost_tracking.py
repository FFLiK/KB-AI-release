from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TokenRates:
    input_per_million_usd: Decimal
    output_per_million_usd: Decimal
    cached_per_million_usd: Decimal = Decimal("0")


class CostTracker:
    def __init__(self, rates: dict[str, TokenRates] | None = None):
        self.rates = rates or {
            "gemini-3.6-flash": TokenRates(
                Decimal(os.getenv("GEMINI_INPUT_COST_PER_MILLION_USD", "0")),
                Decimal(os.getenv("GEMINI_OUTPUT_COST_PER_MILLION_USD", "0")),
                Decimal(os.getenv("GEMINI_CACHED_COST_PER_MILLION_USD", "0")),
            ),
            "gpt-5.6-terra": TokenRates(
                Decimal(os.getenv("OPENAI_INPUT_COST_PER_MILLION_USD", "0")),
                Decimal(os.getenv("OPENAI_OUTPUT_COST_PER_MILLION_USD", "0")),
                Decimal(os.getenv("OPENAI_CACHED_COST_PER_MILLION_USD", "0")),
            ),
        }

    def estimate(
        self, model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0
    ) -> float:
        rate = self.rates.get(model)
        if not rate:
            return 0.0
        uncached = max(0, input_tokens - cached_tokens)
        cost = (
            Decimal(uncached) * rate.input_per_million_usd
            + Decimal(output_tokens) * rate.output_per_million_usd
            + Decimal(cached_tokens) * rate.cached_per_million_usd
        ) / Decimal("1000000")
        return float(cost.quantize(Decimal("0.00000001")))

    def estimate_with_status(
        self, model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0
    ) -> tuple[float | None, str]:
        rate = self.rates.get(model)
        if rate is None:
            return None, "MODEL_RATE_NOT_CONFIGURED"
        if not any(
            (
                rate.input_per_million_usd,
                rate.output_per_million_usd,
                rate.cached_per_million_usd,
            )
        ):
            return None, "RATE_NOT_CONFIGURED"
        return self.estimate(model, input_tokens, output_tokens, cached_tokens), "ESTIMATED"