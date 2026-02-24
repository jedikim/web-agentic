"""Self-healing failure classification and recovery strategies.

Classifies failures into 6 categories (beyond just selector issues)
and provides targeted healing plans for each category.

Based on QA Wolf (2024) failure taxonomy research.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# ── Enums ───────────────────────────────────────────


class HealingStrategy(StrEnum):
    """Recovery strategy to apply for a failure."""

    RETRY = "retry"
    WAIT_AND_RETRY = "wait_and_retry"
    SCROLL_INTO_VIEW = "scroll_into_view"
    EXPAND_PARENT = "expand_parent"
    INCREASE_TIMEOUT = "increase_timeout"
    WAIT_FOR_NETWORK = "wait_for_network"
    RE_EXTRACT = "re_extract"
    NONE = "none"


class FailureCategory(StrEnum):
    """Classification of a failure's root cause."""

    SELECTOR_NOT_FOUND = "selector_not_found"
    TIMING_TIMEOUT = "timing_timeout"
    ELEMENT_HIDDEN = "element_hidden"
    STALE_ELEMENT = "stale_element"
    NAVIGATION_INCOMPLETE = "navigation_incomplete"
    DATA_MISMATCH = "data_mismatch"


# ── Data Types ──────────────────────────────────────


@dataclass(frozen=True)
class HealingPlan:
    """A single healing strategy with parameters.

    Attributes:
        strategy: The healing strategy to apply.
        category: The failure category this plan addresses.
        params: Strategy-specific parameters.
        confidence: Confidence that this plan will succeed.
    """

    strategy: HealingStrategy
    category: FailureCategory
    params: dict[str, Any]
    confidence: float = 0.5


@dataclass(frozen=True)
class ClassificationResult:
    """Result of failure classification.

    Attributes:
        category: The identified failure category.
        healing_plans: Ordered list of healing strategies to try.
        raw_error: The original error message.
    """

    category: FailureCategory
    healing_plans: tuple[HealingPlan, ...]
    raw_error: str


# ── Type Aliases ────────────────────────────────────

_PlanBuilder = Callable[[FailureCategory], tuple[HealingPlan, ...]]


# ── Pattern Matching ────────────────────────────────

_TIMEOUT_PATTERNS: list[str] = [
    r"timeout",
    r"timed?\s*out",
    r"waiting.*exceeded",
    r"deadline.*exceeded",
    r"navigation.*timeout",
    r"wait.*timeout",
]

_HIDDEN_PATTERNS: list[str] = [
    r"not\s+visible",
    r"not\s+interactable",
    r"element.*hidden",
    r"visibility.*hidden",
    r"display.*none",
    r"offscreen",
    r"outside.*viewport",
    r"obscured",
    r"covered\s+by",
    r"overlapping",
]

_STALE_PATTERNS: list[str] = [
    r"stale",
    r"detached",
    r"removed\s+from.*dom",
    r"no\s+longer\s+attached",
    r"element.*destroyed",
    r"node.*garbage",
    r"execution\s+context.*destroyed",
]

_NAVIGATION_PATTERNS: list[str] = [
    r"net::err",
    r"navigation.*failed",
    r"page.*closed",
    r"target.*closed",
    r"connection.*refused",
    r"dns.*failed",
    r"ssl.*error",
    r"certificate",
    r"err_connection",
    r"err_name_not_resolved",
]

_DATA_PATTERNS: list[str] = [
    r"assertion.*fail",
    r"expected.*got",
    r"mismatch",
    r"unexpected\s+value",
    r"data.*validation",
    r"schema.*error",
]


def _match_patterns(text: str, patterns: list[str]) -> bool:
    """Check if text matches any of the given patterns."""
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)


# ── Healing Plan Builders ───────────────────────────


def _timing_healing_plans(category: FailureCategory) -> tuple[HealingPlan, ...]:
    return (
        HealingPlan(
            strategy=HealingStrategy.INCREASE_TIMEOUT,
            category=category,
            params={"multiplier": 2.0},
            confidence=0.7,
        ),
        HealingPlan(
            strategy=HealingStrategy.WAIT_AND_RETRY,
            category=category,
            params={"wait_ms": 2000},
            confidence=0.6,
        ),
        HealingPlan(
            strategy=HealingStrategy.WAIT_FOR_NETWORK,
            category=category,
            params={"timeout_ms": 5000},
            confidence=0.5,
        ),
    )


def _hidden_healing_plans(category: FailureCategory) -> tuple[HealingPlan, ...]:
    return (
        HealingPlan(
            strategy=HealingStrategy.SCROLL_INTO_VIEW,
            category=category,
            params={"behavior": "smooth"},
            confidence=0.8,
        ),
        HealingPlan(
            strategy=HealingStrategy.EXPAND_PARENT,
            category=category,
            params={"click_parent": True},
            confidence=0.5,
        ),
        HealingPlan(
            strategy=HealingStrategy.WAIT_AND_RETRY,
            category=category,
            params={"wait_ms": 1000},
            confidence=0.4,
        ),
    )


