"""F(Fallback Router) — Failure classification and cost-cascading recovery routing.

Token cost: 0 (pure rule-based, no LLM calls).

The fallback router receives exceptions from step execution and:

* **classify** — maps the exception to a ``FailureCode`` using the error's
  type, its message text, and the current ``StepContext`` (page state, attempt).
* **route** — returns a ``RecoveryPlan`` for the classified failure, following
  the P7 cost-cascading principle (cheapest strategy first).
* **get_escalation_chain** — returns the full ordered chain of recovery plans
  for progressive escalation (retry → LLM → Vision → Human Handoff).
* **should_escalate** — decides whether the current attempt warrants escalation.
* **record_outcome / get_stats** — tracks failure/recovery statistics.
"""
from __future__ import annotations

import logging
from typing import Any

from src.core.types import (
    AutomationError,
    AuthRequiredError,
    BotDetectedError,
    CaptchaDetectedError,
    FailureCode,
    NavigationBlockedError,
    NetworkError,
    NotInteractableError,
    RecoveryPlan,
    SelectorNotFoundError,
    StateNotChangedError,
    StepContext,
    VisualAmbiguityError,
)

logger = logging.getLogger(__name__)

# ── Exception-to-FailureCode Mapping ─────────────────

_EXCEPTION_MAP: dict[type[AutomationError], FailureCode] = {
    SelectorNotFoundError: FailureCode.SELECTOR_NOT_FOUND,
    NotInteractableError: FailureCode.NOT_INTERACTABLE,
    StateNotChangedError: FailureCode.STATE_NOT_CHANGED,
    VisualAmbiguityError: FailureCode.VISUAL_AMBIGUITY,
    NetworkError: FailureCode.NETWORK_ERROR,
    CaptchaDetectedError: FailureCode.CAPTCHA_DETECTED,
    AuthRequiredError: FailureCode.AUTH_REQUIRED,
    NavigationBlockedError: FailureCode.NAVIGATION_BLOCKED,
    BotDetectedError: FailureCode.BOT_DETECTED,
}

# ── FailureCode-to-RecoveryPlan Mapping ──────────────

_ROUTE_TABLE: dict[FailureCode, RecoveryPlan] = {
    FailureCode.SELECTOR_NOT_FOUND: RecoveryPlan(
        strategy="escalate_llm",
        tier=1,
        params={"mode": "select"},
    ),
    FailureCode.NOT_INTERACTABLE: RecoveryPlan(
        strategy="retry",
        tier=1,
        params={"wait_ms": 1000, "scroll": True},
    ),
    FailureCode.STATE_NOT_CHANGED: RecoveryPlan(
        strategy="retry",
        tier=1,
        params={"wait_ms": 2000},
    ),
    FailureCode.VISUAL_AMBIGUITY: RecoveryPlan(
        strategy="escalate_vision",
        tier=2,
        params={"mode": "detect"},
    ),
    FailureCode.NETWORK_ERROR: RecoveryPlan(
        strategy="retry",
        tier=1,
        params={"wait_ms": 3000, "max_extra": 2},
    ),
    FailureCode.QUEUE_DETECTED: RecoveryPlan(
        strategy="retry",
        tier=1,
        params={"wait_ms": 5000},
    ),
    FailureCode.CAPTCHA_DETECTED: RecoveryPlan(
        strategy="human_handoff",
        tier=3,
        params={"type": "captcha"},
    ),
    FailureCode.AUTH_REQUIRED: RecoveryPlan(
        strategy="human_handoff",
        tier=3,
        params={"type": "auth"},
    ),
    FailureCode.DYNAMIC_LAYOUT: RecoveryPlan(
        strategy="escalate_llm",
        tier=2,
        params={"mode": "plan", "re_extract": True},
    ),
    FailureCode.NAVIGATION_BLOCKED: RecoveryPlan(
        strategy="skip",
        tier=1,
        params={"reason": "robots_txt"},
    ),
    FailureCode.BOT_DETECTED: RecoveryPlan(
        strategy="retry",
        tier=2,
        params={"wait_ms": 5000, "stealth_upgrade": True},
    ),
}

