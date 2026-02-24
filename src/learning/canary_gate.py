"""Canary Gate — regression check gate for selector cache promotion.

Before a pattern is promoted to a rule, it must pass the canary gate:
1. Minimum number of trials (success + failure)
2. Minimum success rate
3. (Optional) No regression vs. the existing baseline selector

Usage::

    from src.learning.canary_gate import evaluate_canary, CanaryConfig

    result = await evaluate_canary(pattern_db, "example.com", "search", "#q")
    if result.promoted:
        # safe to promote
        ...
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CanaryConfig:
    """Configuration for canary gate evaluation.

    Attributes:
        min_trials: Minimum number of total trials required.
        min_success_rate: Minimum success ratio to pass.
        baseline_comparison: Whether to compare against existing baseline.
        regression_tolerance: Allowed drop from baseline rate (e.g. 0.05 = 5%).
    """

    min_trials: int = 5
    min_success_rate: float = 0.8
    baseline_comparison: bool = True
    regression_tolerance: float = 0.05


@dataclass(frozen=True)
class CanaryResult:
    """Result of canary gate evaluation.

    Attributes:
        promoted: Whether the candidate passed the gate.
        success_rate: The candidate's success rate.
        baseline_rate: The baseline rate, if available.
        reason: Human-readable explanation.
    """

    promoted: bool
    success_rate: float
    baseline_rate: float | None
    reason: str


async def evaluate_canary(
    pattern_db: object,
    site: str,
    intent: str,
    candidate_selector: str,
    config: CanaryConfig | None = None,
) -> CanaryResult:
    """Evaluate candidate selector for promotion readiness.

    Steps:
        1. Get success rate for candidate from pattern_db.
        2. Check min_trials met.
        3. Check min_success_rate met.
        4. If baseline_comparison: compare to existing baseline selector.
        5. Return CanaryResult.

    Args:
        pattern_db: PatternDB instance (typed as object to avoid circular import).
        site: Hostname or glob.
        intent: Natural-language intent.
        candidate_selector: CSS selector to evaluate.
        config: Optional canary configuration.

    Returns:
        A ``CanaryResult`` indicating whether promotion is safe.
    """
    if config is None:
        config = CanaryConfig()

    # Get candidate stats
    success, fail, rate = await pattern_db.get_success_rate(  # type: ignore[attr-defined]
        site, intent, candidate_selector
    )
    total = success + fail

    if total < config.min_trials:
        return CanaryResult(
            promoted=False,
            success_rate=rate,
            baseline_rate=None,
            reason=f"Insufficient trials: {total} < {config.min_trials}",
        )

    if rate < config.min_success_rate:
        return CanaryResult(
            promoted=False,
            success_rate=rate,
            baseline_rate=None,
            reason=f"Low success rate: {rate:.2f} < {config.min_success_rate:.2f}",
        )

    # Baseline comparison
    if config.baseline_comparison:
        baseline = await pattern_db.get_baseline_rate(site, intent)  # type: ignore[attr-defined]
        if baseline is not None and rate < baseline - config.regression_tolerance:
            return CanaryResult(
                promoted=False,
                success_rate=rate,
                baseline_rate=baseline,
                reason=(
                    f"Regression: {rate:.2f} < baseline {baseline:.2f}"
                    f" - tolerance {config.regression_tolerance}"
                ),
            )
        return CanaryResult(
            promoted=True,
            success_rate=rate,
            baseline_rate=baseline,
            reason="Passed all canary checks",
        )

    return CanaryResult(
        promoted=True,
        success_rate=rate,
        baseline_rate=None,
        reason="Passed canary checks (no baseline comparison)",
    )
