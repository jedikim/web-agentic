"""Retry policy — decides whether a failed step should be retried.

Centralises retry/non-retry classification so that the orchestrator and
fallback router can make consistent decisions without duplicating logic.
"""
from __future__ import annotations

from dataclasses import dataclass

# Failure codes that must never be retried regardless of remaining attempts.
NON_RETRYABLE_CODES: frozenset[str] = frozenset({
    "auth_blocked",
    "review_rejected",
    "captcha_detected",
})


@dataclass(frozen=True)
class RetryDecision:
    """Immutable result of a retry-policy evaluation.

    Attributes:
        retry: Whether the step should be retried.
        reason: Human-readable explanation of the decision.
    """

    retry: bool
    reason: str


def should_retry(
    failure_code: str,
    attempt: int,
    max_attempts: int,
) -> RetryDecision:
    """Evaluate whether a failed step should be retried.

    Args:
        failure_code: The failure classification code (snake_case).
        attempt: Current attempt number (0-based).
        max_attempts: Maximum number of attempts allowed.

    Returns:
        A ``RetryDecision`` indicating whether to retry and why.
    """
    if attempt >= max_attempts:
        return RetryDecision(retry=False, reason="max attempts reached")
    if failure_code in NON_RETRYABLE_CODES:
        return RetryDecision(retry=False, reason=f"non-retryable: {failure_code}")
    return RetryDecision(retry=True, reason="retryable")


def is_retryable(failure_code: str) -> bool:
    """Convenience check: is *failure_code* retryable at all?

    This ignores attempt counts and only checks the code itself.

    Args:
        failure_code: The failure classification code (snake_case).

    Returns:
        ``True`` if the code is not in ``NON_RETRYABLE_CODES``.
    """
    return failure_code not in NON_RETRYABLE_CODES
