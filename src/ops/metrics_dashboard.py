"""Metrics Dashboard — collects per-run metrics and produces aggregate summaries.

Provides ``MetricsDashboard`` for recording automation run metrics
(latency, LLM calls, cost, pass/fail status) and computing a
``MetricsSummary`` with averages and failure rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RunStatus = Literal["pass", "fail"]


@dataclass(frozen=True)
class RunMetricInput:
    """Single automation-run metric record.

    Attributes:
        duration_ms: Wall-clock duration in milliseconds.
        llm_calls: Number of LLM API calls made during the run.
        cost_usd: Total LLM cost in USD.
        status: Run outcome — ``"pass"`` or ``"fail"``.
    """

    duration_ms: float
    llm_calls: int
    cost_usd: float
    status: RunStatus


@dataclass(frozen=True)
class MetricsSummary:
    """Aggregated metrics across all recorded runs.

    Attributes:
        total_runs: Number of runs recorded.
        avg_latency_ms: Mean duration across runs (0 when empty).
        total_cost_usd: Sum of ``cost_usd`` across runs.
        failure_rate: Fraction of runs with ``status == "fail"`` (0..1).
        llm_calls_per_run: Mean LLM calls per run (0 when empty).
    """

    total_runs: int
    avg_latency_ms: float
    total_cost_usd: float
    failure_rate: float
    llm_calls_per_run: float


class MetricsDashboard:
    """In-memory metrics collector with summary aggregation.

    Usage::

        dash = MetricsDashboard()
        dash.record_run(RunMetricInput(duration_ms=120, llm_calls=3, cost_usd=0.01, status="pass"))
        print(dash.summary())
    """

    def __init__(self) -> None:
        self._records: list[RunMetricInput] = []

    # ── mutation ──────────────────────────────────────

    def record_run(self, input: RunMetricInput) -> None:  # noqa: A002
        """Append a run metric record."""
        self._records.append(input)

    def reset(self) -> None:
        """Clear all recorded metrics."""
        self._records.clear()

    # ── query ─────────────────────────────────────────

    def summary(self) -> MetricsSummary:
        """Return an aggregate summary of all recorded runs.

        Returns zero-valued ``MetricsSummary`` when no runs have been recorded.
        """
        if not self._records:
            return MetricsSummary(
                total_runs=0,
                avg_latency_ms=0.0,
                total_cost_usd=0.0,
                failure_rate=0.0,
                llm_calls_per_run=0.0,
            )

        total_runs = len(self._records)
        total_latency = sum(r.duration_ms for r in self._records)
        total_cost = sum(r.cost_usd for r in self._records)
        total_llm_calls = sum(r.llm_calls for r in self._records)
        failure_count = sum(1 for r in self._records if r.status == "fail")

        return MetricsSummary(
            total_runs=total_runs,
            avg_latency_ms=total_latency / total_runs,
            total_cost_usd=total_cost,
            failure_rate=failure_count / total_runs,
            llm_calls_per_run=total_llm_calls / total_runs,
        )
