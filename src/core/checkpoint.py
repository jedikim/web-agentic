"""Screenshot-based checkpoint evaluation for step verification.

Pure function: confidence + threshold + sensitiveAction -> decision.
Used by the orchestrator to gate step progression.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CheckpointDecision(StrEnum):
    """Outcome of a checkpoint evaluation."""

    GO = "go"
    NOT_GO = "not_go"
    ASK_USER = "ask_user"


@dataclass(frozen=True)
class CheckpointConfig:
    """Threshold configuration for checkpoint gating.

    Attributes:
        go_threshold: Minimum confidence to proceed automatically.
        ask_threshold: Minimum confidence to ask user (below = NOT_GO).
        enabled: Whether checkpoint evaluation is active.
    """

    go_threshold: float = 0.8
    ask_threshold: float = 0.5
    enabled: bool = True


@dataclass(frozen=True)
class CheckpointResult:
    """Result of a checkpoint evaluation.

    Attributes:
        decision: The gating decision (GO, NOT_GO, ASK_USER).
        confidence: The input confidence score.
        reason: Human-readable explanation.
    """

    decision: CheckpointDecision
    confidence: float
    reason: str


def evaluate_checkpoint(
    confidence: float,
    config: CheckpointConfig,
    sensitive_action: bool = False,
) -> CheckpointResult:
    """Pure function: confidence + threshold + sensitiveAction -> decision.

    Args:
        confidence: 0.0 to 1.0 confidence score.
        config: Threshold configuration.
        sensitive_action: If True, raise all thresholds by 0.1.

    Returns:
        CheckpointResult with decision, confidence, and reason.
    """
    if not config.enabled:
        return CheckpointResult(
            decision=CheckpointDecision.GO,
            confidence=confidence,
            reason="Checkpoint disabled",
        )

    go_thresh = config.go_threshold + (0.1 if sensitive_action else 0.0)
    ask_thresh = config.ask_threshold + (0.1 if sensitive_action else 0.0)

    if confidence >= go_thresh:
        return CheckpointResult(
            decision=CheckpointDecision.GO,
            confidence=confidence,
            reason=f"Confidence {confidence:.2f} >= go threshold {go_thresh:.2f}",
        )
    elif confidence >= ask_thresh:
        return CheckpointResult(
            decision=CheckpointDecision.ASK_USER,
            confidence=confidence,
            reason=(
                f"Confidence {confidence:.2f} between "
                f"ask ({ask_thresh:.2f}) and go ({go_thresh:.2f})"
            ),
        )
    else:
        return CheckpointResult(
            decision=CheckpointDecision.NOT_GO,
            confidence=confidence,
            reason=f"Confidence {confidence:.2f} < ask threshold {ask_thresh:.2f}",
        )
