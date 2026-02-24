"""Tests for src.core.retry_policy — RetryDecision, should_retry, is_retryable."""
from __future__ import annotations

from src.core.retry_policy import (
    NON_RETRYABLE_CODES,
    RetryDecision,
    is_retryable,
    should_retry,
)


def test_retryable_code_within_limit() -> None:
    """A retryable failure code with remaining attempts should allow retry."""
    decision = should_retry("network_error", attempt=0, max_attempts=3)
    assert decision == RetryDecision(retry=True, reason="retryable")


def test_retryable_code_at_max_attempts() -> None:
    """Even a retryable code must stop when attempt >= max_attempts."""
    decision = should_retry("network_error", attempt=3, max_attempts=3)
    assert decision.retry is False
    assert decision.reason == "max attempts reached"


def test_non_retryable_auth_blocked() -> None:
    """auth_blocked must never be retried."""
    decision = should_retry("auth_blocked", attempt=0, max_attempts=5)
    assert decision.retry is False
    assert "non-retryable" in decision.reason
    assert "auth_blocked" in decision.reason


def test_non_retryable_review_rejected() -> None:
    """review_rejected must never be retried."""
    decision = should_retry("review_rejected", attempt=0, max_attempts=5)
    assert decision.retry is False
    assert "non-retryable" in decision.reason


def test_non_retryable_captcha_detected() -> None:
    """captcha_detected must never be retried."""
    decision = should_retry("captcha_detected", attempt=0, max_attempts=5)
    assert decision.retry is False
    assert "captcha_detected" in decision.reason


def test_is_retryable_convenience() -> None:
    """is_retryable returns False for non-retryable codes, True otherwise."""
    for code in NON_RETRYABLE_CODES:
        assert is_retryable(code) is False
    assert is_retryable("network_error") is True


def test_unknown_code_is_retryable() -> None:
    """An unrecognised failure code should default to retryable."""
    decision = should_retry("some_unknown_failure", attempt=0, max_attempts=3)
    assert decision.retry is True
    assert is_retryable("some_unknown_failure") is True


def test_zero_max_attempts() -> None:
    """With max_attempts=0, even attempt 0 should not retry."""
    decision = should_retry("network_error", attempt=0, max_attempts=0)
    assert decision.retry is False
    assert decision.reason == "max attempts reached"
