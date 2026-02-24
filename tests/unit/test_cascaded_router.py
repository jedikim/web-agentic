"""Tests for the Cascaded Flash-First Router."""
from __future__ import annotations

from src.ai.cascaded_router import (
    CascadedRouter,
    TaskComplexity,
    classify_task_complexity,
    should_escalate_to_pro,
)

# ── classify_task_complexity ────────────────────────


def test_simple_intent_classified() -> None:
    """'click the button' with no extra steps -> SIMPLE."""
    result = classify_task_complexity("click the button")
    assert result == TaskComplexity.SIMPLE


def test_complex_intent_classified() -> None:
    """'analyze the product listing' -> COMPLEX."""
    result = classify_task_complexity("analyze the product listing")
    assert result == TaskComplexity.COMPLEX


def test_moderate_by_step_count() -> None:
    """Neutral intent with step_count=3 -> MODERATE."""
    result = classify_task_complexity("do something", step_count=3)
    assert result == TaskComplexity.MODERATE


def test_complex_by_step_count() -> None:
    """Any intent with step_count=6 -> COMPLEX (>5 threshold)."""
    result = classify_task_complexity("do something", step_count=6)
    assert result == TaskComplexity.COMPLEX


# ── CascadedRouter.route ───────────────────────────


def test_always_starts_with_flash() -> None:
    """route() always returns model_tier='flash'."""
    router = CascadedRouter()
    decision = router.route("analyze complex data", step_count=10)
    assert decision.model_tier == "flash"


# ── should_escalate_to_pro ─────────────────────────


def test_low_confidence_escalation() -> None:
    """Confidence=0.5 with MODERATE complexity -> escalate (threshold 0.7)."""
    result = should_escalate_to_pro(
        flash_confidence=0.5,
        parse_ok=True,
        complexity=TaskComplexity.MODERATE,
    )
    assert result is True


def test_parse_failure_escalation() -> None:
    """parse_ok=False -> always escalate regardless of confidence."""
    result = should_escalate_to_pro(
        flash_confidence=0.99,
        parse_ok=False,
        complexity=TaskComplexity.SIMPLE,
    )
    assert result is True


def test_high_confidence_no_escalation() -> None:
    """Confidence=0.9 with parse_ok=True -> no escalation."""
    result = should_escalate_to_pro(
        flash_confidence=0.9,
        parse_ok=True,
        complexity=TaskComplexity.MODERATE,
    )
    assert result is False


def test_simple_lower_threshold() -> None:
    """SIMPLE task + confidence=0.55 -> no escalation (threshold is 0.5)."""
    result = should_escalate_to_pro(
        flash_confidence=0.55,
        parse_ok=True,
        complexity=TaskComplexity.SIMPLE,
        threshold=0.7,
    )
    assert result is False


# ── CascadedRouter stats ──────────────────────────


def test_record_and_stats() -> None:
    """Record outcomes and verify stats dict structure."""
    router = CascadedRouter()
    router.record_outcome("flash", TaskComplexity.SIMPLE, success=True, tokens=100)
    router.record_outcome("flash", TaskComplexity.SIMPLE, success=False, tokens=50)
    router.record_outcome("pro", TaskComplexity.COMPLEX, success=True, tokens=500)

    stats = router.get_stats()
    assert "simple:flash" in stats
    assert stats["simple:flash"]["successes"] == 1
    assert stats["simple:flash"]["failures"] == 1
    assert stats["simple:flash"]["total_tokens"] == 150
    assert stats["simple:flash"]["success_rate"] == 0.5

    assert "complex:pro" in stats
    assert stats["complex:pro"]["successes"] == 1
    assert stats["complex:pro"]["success_rate"] == 1.0


def test_success_rate_calculation() -> None:
    """7 successes + 3 failures = 0.7 success rate."""
    router = CascadedRouter()
    for _ in range(7):
        router.record_outcome("flash", TaskComplexity.MODERATE, success=True)
    for _ in range(3):
        router.record_outcome("flash", TaskComplexity.MODERATE, success=False)

    rate = router.get_success_rate(TaskComplexity.MODERATE, "flash")
    assert rate == 0.7


def test_empty_stats_zero() -> None:
    """No recorded data -> success rate 0.0."""
    router = CascadedRouter()
    rate = router.get_success_rate(TaskComplexity.SIMPLE, "flash")
    assert rate == 0.0
