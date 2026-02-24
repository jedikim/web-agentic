"""V(Verifier) — Post-action verification module.

Checks whether an action achieved its intended effect by inspecting
the page URL, DOM elements, text content, or network state.
All checks are pure DOM/URL-based with zero LLM token cost.

See docs/PRD.md section 3.5 and docs/ARCHITECTURE.md for design rationale.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from playwright.async_api import Page

from src.core.types import VerifyCondition, VerifyResult

logger = logging.getLogger(__name__)

# Default timeout in milliseconds when none is specified on the condition.
_DEFAULT_TIMEOUT_MS = 5000


class Verifier:
    """Post-action verification implementing the IVerifier protocol.

    Each verification type is dispatched to a dedicated handler.  All
    handlers are async and respect the per-condition ``timeout_ms``.

    Token cost: 0 (pure DOM/URL checking, no LLM).
    """

    # Registry mapping condition type strings to handler methods.
    _HANDLERS: dict[str, str] = {
        "url_changed": "_verify_url_changed",
        "url_contains": "_verify_url_contains",
        "element_visible": "_verify_element_visible",
        "element_gone": "_verify_element_gone",
        "text_present": "_verify_text_present",
        "network_idle": "_verify_network_idle",
    }

    async def verify(self, condition: VerifyCondition, page: Page) -> VerifyResult:
        """Verify a condition against the current page state.

        Args:
            condition: The verification condition describing what to check.
            page: The Playwright page instance to inspect.

        Returns:
            VerifyResult with success flag, human-readable message, and
            optional details dict.
        """
        handler_name = self._HANDLERS.get(condition.type)
        if handler_name is None:
            return VerifyResult(
                success=False,
                message=f"Unknown verification type: {condition.type}",
                details={"type": condition.type},
            )

        handler = getattr(self, handler_name)
        timeout_ms = condition.timeout_ms or _DEFAULT_TIMEOUT_MS

        try:
            return await handler(condition, page, timeout_ms)
        except asyncio.TimeoutError:
            return VerifyResult(
                success=False,
                message=f"Verification timed out after {timeout_ms}ms: {condition.type}",
                details={"type": condition.type, "timeout_ms": timeout_ms},
            )
        except Exception as exc:
            logger.exception("Verification error for %s", condition.type)
            return VerifyResult(
                success=False,
                message=f"Verification error: {exc}",
                details={"type": condition.type, "error": str(exc)},
            )

    # ── url_changed ──────────────────────────────────────

    async def _verify_url_changed(
        self,
        condition: VerifyCondition,
        page: Page,
        timeout_ms: int,
    ) -> VerifyResult:
        """Verify that the URL changed from the value stored in ``condition.value``.

        ``condition.value`` must contain the *previous* URL.  The method
        polls until the current URL differs or the timeout expires.
        """
        previous_url = condition.value
        if not previous_url:
            return VerifyResult(
                success=False,
                message="url_changed requires 'value' to contain the previous URL",
                details={"type": "url_changed"},
            )

        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while True:
            current_url = page.url
            if current_url != previous_url:
                return VerifyResult(
                    success=True,
                    message=f"URL changed from {previous_url} to {current_url}",
                    details={"previous_url": previous_url, "current_url": current_url},
                )
            if asyncio.get_event_loop().time() >= deadline:
                return VerifyResult(
                    success=False,
                    message=f"URL did not change from {previous_url} within {timeout_ms}ms",
                    details={"previous_url": previous_url, "current_url": current_url},
                )
            await asyncio.sleep(0.05)

    # ── url_contains ─────────────────────────────────────

    async def _verify_url_contains(
        self,
        condition: VerifyCondition,
        page: Page,
        timeout_ms: int,
    ) -> VerifyResult:
        """Verify that the current URL contains the expected substring."""
        expected = condition.value
        if not expected:
            return VerifyResult(
                success=False,
                message="url_contains requires 'value' with the expected substring",
                details={"type": "url_contains"},
            )

        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while True:
            current_url = page.url
            if expected in current_url:
                return VerifyResult(
                    success=True,
                    message=f"URL contains '{expected}'",
                    details={"url": current_url, "expected": expected},
                )
            if asyncio.get_event_loop().time() >= deadline:
                return VerifyResult(
                    success=False,
                    message=f"URL does not contain '{expected}' within {timeout_ms}ms",
                    details={"url": current_url, "expected": expected},
                )
            await asyncio.sleep(0.05)

    # ── element_visible ──────────────────────────────────

    async def _verify_element_visible(
        self,
        condition: VerifyCondition,
        page: Page,
        timeout_ms: int,
    ) -> VerifyResult:
        """Verify that the element matching ``condition.value`` selector is visible."""
        selector = condition.value
        if not selector:
            return VerifyResult(
                success=False,
                message="element_visible requires 'value' with a CSS selector",
                details={"type": "element_visible"},
            )

        try:
            locator = page.locator(selector)
            await locator.wait_for(state="visible", timeout=timeout_ms)
            return VerifyResult(
                success=True,
                message=f"Element '{selector}' is visible",
                details={"selector": selector},
            )
        except Exception:
            return VerifyResult(
                success=False,
                message=f"Element '{selector}' not visible within {timeout_ms}ms",
                details={"selector": selector, "timeout_ms": timeout_ms},
            )

    # ── element_gone ─────────────────────────────────────

    async def _verify_element_gone(
        self,
        condition: VerifyCondition,
        page: Page,
        timeout_ms: int,
    ) -> VerifyResult:
        """Verify that the element matching ``condition.value`` is no longer visible."""
        selector = condition.value
        if not selector:
            return VerifyResult(
                success=False,
                message="element_gone requires 'value' with a CSS selector",
                details={"type": "element_gone"},
            )

        try:
            locator = page.locator(selector)
            await locator.wait_for(state="hidden", timeout=timeout_ms)
            return VerifyResult(
                success=True,
                message=f"Element '{selector}' is gone",
                details={"selector": selector},
            )
        except Exception:
            return VerifyResult(
                success=False,
                message=f"Element '{selector}' still visible after {timeout_ms}ms",
                details={"selector": selector, "timeout_ms": timeout_ms},
            )

    # ── text_present ─────────────────────────────────────

    async def _verify_text_present(
        self,
        condition: VerifyCondition,
        page: Page,
        timeout_ms: int,
    ) -> VerifyResult:
        """Verify that expected text appears somewhere on the page."""
        expected_text = condition.value
        if not expected_text:
            return VerifyResult(
                success=False,
                message="text_present requires 'value' with expected text",
                details={"type": "text_present"},
            )

        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while True:
            try:
                body_text = await page.inner_text("body")
            except Exception:
                body_text = ""

            if expected_text in body_text:
                return VerifyResult(
                    success=True,
                    message=f"Text '{expected_text}' found on page",
                    details={"expected_text": expected_text},
                )
            if asyncio.get_event_loop().time() >= deadline:
                return VerifyResult(
                    success=False,
                    message=f"Text '{expected_text}' not found within {timeout_ms}ms",
                    details={"expected_text": expected_text, "timeout_ms": timeout_ms},
                )
            await asyncio.sleep(0.05)

    # ── network_idle ─────────────────────────────────────

    async def _verify_network_idle(
        self,
        condition: VerifyCondition,
        page: Page,
        timeout_ms: int,
    ) -> VerifyResult:
        """Verify that the network is idle (load state is 'networkidle').

        Uses Playwright's ``wait_for_load_state('networkidle')`` with
        the configured timeout.
        """
        try:
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
            return VerifyResult(
                success=True,
                message="Network is idle",
                details={"type": "network_idle"},
            )
        except Exception:
            return VerifyResult(
                success=False,
                message=f"Network not idle within {timeout_ms}ms",
                details={"type": "network_idle", "timeout_ms": timeout_ms},
            )
