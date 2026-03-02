"""Result verifier — post-execution verification checks.

Supports three verification modes: URL pattern matching, DOM selector
existence, and network response inspection.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ── Browser Protocol ──


class PageLike(Protocol):
    """Minimal page interface for verification."""

    @property
    def url(self) -> str: ...
    async def query_selector(self, selector: str) -> Any: ...
    async def evaluate(self, expression: str) -> Any: ...
    async def wait_for_selector(
        self, selector: str, **kwargs: Any
    ) -> Any: ...


class BrowserLike(Protocol):
    """Browser wrapper providing page access."""

    async def get_page(self) -> PageLike: ...


# ── Result dataclasses ──


@dataclass
class CheckResult:
    """Outcome of a single verification check."""

    mode: str  # "url" | "dom" | "network"
    passed: bool = False
    expected: str = ""
    actual: str = ""
    detail: str = ""


@dataclass
class VerificationResult:
    """Aggregate outcome of all verification checks."""

    passed: bool = False
    checks: list[CheckResult] = field(default_factory=list)
    reason: str = ""


# ── Expected specification ──


@dataclass
class ExpectedOutcome:
    """Specification of what a successful execution should produce.

    At least one field should be non-None for verification to be meaningful.
    """

    url_pattern: str | None = None       # regex or substring
    dom_selector: str | None = None      # CSS selector that must exist
    dom_text: str | None = None          # text content expected in selector
    network_url_pattern: str | None = None  # API URL substring
    network_status: int | None = None    # expected HTTP status


# ── Verifier ──


class ResultVerifier:
    """Post-execution result verification.

    Runs all applicable checks based on which fields in the expected
    outcome are populated.
    """

    def __init__(self, *, dom_wait_ms: int = 3000) -> None:
        self._dom_wait_ms = dom_wait_ms

    async def verify(
        self,
        expected: ExpectedOutcome,
        browser: BrowserLike,
    ) -> VerificationResult:
        """Run all applicable verification checks.

        Args:
            expected: The expected outcome specification.
            browser: Browser wrapper for page inspection.

        Returns:
            VerificationResult with individual check results.
        """
        page = await browser.get_page()
        checks: list[CheckResult] = []

        if expected.url_pattern is not None:
            checks.append(self._check_url(page, expected.url_pattern))

        if expected.dom_selector is not None:
            checks.append(
                await self._check_dom(
                    page, expected.dom_selector, expected.dom_text
                )
            )

        if expected.network_url_pattern is not None:
            checks.append(
                await self._check_network(
                    page,
                    expected.network_url_pattern,
                    expected.network_status,
                )
            )

        if not checks:
            return VerificationResult(
                passed=True,
                checks=[],
                reason="no_checks_specified",
            )

        all_passed = all(c.passed for c in checks)
        failed = [c for c in checks if not c.passed]
        reason = "all_passed" if all_passed else (
            "; ".join(f"{c.mode}: {c.detail}" for c in failed)
        )

        return VerificationResult(
            passed=all_passed,
            checks=checks,
            reason=reason,
        )

    @staticmethod
    def _check_url(page: PageLike, pattern: str) -> CheckResult:
        """Verify the current URL matches the expected pattern.

        Supports both substring matching and regex patterns.
        """
        current_url = page.url
        # Try regex first.
        try:
            matched = bool(re.search(pattern, current_url))
        except re.error:
            # Fall back to substring match.
            matched = pattern in current_url

        return CheckResult(
            mode="url",
            passed=matched,
            expected=pattern,
            actual=current_url,
            detail="" if matched else (
                f"URL '{current_url}' does not match '{pattern}'"
            ),
        )

    async def _check_dom(
        self,
        page: PageLike,
        selector: str,
        expected_text: str | None,
    ) -> CheckResult:
        """Verify a DOM element exists and optionally contains text."""
        try:
            await page.wait_for_selector(
                selector, timeout=self._dom_wait_ms
            )
            el = await page.query_selector(selector)
        except Exception:
            el = None

        if el is None:
            return CheckResult(
                mode="dom",
                passed=False,
                expected=selector,
                actual="(not found)",
                detail=f"Selector '{selector}' not found on page",
            )

        if expected_text is not None:
            try:
                text = await page.evaluate(
                    f"document.querySelector('{selector}')?.textContent ?? ''"
                )
            except Exception:
                text = ""
            text_matched = expected_text.lower() in str(text).lower()
            return CheckResult(
                mode="dom",
                passed=text_matched,
                expected=f"{selector} containing '{expected_text}'",
                actual=str(text)[:200],
                detail="" if text_matched else (
                    f"Text '{expected_text}' not found in element"
                ),
            )

        return CheckResult(
            mode="dom",
            passed=True,
            expected=selector,
            actual="(found)",
        )

    @staticmethod
    async def _check_network(
        page: PageLike,
        url_pattern: str,
        expected_status: int | None,
    ) -> CheckResult:
        """Verify a network request was made (via page.evaluate).

        Uses the Performance API to inspect completed requests.
        """
        try:
            entries: list[dict[str, Any]] = await page.evaluate(
                f"""(() => {{
                    const entries = performance.getEntriesByType('resource');
                    return entries
                        .filter(e => e.name.includes('{url_pattern}'))
                        .map(e => ({{
                            url: e.name,
                            status: e.responseStatus || 0,
                            duration: e.duration,
                        }}));
                }})()"""
            )
        except Exception as exc:
            return CheckResult(
                mode="network",
                passed=False,
                expected=url_pattern,
                actual=f"(error: {exc})",
                detail=f"Network check failed: {exc}",
            )

        if not entries:
            return CheckResult(
                mode="network",
                passed=False,
                expected=url_pattern,
                actual="(no matching requests)",
                detail=(
                    f"No network request matching '{url_pattern}' found"
                ),
            )

        # Check status if specified.
        if expected_status is not None:
            matching = [
                e for e in entries
                if e.get("status") == expected_status
            ]
            if not matching:
                actual_statuses = [e.get("status", 0) for e in entries]
                return CheckResult(
                    mode="network",
                    passed=False,
                    expected=f"{url_pattern} (status {expected_status})",
                    actual=f"statuses: {actual_statuses}",
                    detail=(
                        f"Expected status {expected_status}, "
                        f"got {actual_statuses}"
                    ),
                )

        return CheckResult(
            mode="network",
            passed=True,
            expected=url_pattern,
            actual=f"{len(entries)} matching request(s)",
        )
