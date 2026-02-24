"""Tests for src.core.self_healing — 6-category failure classification."""
from __future__ import annotations

import pytest

from src.core.retry_policy import should_heal
from src.core.self_healing import (
    FailureCategory,
    HealingPlan,
    HealingStrategy,
    classify_failure,
    get_healing_plans,
)

# ── Classification tests ────────────────────────────


def test_timeout_classified() -> None:
    """TimeoutError exception should classify as TIMING_TIMEOUT."""
    result = classify_failure(exception=TimeoutError("waited too long"))
    assert result.category == FailureCategory.TIMING_TIMEOUT


def test_hidden_element_classified() -> None:
    """Error message 'element not visible' should classify as ELEMENT_HIDDEN."""
    result = classify_failure(error_message="element not visible")
    assert result.category == FailureCategory.ELEMENT_HIDDEN


def test_stale_element_classified() -> None:
    """Error mentioning 'detached from DOM' should classify as STALE_ELEMENT."""
    result = classify_failure(error_message="element detached from DOM")
    assert result.category == FailureCategory.STALE_ELEMENT


def test_navigation_classified() -> None:
    """Error with 'net::err_connection_refused' should classify as NAVIGATION_INCOMPLETE."""
    result = classify_failure(error_message="net::err_connection_refused")
    assert result.category == FailureCategory.NAVIGATION_INCOMPLETE


def test_data_mismatch_classified() -> None:
    """Error with 'assertion failed: expected X got Y' should classify as DATA_MISMATCH."""
    result = classify_failure(error_message="assertion failed: expected X got Y")
    assert result.category == FailureCategory.DATA_MISMATCH


def test_unknown_defaults_selector() -> None:
    """Unknown error should default to SELECTOR_NOT_FOUND."""
    result = classify_failure(error_message="some completely unknown error xyz")
    assert result.category == FailureCategory.SELECTOR_NOT_FOUND


# ── Healing plan tests ──────────────────────────────


def test_timing_healing_plans() -> None:
    """Timing category should have INCREASE_TIMEOUT as first plan."""
    plans = get_healing_plans(FailureCategory.TIMING_TIMEOUT)
    assert len(plans) >= 1
    assert plans[0].strategy == HealingStrategy.INCREASE_TIMEOUT


def test_hidden_healing_plans() -> None:
    """Hidden category should have SCROLL_INTO_VIEW as first plan."""
    plans = get_healing_plans(FailureCategory.ELEMENT_HIDDEN)
    assert len(plans) >= 1
    assert plans[0].strategy == HealingStrategy.SCROLL_INTO_VIEW


def test_stale_healing_plans() -> None:
    """Stale category should have WAIT_AND_RETRY as first plan."""
    plans = get_healing_plans(FailureCategory.STALE_ELEMENT)
    assert len(plans) >= 1
    assert plans[0].strategy == HealingStrategy.WAIT_AND_RETRY


def test_navigation_healing_plans() -> None:
    """Navigation category should have WAIT_FOR_NETWORK as first plan."""
    plans = get_healing_plans(FailureCategory.NAVIGATION_INCOMPLETE)
    assert len(plans) >= 1
    assert plans[0].strategy == HealingStrategy.WAIT_FOR_NETWORK


def test_healing_plan_frozen() -> None:
    """HealingPlan should be immutable (frozen dataclass)."""
    plan = HealingPlan(
        strategy=HealingStrategy.RETRY,
        category=FailureCategory.SELECTOR_NOT_FOUND,
        params={"key": "val"},
        confidence=0.9,
    )
    with pytest.raises(AttributeError):
        plan.confidence = 0.1  # type: ignore[misc]


# ── retry_policy integration tests ──────────────────


def test_should_heal_returns_category() -> None:
    """should_heal('SelectorNotFound') should return 'selector_not_found'."""
    result = should_heal("SelectorNotFound")
    assert result == "selector_not_found"


def test_should_heal_unknown_none() -> None:
    """should_heal with an unknown code should return None."""
    result = should_heal("unknown_code")
    assert result is None
