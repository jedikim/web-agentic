"""Cascaded Flash-First Router — always try Flash model first, escalate to Pro on failure.

Routes LLM requests to the cheapest model that can handle the task.
Tracks per-complexity success rates to inform routing decisions.

Based on BudgetMLAgent (2025) cascaded model routing research.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# ── Enums ───────────────────────────────────────────


class TaskComplexity(StrEnum):
    """Complexity classification for LLM routing."""

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


# ── Data Types ──────────────────────────────────────


@dataclass(frozen=True)
class RoutingDecision:
    """Result of the routing decision.

    Attributes:
        model_tier: Target model tier ("flash" or "pro").
        reason: Human-readable explanation.
        complexity: Classified task complexity.
        confidence: Routing confidence in [0.0, 1.0].
    """

    model_tier: str
    reason: str
    complexity: TaskComplexity
    confidence: float


@dataclass(frozen=True)
class CascadeResult:
    """Result after executing through the cascade.

    Attributes:
        response: The LLM response text.
        model_used: Which model actually produced the response.
        escalated: Whether the request was escalated from Flash to Pro.
        flash_confidence: Confidence score from Flash attempt.
        total_tokens: Total tokens consumed.
    """

    response: str
    model_used: str
    escalated: bool
    flash_confidence: float
    total_tokens: int


@dataclass
class ModelStats:
    """Mutable success/failure tracking for a model+complexity pair.

    Attributes:
        successes: Number of successful completions.
        failures: Number of failed completions.
        total_tokens: Cumulative tokens used.
    """

    successes: int = 0
    failures: int = 0
    total_tokens: int = 0

    @property
    def success_rate(self) -> float:
        """Compute success rate as successes / total attempts.

        Returns 0.0 if no attempts recorded.
        """
        total = self.successes + self.failures
        if total == 0:
            return 0.0
        return self.successes / total


# ── Complexity Patterns ─────────────────────────────

_SIMPLE_PATTERNS: list[str] = [
    r"\bclick\b",
    r"\btype\b",
    r"\benter\b",
    r"\bscroll\b",
    r"\bselect\b",
    r"\bcheck\b",
    r"\bsearch\b",
    r"\bopen\b",
    r"\bclose\b",
    r"\bgo\b",
    r"\bnavigate\b",
    r"\bpress\b",
    r"\b클릭\b",
    r"\b입력\b",
    r"\b검색\b",
    r"\b열기\b",
]

_COMPLEX_PATTERNS: list[str] = [
    r"\banalyze\b",
    r"\bcompare\b",
    r"\bextract\b",
    r"\bsummarize\b",
    r"\bevaluate\b",
    r"\bgenerate\b",
    r"\bplan\b",
    r"\bcreate\b",
    r"\bimplement\b",
    r"\btransform\b",
    r"\bconvert\b",
    r"\b분석\b",
    r"\b비교\b",
    r"\b추출\b",
    r"\b요약\b",
    r"\b생성\b",
]


# ── Public Functions ────────────────────────────────


def classify_task_complexity(
    intent: str,
    step_count: int = 0,
) -> TaskComplexity:
    """Classify a task's complexity from its intent and step count.

    Rules:
    - Intent matching simple patterns AND step_count <= 1 -> SIMPLE
    - Intent matching complex patterns OR step_count > 5 -> COMPLEX
    - Otherwise -> MODERATE

    Args:
        intent: Natural language intent string.
        step_count: Number of planned steps (0 if unknown).

    Returns:
        TaskComplexity classification.
    """
    intent_lower = intent.lower()

    has_simple = any(re.search(p, intent_lower) for p in _SIMPLE_PATTERNS)
    has_complex = any(re.search(p, intent_lower) for p in _COMPLEX_PATTERNS)

    if has_complex or step_count > 5:
        return TaskComplexity.COMPLEX
    if has_simple and step_count <= 1:
        return TaskComplexity.SIMPLE
    if step_count > 1:
        return TaskComplexity.MODERATE

    return TaskComplexity.MODERATE if not has_simple else TaskComplexity.SIMPLE


def should_escalate_to_pro(
    flash_confidence: float,
    parse_ok: bool,
    complexity: TaskComplexity,
    threshold: float = 0.7,
) -> bool:
    """Decide whether to escalate from Flash to Pro model.

    Escalation triggers:
    - Parse failure (regardless of confidence)
    - Confidence below threshold (adjusted for complexity)

    Args:
        flash_confidence: Flash model's confidence score.
        parse_ok: Whether Flash response parsed successfully.
        complexity: Task complexity classification.
        threshold: Base confidence threshold.

    Returns:
        True if should escalate to Pro.
    """
    if not parse_ok:
        return True

    # Simple tasks have lower threshold
    effective_threshold = threshold
    if complexity == TaskComplexity.SIMPLE:
        effective_threshold = 0.5
    elif complexity == TaskComplexity.COMPLEX:
        effective_threshold = threshold  # keep base threshold for complex

    return flash_confidence < effective_threshold


# ── Router Class ────────────────────────────────────


class CascadedRouter:
    """Flash-first model router with success rate tracking.

    Always routes to Flash first. Escalates to Pro when Flash
    confidence is low or parsing fails.

    Args:
        confidence_threshold: Base threshold for Pro escalation.
        simple_threshold: Lower threshold for simple tasks.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.7,
        simple_threshold: float = 0.5,
    ) -> None:
        self._confidence_threshold = confidence_threshold
        self._simple_threshold = simple_threshold
        self._stats: dict[str, ModelStats] = {}

    def _stats_key(self, complexity: TaskComplexity, model_tier: str) -> str:
        return f"{complexity.value}:{model_tier}"

    def route(
        self,
        intent: str,
        step_count: int = 0,
    ) -> RoutingDecision:
        """Make initial routing decision (always Flash-first).

        Args:
            intent: Natural language intent string.
            step_count: Number of planned steps.

        Returns:
            RoutingDecision targeting Flash model.
        """
        complexity = classify_task_complexity(intent, step_count)
        return RoutingDecision(
            model_tier="flash",
            reason=f"flash-first for {complexity.value} task",
            complexity=complexity,
            confidence=1.0,
        )

    def should_escalate(
        self,
        flash_confidence: float,
        parse_ok: bool,
        complexity: TaskComplexity,
    ) -> bool:
        """Check if Flash result should be escalated to Pro.

        Args:
            flash_confidence: Flash model's confidence score.
            parse_ok: Whether Flash response parsed successfully.
            complexity: Task complexity.

        Returns:
            True if should escalate.
        """
        threshold = self._confidence_threshold
        if complexity == TaskComplexity.SIMPLE:
            threshold = self._simple_threshold
        return should_escalate_to_pro(
            flash_confidence,
            parse_ok,
            complexity,
            threshold,
        )

    def record_outcome(
        self,
        model_tier: str,
        complexity: TaskComplexity,
        success: bool,
        tokens: int = 0,
    ) -> None:
        """Record a model invocation outcome.

        Args:
            model_tier: The model tier used ("flash" or "pro").
            complexity: Task complexity.
            success: Whether the invocation succeeded.
            tokens: Tokens consumed.
        """
        key = self._stats_key(complexity, model_tier)
        if key not in self._stats:
            self._stats[key] = ModelStats()
        stats = self._stats[key]
        if success:
            stats.successes += 1
        else:
            stats.failures += 1
        stats.total_tokens += tokens

    def get_stats(self) -> dict[str, dict[str, Any]]:
        """Get all recorded statistics.

        Returns:
            Dict mapping stat keys to their values.
        """
        result: dict[str, dict[str, Any]] = {}
        for key, stats in self._stats.items():
            result[key] = {
                "successes": stats.successes,
                "failures": stats.failures,
                "total_tokens": stats.total_tokens,
                "success_rate": stats.success_rate,
            }
        return result

    def get_success_rate(
        self,
        complexity: TaskComplexity,
        model_tier: str,
    ) -> float:
        """Get success rate for a specific complexity+model combination.

        Args:
            complexity: Task complexity level.
            model_tier: Model tier ("flash" or "pro").

        Returns:
            Success rate in [0.0, 1.0], or 0.0 if no data.
        """
        key = self._stats_key(complexity, model_tier)
        stats = self._stats.get(key)
        if stats is None:
            return 0.0
        return stats.success_rate
