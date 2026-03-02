"""Failure classification types for Phase 4 self-improvement."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class FailureType(enum.Enum):
    """4-level failure classification."""

    SELECTOR_NOT_FOUND = "selector_not_found"
    SELECTOR_STALE = "selector_stale"
    TIMEOUT = "timeout"
    OBSTACLE_BLOCKED = "obstacle_blocked"
    NAVIGATION_FAILED = "navigation_failed"
    VERIFICATION_FAILED = "verification_failed"
    STRATEGY_MISMATCH = "strategy_mismatch"
    AUTH_REQUIRED = "auth_required"
    CAPTCHA = "captcha"
    SITE_CHANGED = "site_changed"
    UNKNOWN = "unknown"


class RemediationAction(enum.Enum):
    """Automatic remediation actions."""

    FIX_SELECTOR = "fix_selector"
    FIX_OBSTACLE = "fix_obstacle"
    CHANGE_STRATEGY = "change_strategy"
    FULL_RECON = "full_recon"
    ADD_WAIT = "add_wait"
    HUMAN_HANDOFF = "human_handoff"


@dataclass
class FailureEvidence:
    """Evidence collected from a failed execution."""

    failure_type: FailureType = FailureType.UNKNOWN
    error_message: str = ""
    selector: str | None = None
    url: str = ""
    screenshot_path: str | None = None
    dom_snapshot: dict[str, Any] | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    remediation: RemediationAction = RemediationAction.HUMAN_HANDOFF
    extra: dict[str, Any] = field(default_factory=dict)

    def classify_remediation(self) -> RemediationAction:
        """Determine remediation based on failure type."""
        mapping: dict[FailureType, RemediationAction] = {
            FailureType.SELECTOR_NOT_FOUND: RemediationAction.FIX_SELECTOR,
            FailureType.SELECTOR_STALE: RemediationAction.FIX_SELECTOR,
            FailureType.TIMEOUT: RemediationAction.ADD_WAIT,
            FailureType.OBSTACLE_BLOCKED: RemediationAction.FIX_OBSTACLE,
            FailureType.NAVIGATION_FAILED: RemediationAction.CHANGE_STRATEGY,
            FailureType.VERIFICATION_FAILED: RemediationAction.CHANGE_STRATEGY,
            FailureType.STRATEGY_MISMATCH: RemediationAction.CHANGE_STRATEGY,
            FailureType.SITE_CHANGED: RemediationAction.FULL_RECON,
            FailureType.AUTH_REQUIRED: RemediationAction.HUMAN_HANDOFF,
            FailureType.CAPTCHA: RemediationAction.HUMAN_HANDOFF,
        }
        self.remediation = mapping.get(
            self.failure_type, RemediationAction.HUMAN_HANDOFF
        )
        return self.remediation
