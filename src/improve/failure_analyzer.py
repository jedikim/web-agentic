"""Failure classification — 4-level escalation from pattern to LLM."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from src.llm.router import LLMRouter
from src.models.failure import FailureEvidence, FailureType

logger = logging.getLogger(__name__)

# ── Level 1: Playwright error type mapping ──

_PW_ERROR_MAP: dict[str, FailureType] = {
    "TimeoutError": FailureType.TIMEOUT,
    "TargetClosedError": FailureType.NAVIGATION_FAILED,
    "BrowserClosedError": FailureType.NAVIGATION_FAILED,
}

# ── Level 2: Verification failure code mapping ──

_VERIFY_CODE_MAP: dict[str, FailureType] = {
    "selector_not_found": FailureType.SELECTOR_NOT_FOUND,
    "element_not_visible": FailureType.SELECTOR_STALE,
    "element_detached": FailureType.SELECTOR_STALE,
    "url_mismatch": FailureType.NAVIGATION_FAILED,
    "content_mismatch": FailureType.VERIFICATION_FAILED,
    "state_unchanged": FailureType.VERIFICATION_FAILED,
}

# ── Level 3: String pattern rules (regex → FailureType) ──

_STRING_PATTERNS: list[tuple[re.Pattern[str], FailureType]] = [
    (re.compile(r"waiting for selector", re.I), FailureType.SELECTOR_NOT_FOUND),
    (re.compile(r"no element found", re.I), FailureType.SELECTOR_NOT_FOUND),
    (re.compile(r"element is not attached", re.I), FailureType.SELECTOR_STALE),
    (re.compile(r"element is not visible", re.I), FailureType.SELECTOR_STALE),
    (re.compile(r"timeout \d+ms exceeded", re.I), FailureType.TIMEOUT),
    (re.compile(r"net::ERR_", re.I), FailureType.NAVIGATION_FAILED),
    (re.compile(r"navigation.*(failed|aborted)", re.I), FailureType.NAVIGATION_FAILED),
    (re.compile(r"captcha|recaptcha|hcaptcha", re.I), FailureType.CAPTCHA),
    (re.compile(r"login.*(required|needed)|sign.in", re.I), FailureType.AUTH_REQUIRED),
    (re.compile(r"(popup|modal|overlay|banner).*block", re.I), FailureType.OBSTACLE_BLOCKED),
    (re.compile(r"cookie.*(consent|accept|banner)", re.I), FailureType.OBSTACLE_BLOCKED),
    (re.compile(r"layout.*changed|dom.*restructured", re.I), FailureType.SITE_CHANGED),
]

# ── LLM classification prompt ──

_CLASSIFY_PROMPT = """Classify this web automation failure into exactly one type.

Error: {error_message}
Context URL: {url}
Selector: {selector}
Extra context: {extra}

Types (pick one):
- selector_not_found
- selector_stale
- timeout
- obstacle_blocked
- navigation_failed
- verification_failed
- strategy_mismatch
- auth_required
- captcha
- site_changed
- unknown

Respond with JSON: {{"failure_type": "<type>", "reason": "<brief reason>"}}"""


@dataclass
class AnalysisContext:
    """Contextual information for failure analysis."""

    url: str = ""
    selector: str | None = None
    verification_code: str | None = None
    screenshot_path: str | None = None
    dom_snapshot: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None


class FailureAnalyzer:
    """4-level failure classifier with LLM escalation.

    Levels:
        1. Playwright error type mapping (cheapest)
        2. Verification failure code mapping
        3. String pattern rules (regex)
        4. LLM classification (most expensive, last resort)
    """

    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self._llm = llm_router

    async def analyze(
        self,
        error: Exception | str,
        context: AnalysisContext | None = None,
    ) -> FailureEvidence:
        """Classify a failure and return evidence with remediation.

        Args:
            error: The exception or error message string.
            context: Optional contextual information (URL, selector, etc.).

        Returns:
            FailureEvidence with classified type and remediation action.
        """
        ctx = context or AnalysisContext()
        error_msg = str(error)
        error_type_name = type(error).__name__ if isinstance(error, Exception) else ""

        # Level 1: Playwright error type
        ft = _PW_ERROR_MAP.get(error_type_name)

        # Level 2: Verification failure code
        if ft is None and ctx.verification_code:
            ft = _VERIFY_CODE_MAP.get(ctx.verification_code)

        # Level 3: String pattern rules
        if ft is None:
            ft = self._match_string_patterns(error_msg)

        # Level 4: LLM classification (only if L1-L3 all failed)
        if ft is None and self._llm is not None:
            ft = await self._llm_classify(error_msg, ctx)

        if ft is None:
            ft = FailureType.UNKNOWN

        evidence = FailureEvidence(
            failure_type=ft,
            error_message=error_msg,
            selector=ctx.selector,
            url=ctx.url,
            screenshot_path=ctx.screenshot_path,
            dom_snapshot=ctx.dom_snapshot,
            extra=ctx.extra or {},
        )
        evidence.classify_remediation()
        return evidence

    @staticmethod
    def _match_string_patterns(msg: str) -> FailureType | None:
        """Level 3: regex pattern matching against error message."""
        for pattern, ft in _STRING_PATTERNS:
            if pattern.search(msg):
                return ft
        return None

    async def _llm_classify(
        self, error_msg: str, ctx: AnalysisContext
    ) -> FailureType | None:
        """Level 4: LLM-based classification (expensive, last resort)."""
        assert self._llm is not None
        prompt = _CLASSIFY_PROMPT.format(
            error_message=error_msg,
            url=ctx.url or "unknown",
            selector=ctx.selector or "none",
            extra=json.dumps(ctx.extra or {}, ensure_ascii=False),
        )
        try:
            raw = await self._llm.complete(
                "fast",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.0,
            )
            data = json.loads(raw)
            ft_str = data.get("failure_type", "unknown")
            return FailureType(ft_str)
        except (json.JSONDecodeError, ValueError, Exception) as exc:
            logger.warning("LLM classification failed: %s", exc)
            return None