def _stale_healing_plans(category: FailureCategory) -> tuple[HealingPlan, ...]:
    return (
        HealingPlan(
            strategy=HealingStrategy.WAIT_AND_RETRY,
            category=category,
            params={"wait_ms": 500},
            confidence=0.7,
        ),
        HealingPlan(
            strategy=HealingStrategy.RE_EXTRACT,
            category=category,
            params={"full_page": True},
            confidence=0.6,
        ),
    )


def _navigation_healing_plans(category: FailureCategory) -> tuple[HealingPlan, ...]:
    return (
        HealingPlan(
            strategy=HealingStrategy.WAIT_FOR_NETWORK,
            category=category,
            params={"timeout_ms": 10000},
            confidence=0.6,
        ),
        HealingPlan(
            strategy=HealingStrategy.RETRY,
            category=category,
            params={"max_retries": 2},
            confidence=0.5,
        ),
    )


def _data_healing_plans(category: FailureCategory) -> tuple[HealingPlan, ...]:
    return (
        HealingPlan(
            strategy=HealingStrategy.RE_EXTRACT,
            category=category,
            params={"full_page": True},
            confidence=0.5,
        ),
        HealingPlan(
            strategy=HealingStrategy.WAIT_AND_RETRY,
            category=category,
            params={"wait_ms": 1000},
            confidence=0.3,
        ),
    )


def _selector_healing_plans(category: FailureCategory) -> tuple[HealingPlan, ...]:
    return (
        HealingPlan(
            strategy=HealingStrategy.RE_EXTRACT,
            category=category,
            params={"full_page": True},
            confidence=0.6,
        ),
        HealingPlan(
            strategy=HealingStrategy.WAIT_AND_RETRY,
            category=category,
            params={"wait_ms": 500},
            confidence=0.4,
        ),
    )


# ── Public API ──────────────────────────────────────


def classify_failure(
    exception: BaseException | None = None,
    error_message: str | None = None,
) -> ClassificationResult:
    """Classify a failure into one of 6 categories.

    Analyzes the exception type and error message to determine the
    failure category. Returns ordered healing plans for the category.

    Args:
        exception: The caught exception, if available.
        error_message: Error message string, if available.

    Returns:
        ClassificationResult with category and healing plans.
    """
    # Build combined error text
    parts: list[str] = []
    if error_message:
        parts.append(error_message)
    if exception is not None:
        parts.append(type(exception).__name__)
        parts.append(str(exception))
    raw = " ".join(parts) if parts else ""

    # Check exception type first
    if exception is not None:
        exc_name = type(exception).__name__.lower()
        if "timeout" in exc_name:
            return ClassificationResult(
                category=FailureCategory.TIMING_TIMEOUT,
                healing_plans=_timing_healing_plans(FailureCategory.TIMING_TIMEOUT),
                raw_error=raw,
            )

    # Pattern matching on error text
    if _match_patterns(raw, _TIMEOUT_PATTERNS):
        return ClassificationResult(
            category=FailureCategory.TIMING_TIMEOUT,
            healing_plans=_timing_healing_plans(FailureCategory.TIMING_TIMEOUT),
            raw_error=raw,
        )

    if _match_patterns(raw, _HIDDEN_PATTERNS):
        return ClassificationResult(
            category=FailureCategory.ELEMENT_HIDDEN,
            healing_plans=_hidden_healing_plans(FailureCategory.ELEMENT_HIDDEN),
            raw_error=raw,
        )

    if _match_patterns(raw, _STALE_PATTERNS):
        return ClassificationResult(
            category=FailureCategory.STALE_ELEMENT,
            healing_plans=_stale_healing_plans(FailureCategory.STALE_ELEMENT),
            raw_error=raw,
        )

    if _match_patterns(raw, _NAVIGATION_PATTERNS):
        return ClassificationResult(
            category=FailureCategory.NAVIGATION_INCOMPLETE,
            healing_plans=_navigation_healing_plans(
                FailureCategory.NAVIGATION_INCOMPLETE,
            ),
            raw_error=raw,
        )

    if _match_patterns(raw, _DATA_PATTERNS):
        return ClassificationResult(
            category=FailureCategory.DATA_MISMATCH,
            healing_plans=_data_healing_plans(FailureCategory.DATA_MISMATCH),
            raw_error=raw,
        )

    # Default: selector not found
    return ClassificationResult(
        category=FailureCategory.SELECTOR_NOT_FOUND,
        healing_plans=_selector_healing_plans(FailureCategory.SELECTOR_NOT_FOUND),
        raw_error=raw,
    )


def get_healing_plans(category: FailureCategory) -> tuple[HealingPlan, ...]:
    """Get healing plans for a specific failure category.

    Args:
        category: The failure category.

    Returns:
        Tuple of HealingPlan sorted by confidence (highest first).
    """
    plan_builders: dict[FailureCategory, _PlanBuilder] = {
        FailureCategory.TIMING_TIMEOUT: _timing_healing_plans,
        FailureCategory.ELEMENT_HIDDEN: _hidden_healing_plans,
        FailureCategory.STALE_ELEMENT: _stale_healing_plans,
        FailureCategory.NAVIGATION_INCOMPLETE: _navigation_healing_plans,
        FailureCategory.DATA_MISMATCH: _data_healing_plans,
        FailureCategory.SELECTOR_NOT_FOUND: _selector_healing_plans,
    }
    builder = plan_builders.get(category, _selector_healing_plans)
    return builder(category)
