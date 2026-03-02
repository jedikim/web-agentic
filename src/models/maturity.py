"""Maturity state — Cold / Warm / Hot per domain."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MaturityState:
    """Per-domain automation maturity tracking."""

    domain: str = ""
    stage: str = "cold"  # "cold" | "warm" | "hot"
    total_runs: int = 0
    recent_success_rate: float = 0.0  # last 20 runs
    consecutive_successes: int = 0
    llm_calls_last_10: int = 0

    def evaluate_stage(self) -> str:
        """Auto-evaluate maturity stage.

        Returns:
            "cold", "warm", or "hot" based on metrics.
        """
        if self.total_runs == 0:
            return "cold"
        if (
            self.recent_success_rate >= 0.95
            and self.consecutive_successes >= 10
            and self.llm_calls_last_10 == 0
        ):
            return "hot"
        if self.total_runs >= 3 and self.recent_success_rate >= 0.70:
            return "warm"
        return "cold"

    def update_stage(self) -> str:
        """Evaluate and persist the new stage.

        Returns:
            The new stage string.
        """
        self.stage = self.evaluate_stage()
        return self.stage

    def record_run(self, *, success: bool, llm_calls: int) -> None:
        """Record a run result and update metrics.

        Args:
            success: Whether the run succeeded.
            llm_calls: Number of LLM calls in this run.
        """
        self.total_runs += 1
        if success:
            self.consecutive_successes += 1
        else:
            self.consecutive_successes = 0
        # Approximate recent_success_rate (EMA with window ~20)
        alpha = min(1.0 / 20.0, 1.0)
        self.recent_success_rate = (
            alpha * (1.0 if success else 0.0)
            + (1 - alpha) * self.recent_success_rate
        )
        self.llm_calls_last_10 = llm_calls  # simplified: caller tracks window
        self.update_stage()