# ── Escalation Chains ────────────────────────────────
# Each chain is ordered cheapest-first (P7 cost-cascading).
# The first entry is always the primary strategy from _ROUTE_TABLE;
# subsequent entries represent progressive escalation.

_ESCALATION_CHAINS: dict[FailureCode, list[RecoveryPlan]] = {
    FailureCode.SELECTOR_NOT_FOUND: [
        RecoveryPlan(strategy="retry", tier=1, params={"wait_ms": 500}),
        RecoveryPlan(strategy="escalate_llm", tier=1, params={"mode": "select"}),
        RecoveryPlan(strategy="escalate_llm", tier=2, params={"mode": "plan", "re_extract": True}),
        RecoveryPlan(strategy="escalate_vision", tier=2, params={"mode": "detect"}),
        RecoveryPlan(strategy="human_handoff", tier=3, params={"type": "selector"}),
    ],
    FailureCode.NOT_INTERACTABLE: [
        RecoveryPlan(strategy="retry", tier=1, params={"wait_ms": 1000, "scroll": True}),
        RecoveryPlan(strategy="escalate_llm", tier=1, params={"mode": "select"}),
        RecoveryPlan(strategy="escalate_vision", tier=2, params={"mode": "detect"}),
        RecoveryPlan(strategy="human_handoff", tier=3, params={"type": "interactable"}),
    ],
    FailureCode.STATE_NOT_CHANGED: [
        RecoveryPlan(strategy="retry", tier=1, params={"wait_ms": 2000}),
        RecoveryPlan(strategy="escalate_llm", tier=1, params={"mode": "select"}),
        RecoveryPlan(strategy="escalate_vision", tier=2, params={"mode": "detect"}),
        RecoveryPlan(strategy="human_handoff", tier=3, params={"type": "state"}),
    ],
    FailureCode.VISUAL_AMBIGUITY: [
        RecoveryPlan(strategy="escalate_vision", tier=2, params={"mode": "detect"}),
        RecoveryPlan(strategy="escalate_llm", tier=2, params={"mode": "plan", "re_extract": True}),
        RecoveryPlan(strategy="human_handoff", tier=3, params={"type": "ambiguity"}),
    ],
    FailureCode.NETWORK_ERROR: [
        RecoveryPlan(strategy="retry", tier=1, params={"wait_ms": 3000, "max_extra": 2}),
        RecoveryPlan(strategy="retry", tier=1, params={"wait_ms": 5000, "max_extra": 3}),
        RecoveryPlan(strategy="human_handoff", tier=3, params={"type": "network"}),
    ],
    FailureCode.QUEUE_DETECTED: [
        RecoveryPlan(strategy="retry", tier=1, params={"wait_ms": 5000}),
        RecoveryPlan(strategy="retry", tier=1, params={"wait_ms": 10000}),
        RecoveryPlan(strategy="human_handoff", tier=3, params={"type": "queue"}),
    ],
    FailureCode.CAPTCHA_DETECTED: [
        RecoveryPlan(strategy="human_handoff", tier=3, params={"type": "captcha"}),
    ],
    FailureCode.AUTH_REQUIRED: [
        RecoveryPlan(strategy="human_handoff", tier=3, params={"type": "auth"}),
    ],
    FailureCode.DYNAMIC_LAYOUT: [
        RecoveryPlan(strategy="escalate_llm", tier=2, params={"mode": "plan", "re_extract": True}),
        RecoveryPlan(strategy="escalate_vision", tier=2, params={"mode": "detect"}),
        RecoveryPlan(strategy="human_handoff", tier=3, params={"type": "layout"}),
    ],
    FailureCode.NAVIGATION_BLOCKED: [
        RecoveryPlan(strategy="skip", tier=1, params={"reason": "robots_txt"}),
        RecoveryPlan(strategy="human_handoff", tier=3, params={"type": "navigation"}),
    ],
    FailureCode.BOT_DETECTED: [
        RecoveryPlan(strategy="retry", tier=2, params={"wait_ms": 5000, "stealth_upgrade": True}),
        RecoveryPlan(strategy="retry", tier=2, params={"wait_ms": 10000, "clear_cookies": True}),
        RecoveryPlan(strategy="human_handoff", tier=3, params={"type": "bot_detection"}),
    ],
}

