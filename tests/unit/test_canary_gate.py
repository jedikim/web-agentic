"""Tests for Canary Gate — regression check gate for selector cache promotion.

Covers trial count checks, success rate thresholds, baseline comparison,
regression detection, and configuration options.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.learning.canary_gate import CanaryConfig, CanaryResult, evaluate_canary

# ── Mock PatternDB ────────────────────────────────


def _make_mock_db(
    success: int = 0,
    fail: int = 0,
    baseline: float | None = None,
) -> MagicMock:
    """Create a mock PatternDB with configurable success rate and baseline."""
    total = success + fail
    rate = success / total if total > 0 else 0.0

    db = MagicMock()
    db.get_success_rate = AsyncMock(return_value=(success, fail, rate))
    db.get_baseline_rate = AsyncMock(return_value=baseline)
    return db


# ── Tests ─────────────────────────────────────────


class TestCanaryGate:
    """Tests for evaluate_canary function."""

    @pytest.mark.asyncio
    async def test_sufficient_trials_high_rate_promoted(self) -> None:
        """10 success, 1 fail should pass (rate ~0.91 > 0.8, trials 11 > 5)."""
        db = _make_mock_db(success=10, fail=1, baseline=0.85)

        result = await evaluate_canary(db, "example.com", "search", "#q")

        assert result.promoted is True
        assert result.success_rate == pytest.approx(10 / 11)
        assert result.baseline_rate == 0.85
        assert "Passed" in result.reason

    @pytest.mark.asyncio
    async def test_insufficient_trials_not_promoted(self) -> None:
        """2 success, 0 fail should fail (trials 2 < 5)."""
        db = _make_mock_db(success=2, fail=0)

        result = await evaluate_canary(db, "example.com", "search", "#q")

        assert result.promoted is False
        assert "Insufficient trials" in result.reason
        assert "2 < 5" in result.reason

    @pytest.mark.asyncio
    async def test_low_success_rate_not_promoted(self) -> None:
        """3 success, 7 fail should fail (rate 0.3 < 0.8)."""
        db = _make_mock_db(success=3, fail=7)

        result = await evaluate_canary(db, "shop.com", "sort", ".sort-btn")

        assert result.promoted is False
        assert "Low success rate" in result.reason
        assert result.success_rate == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_regression_vs_baseline_not_promoted(self) -> None:
        """Candidate 0.82, baseline 0.95 should fail (regression beyond 0.05 tolerance)."""
        # 82 success, 18 fail => rate 0.82 >= 0.80 (passes min_success_rate)
        # but 0.82 < 0.95 - 0.05 = 0.90 => regression detected
        db = _make_mock_db(success=82, fail=18, baseline=0.95)

        result = await evaluate_canary(db, "shop.com", "filter", ".f")

        assert result.promoted is False
        assert "Regression" in result.reason
        assert result.success_rate == pytest.approx(0.82)
        assert result.baseline_rate == 0.95

    @pytest.mark.asyncio
    async def test_no_regression_promoted(self) -> None:
        """Candidate 0.88, baseline 0.9 should pass (within 0.05 tolerance)."""
        # 88 success, 12 fail => rate 0.88, baseline 0.9
        # 0.88 >= 0.9 - 0.05 = 0.85 => pass
        db = _make_mock_db(success=88, fail=12, baseline=0.9)

        result = await evaluate_canary(db, "shop.com", "sort", "#s")

        assert result.promoted is True
        assert result.success_rate == pytest.approx(0.88)
        assert result.baseline_rate == 0.9
        assert "Passed all canary checks" in result.reason

    @pytest.mark.asyncio
    async def test_baseline_comparison_disabled(self) -> None:
        """With baseline_comparison=False, skip baseline check."""
        db = _make_mock_db(success=6, fail=1)
        config = CanaryConfig(baseline_comparison=False)

        result = await evaluate_canary(
            db, "example.com", "search", "#q", config=config
        )

        assert result.promoted is True
        assert result.baseline_rate is None
        assert "no baseline comparison" in result.reason
        db.get_baseline_rate.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_baseline_exists_promoted(self) -> None:
        """No existing baseline should pass if rate is sufficient."""
        db = _make_mock_db(success=8, fail=1, baseline=None)

        result = await evaluate_canary(db, "new-site.com", "click", ".btn")

        assert result.promoted is True
        assert result.baseline_rate is None
        assert "Passed all canary checks" in result.reason

    @pytest.mark.asyncio
    async def test_zero_trials_not_promoted(self) -> None:
        """Zero trials should fail."""
        db = _make_mock_db(success=0, fail=0)

        result = await evaluate_canary(db, "example.com", "any", "#x")

        assert result.promoted is False
        assert "Insufficient trials" in result.reason
        assert "0 < 5" in result.reason
        assert result.success_rate == 0.0


class TestCanaryConfig:
    """Tests for CanaryConfig defaults and custom values."""

    def test_default_values(self) -> None:
        config = CanaryConfig()
        assert config.min_trials == 5
        assert config.min_success_rate == 0.8
        assert config.baseline_comparison is True
        assert config.regression_tolerance == 0.05

    def test_custom_values(self) -> None:
        config = CanaryConfig(
            min_trials=10,
            min_success_rate=0.95,
            baseline_comparison=False,
            regression_tolerance=0.1,
        )
        assert config.min_trials == 10
        assert config.min_success_rate == 0.95
        assert config.baseline_comparison is False
        assert config.regression_tolerance == 0.1

    def test_frozen(self) -> None:
        config = CanaryConfig()
        with pytest.raises(AttributeError):
            config.min_trials = 10  # type: ignore[misc]


class TestCanaryResult:
    """Tests for CanaryResult immutability."""

    def test_frozen(self) -> None:
        result = CanaryResult(
            promoted=True, success_rate=0.9, baseline_rate=0.85, reason="ok"
        )
        with pytest.raises(AttributeError):
            result.promoted = False  # type: ignore[misc]
