"""Rule Promotion Engine — promotes proven patterns to Rule Engine rules.

When a pattern in the ``PatternDB`` accumulates enough successful executions,
the ``RulePromoter`` converts it into a ``RuleDefinition`` and registers it
with the ``IRuleEngine``.  This is the core of the "fewer LLM calls over time"
learning loop.

Usage::

    promoter = RulePromoter(pattern_db, rule_engine)
    promoted = await promoter.check_and_promote()
    # promoted is a list of newly registered RuleDefinition objects

    # During step execution:
    await promoter.record_step_result(result, intent, site, selector, method)
"""
from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from src.core.types import IRuleEngine, RuleDefinition, StepResult
from src.learning.canary_gate import CanaryConfig, evaluate_canary
from src.learning.pattern_db import Pattern, PatternDB

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ── Category inference ──────────────────────────────

_CATEGORY_KEYWORDS: list[tuple[list[str], str]] = [
    (["정렬", "sort"], "sort"),
    (["팝업", "popup", "close", "닫기", "modal"], "popup"),
    (["검색", "search"], "search"),
    (["필터", "filter"], "filter"),
    (["페이지", "pagination", "next", "다음", "이전", "prev"], "pagination"),
    (["로그인", "login", "auth", "sign"], "login"),
    (["에러", "error", "오류"], "error"),
]


def _infer_category(intent: str, method: str) -> str:
    """Infer a rule category from intent keywords and method.

    Args:
        intent: Natural-language intent string.
        method: Interaction method (click, type, etc.).

    Returns:
        A category string from the recognised set.
    """
    lower_intent = intent.lower()
    lower_method = method.lower()

    # Check intent keywords first
    for keywords, category in _CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in lower_intent:
                return category

    # Method-based fallback
    if lower_method == "type":
        return "search"

    return "search"


class RulePromoter:
    """Promotes proven PatternDB patterns to Rule Engine rules.

    Args:
        pattern_db: The pattern database to query for promotable patterns.
        rule_engine: The rule engine to register promoted rules with.
        min_success: Minimum number of successes for promotion.
        min_ratio: Minimum success ratio for promotion.
    """

    def __init__(
        self,
        pattern_db: PatternDB,
        rule_engine: IRuleEngine,
        min_success: int = 3,
        min_ratio: float = 0.8,
    ) -> None:
        self._pattern_db = pattern_db
        self._rule_engine = rule_engine
        self._min_success = min_success
        self._min_ratio = min_ratio
        self._promoted_ids: set[str] = set()  # Track already-promoted patterns

    async def check_and_promote(self) -> list[RuleDefinition]:
        """Query PatternDB for promotable patterns and register as rules.

        Only promotes patterns that have not already been promoted in this
        session (tracked by ``_promoted_ids``).

        Returns:
            List of newly promoted ``RuleDefinition`` objects.
        """
        promotable = await self._pattern_db.get_promotable(
            min_success=self._min_success,
            min_ratio=self._min_ratio,
        )

        promoted: list[RuleDefinition] = []
        for pattern in promotable:
            if pattern.pattern_id in self._promoted_ids:
                continue

            canary_config = CanaryConfig(
                min_trials=self._min_success,
                min_success_rate=self._min_ratio,
            )
            canary_result = await evaluate_canary(
                self._pattern_db, pattern.site, pattern.intent, pattern.selector,
                config=canary_config,
            )
            if not canary_result.promoted:
                logger.info(
                    "Canary gate rejected pattern %s: %s",
                    pattern.pattern_id,
                    canary_result.reason,
                )
                continue

            rule = await self.promote_pattern(pattern)
            promoted.append(rule)

        return promoted

    async def promote_pattern(self, pattern: Pattern) -> RuleDefinition:
        """Convert a Pattern into a RuleDefinition and register it.

        Args:
            pattern: The pattern to promote.

        Returns:
            The created ``RuleDefinition``.
        """
        rule_id = self._generate_rule_id(pattern)
        category = _infer_category(pattern.intent, pattern.method)

        rule = RuleDefinition(
            rule_id=rule_id,
            category=category,
            intent_pattern=pattern.intent,
            selector=pattern.selector,
            method=pattern.method,
            site_pattern=pattern.site,
            priority=10,  # Promoted rules get moderate priority
        )

        self._rule_engine.register_rule(rule)
        self._promoted_ids.add(pattern.pattern_id)

        logger.info(
            "Promoted pattern %s to rule %s (category=%s, success=%d)",
            pattern.pattern_id,
            rule_id,
            category,
            pattern.success_count,
        )

        return rule

    async def record_step_result(
        self,
        step_result: StepResult,
        intent: str,
        site: str,
        selector: str,
        method: str,
    ) -> None:
        """Record step success/failure in the PatternDB.

        Args:
            step_result: The result of the step execution.
            intent: Natural-language intent.
            site: Hostname or glob.
            selector: CSS selector used.
            method: Interaction method.
        """
        if step_result.success:
            await self._pattern_db.record_success(intent, site, selector, method)
            logger.debug("Recorded success for intent=%r site=%r", intent, site)
        else:
            await self._pattern_db.record_failure(intent, site, selector, method)
            logger.debug("Recorded failure for intent=%r site=%r", intent, site)

    @staticmethod
    def _generate_rule_id(pattern: Pattern) -> str:
        """Generate a unique rule_id from pattern data.

        Args:
            pattern: The pattern to generate an ID for.

        Returns:
            A string like ``promoted_<hash>``.
        """
        raw = f"{pattern.intent}|{pattern.site}|{pattern.selector}|{pattern.method}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        return f"promoted_{digest}"