# Attempt threshold beyond which selector failures are reclassified as DYNAMIC_LAYOUT.
_DYNAMIC_LAYOUT_ATTEMPT_THRESHOLD = 3


# ── FallbackRouter ───────────────────────────────────


class FallbackRouter:
    """Failure classification and cost-cascading recovery router.

    Implements the ``IFallbackRouter`` Protocol.

    The router classifies exceptions into ``FailureCode`` values and maps them
    to ``RecoveryPlan`` objects using the cheapest-first cost-cascading principle.

    Example::

        router = create_fallback_router()
        code = router.classify(error, context)
        plan = router.route(code)
        chain = router.get_escalation_chain(code)
    """

    def __init__(self) -> None:
        self._stats: dict[FailureCode, dict[str, int]] = {}

    # ── Public API (IFallbackRouter Protocol) ────────

    def classify(self, error: Exception, context: StepContext) -> FailureCode:
        """Classify an exception into a ``FailureCode``.

        Classification priority:
        1. Known ``AutomationError`` subclasses with a ``failure_code`` attribute.
        2. Generic exceptions — heuristic classification by message text and
           page state signals.
        3. Attempt-aware reclassification — high attempt counts suggest dynamic
           layout issues rather than simple selector misses.

        Args:
            error: The exception that occurred during step execution.
            context: Current step execution context (page state, attempt count).

        Returns:
            The classified ``FailureCode``.
        """
        # 1. Direct mapping for known AutomationError subclasses.
        for exc_type, code in _EXCEPTION_MAP.items():
            if isinstance(error, exc_type):
                return self._maybe_reclassify(code, context)

        # 2. Heuristic classification for generic exceptions.
        code = self._heuristic_classify(error, context)
        return self._maybe_reclassify(code, context)

    def route(self, failure: FailureCode) -> RecoveryPlan:
        """Return the primary ``RecoveryPlan`` for a failure code.

        The plan follows the P7 cost-cascading principle — the cheapest viable
        strategy is returned first.

        Args:
            failure: The classified failure code.

        Returns:
            A ``RecoveryPlan`` with strategy, tier, and parameters.
        """
        plan = _ROUTE_TABLE.get(failure)
        if plan is not None:
            return plan

        # Defensive fallback — should not happen with well-defined FailureCodes.
        logger.warning("No route for failure code %s; defaulting to retry", failure)
        return RecoveryPlan(strategy="retry", tier=1, params={"wait_ms": 1000})

    # ── Extended API ─────────────────────────────────

    def get_escalation_chain(self, failure: FailureCode) -> list[RecoveryPlan]:
        """Return the full ordered chain of recovery plans for progressive escalation.

        The chain is ordered cheapest-first (retry -> LLM Flash -> LLM Pro ->
        Vision -> Human Handoff).

        Args:
            failure: The classified failure code.

        Returns:
            Ordered list of ``RecoveryPlan`` objects.
        """
        chain = _ESCALATION_CHAINS.get(failure)
        if chain is not None:
            return list(chain)  # Return a copy to prevent mutation.

        # Fallback: return the primary plan only.
        return [self.route(failure)]

    def should_escalate(self, failure: FailureCode, attempt: int) -> bool:
        """Determine whether the current attempt warrants escalation.

        Escalation logic:
        - attempt 0: never escalate (first try).
        - attempt >= 1: escalate if the chain has more entries available.
        - CAPTCHA_DETECTED / AUTH_REQUIRED: always escalate (immediate handoff).

        Args:
            failure: The classified failure code.
            attempt: Current attempt number (0-based).

        Returns:
            True if the attempt should escalate to the next recovery tier.
        """
        # Immediate-handoff failures always escalate.
        if failure in (FailureCode.CAPTCHA_DETECTED, FailureCode.AUTH_REQUIRED):
            return True

        # First attempt — use primary strategy, no escalation.
        if attempt <= 0:
            return False

        # Escalate if the chain has more entries than the current attempt.
        chain = self.get_escalation_chain(failure)
        return attempt < len(chain)

    def record_outcome(self, failure: FailureCode, recovered: bool) -> None:
        """Record whether a failure was successfully recovered.

        Args:
            failure: The failure code that was observed.
            recovered: True if recovery succeeded, False otherwise.
        """
        if failure not in self._stats:
            self._stats[failure] = {"total": 0, "recovered": 0, "failed": 0}

        self._stats[failure]["total"] += 1
        if recovered:
            self._stats[failure]["recovered"] += 1
        else:
            self._stats[failure]["failed"] += 1

    def get_stats(self) -> dict[str, Any]:
        """Return failure/recovery statistics.

        Returns:
            Dictionary mapping failure code values to their statistics
            (total, recovered, failed, recovery_rate).
        """
        result: dict[str, Any] = {}
        for code, counts in self._stats.items():
            total = counts["total"]
            recovered = counts["recovered"]
            result[code.value] = {
                "total": total,
                "recovered": recovered,
                "failed": counts["failed"],
                "recovery_rate": recovered / total if total > 0 else 0.0,
            }
        return result

    # ── Private Helpers ──────────────────────────────

    def _heuristic_classify(self, error: Exception, context: StepContext) -> FailureCode:
        """Classify a generic (non-AutomationError) exception using heuristics.

        Checks error message text and page state signals in priority order.

        Args:
            error: The generic exception.
            context: Current step context.

        Returns:
            The heuristically determined ``FailureCode``.
        """
        msg = str(error).lower()

        # Message-based heuristics.
        if "timeout" in msg:
            return FailureCode.NETWORK_ERROR
        if "captcha" in msg or "challenge" in msg:
            return FailureCode.CAPTCHA_DETECTED
        if "robots.txt" in msg or "navigation blocked" in msg:
            return FailureCode.NAVIGATION_BLOCKED
        if any(kw in msg for kw in ("cloudflare", "bot detected", "access denied", "403")):
            return FailureCode.BOT_DETECTED

        # Page-state heuristics.
        if context.page_state.has_captcha:
            return FailureCode.CAPTCHA_DETECTED
        if context.page_state.has_popup:
            return FailureCode.NOT_INTERACTABLE

        # Default.
        return FailureCode.SELECTOR_NOT_FOUND

    def _maybe_reclassify(self, code: FailureCode, context: StepContext) -> FailureCode:
        """Reclassify based on attempt count if applicable.

        After many failed attempts with SELECTOR_NOT_FOUND, the issue is more
        likely a dynamic layout change than a simple missing element.

        Args:
            code: The initially classified failure code.
            context: Current step context.

        Returns:
            The (potentially reclassified) failure code.
        """
        if (
            code == FailureCode.SELECTOR_NOT_FOUND
            and context.attempt >= _DYNAMIC_LAYOUT_ATTEMPT_THRESHOLD
        ):
            logger.info(
                "Reclassifying SELECTOR_NOT_FOUND → DYNAMIC_LAYOUT after %d attempts",
                context.attempt,
            )
            return FailureCode.DYNAMIC_LAYOUT
        return code


# ── Factory ──────────────────────────────────────────


def create_fallback_router() -> FallbackRouter:
    """Create and return a new ``FallbackRouter`` instance.

    Returns:
        A configured ``FallbackRouter``.
    """
    return FallbackRouter()
