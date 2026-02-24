"""Tests for src.core.checkpoint — pure function checkpoint evaluation."""
from __future__ import annotations

from src.core.checkpoint import (
    CheckpointConfig,
    CheckpointDecision,
    CheckpointResult,
    evaluate_checkpoint,
)


def _default_config() -> CheckpointConfig:
    return CheckpointConfig(go_threshold=0.8, ask_threshold=0.5, enabled=True)


class TestEvaluateCheckpoint:
    """Tests for the evaluate_checkpoint pure function."""

    def test_high_confidence_returns_go(self) -> None:
        result = evaluate_checkpoint(0.9, _default_config())
        assert result.decision == CheckpointDecision.GO

    def test_medium_confidence_returns_ask_user(self) -> None:
        result = evaluate_checkpoint(0.6, _default_config())
        assert result.decision == CheckpointDecision.ASK_USER

    def test_low_confidence_returns_not_go(self) -> None:
        result = evaluate_checkpoint(0.3, _default_config())
        assert result.decision == CheckpointDecision.NOT_GO

    def test_sensitive_action_raises_thresholds(self) -> None:
        # 0.85 normally >= 0.8 (GO), but with sensitive +0.1 -> threshold 0.9
        result = evaluate_checkpoint(0.85, _default_config(), sensitive_action=True)
        assert result.decision == CheckpointDecision.ASK_USER

    def test_disabled_always_returns_go(self) -> None:
        config = CheckpointConfig(enabled=False)
        result = evaluate_checkpoint(0.1, config)
        assert result.decision == CheckpointDecision.GO
        assert "disabled" in result.reason.lower()

    def test_boundary_go_threshold(self) -> None:
        result = evaluate_checkpoint(0.8, _default_config())
        assert result.decision == CheckpointDecision.GO

    def test_boundary_ask_threshold(self) -> None:
        result = evaluate_checkpoint(0.5, _default_config())
        assert result.decision == CheckpointDecision.ASK_USER

    def test_below_ask_threshold(self) -> None:
        result = evaluate_checkpoint(0.49, _default_config())
        assert result.decision == CheckpointDecision.NOT_GO

    def test_sensitive_boundary(self) -> None:
        # sensitive raises go_threshold to 0.9; 0.9 exactly should be GO
        result = evaluate_checkpoint(0.9, _default_config(), sensitive_action=True)
        assert result.decision == CheckpointDecision.GO

    def test_checkpoint_result_has_reason(self) -> None:
        result = evaluate_checkpoint(0.6, _default_config())
        assert isinstance(result, CheckpointResult)
        assert result.confidence == 0.6
        assert len(result.reason) > 0
