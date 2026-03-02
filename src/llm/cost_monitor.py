"""Budget enforcement — track and limit LLM spending per task/domain."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when LLM budget is exceeded."""


@dataclass
class CostRecord:
    """Single LLM call cost record."""

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class CostMonitor:
    """Track cumulative LLM costs and enforce budget limits.

    Usage::

        monitor = CostMonitor(budget_usd=0.10)
        monitor.record("gemini/gemini-3-flash-preview", input_tokens=500, output_tokens=200)
        monitor.check_budget()  # raises BudgetExceededError if over
    """

    budget_usd: float = 0.10
    total_cost_usd: float = 0.0
    total_calls: int = 0
    records: list[CostRecord] = field(default_factory=list)

    # Approximate cost per 1M tokens (input/output)
    _COST_TABLE: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {
            "gemini/gemini-3-flash-preview": (0.10, 0.40),
            "gemini/gemini-3.1-pro-preview": (1.25, 5.00),
            "openai/gpt-5-mini": (0.15, 0.60),
            "openai/gpt-5.3-codex": (2.50, 10.00),
        },
    )

    def estimate_cost(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Estimate cost for a call."""
        costs = self._COST_TABLE.get(model, (0.50, 2.00))
        input_cost = (input_tokens / 1_000_000) * costs[0]
        output_cost = (output_tokens / 1_000_000) * costs[1]
        return input_cost + output_cost

    def record(
        self, model: str, *, input_tokens: int, output_tokens: int
    ) -> float:
        """Record a completed LLM call.

        Returns:
            Estimated cost of this call in USD.
        """
        cost = self.estimate_cost(model, input_tokens, output_tokens)
        self.total_cost_usd += cost
        self.total_calls += 1
        self.records.append(
            CostRecord(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
            )
        )
        return cost

    def check_budget(self) -> None:
        """Raise BudgetExceededError if over budget."""
        if self.total_cost_usd > self.budget_usd:
            raise BudgetExceededError(
                f"Budget exceeded: ${self.total_cost_usd:.4f} > ${self.budget_usd:.4f} "
                f"({self.total_calls} calls)"
            )

    @property
    def remaining_usd(self) -> float:
        """Remaining budget in USD."""
        return max(0.0, self.budget_usd - self.total_cost_usd)

    def reset(self) -> None:
        """Reset all tracking."""
        self.total_cost_usd = 0.0
        self.total_calls = 0
        self.records.clear()
