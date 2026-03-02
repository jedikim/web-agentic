"""Bundle executor — run DSL workflow steps via Playwright.

Processes GeneratedBundle workflow steps sequentially, mapping each DSL
action to the corresponding Playwright call through a BrowserLike protocol.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.models.bundle import GeneratedBundle
from src.models.failure import FailureEvidence, FailureType

logger = logging.getLogger(__name__)

# ── Supported DSL actions ──

_VALID_ACTIONS = frozenset({
    "goto", "click", "fill", "scroll", "wait", "screenshot",
    "hover", "select", "press", "evaluate",
})

_DEFAULT_TIMEOUT_MS = 10_000
_DEFAULT_WAIT_MS = 2_000


# ── Browser Protocol ──


class PageLike(Protocol):
    """Minimal Playwright page interface for DSL execution."""

    async def goto(self, url: str, **kwargs: Any) -> Any: ...
    async def click(self, selector: str, **kwargs: Any) -> None: ...
    async def fill(self, selector: str, value: str, **kwargs: Any) -> None: ...
    async def hover(self, selector: str, **kwargs: Any) -> None: ...
    async def press(self, selector: str, key: str, **kwargs: Any) -> None: ...
    async def select_option(
        self, selector: str, value: str, **kwargs: Any
    ) -> Any: ...
    async def screenshot(self, **kwargs: Any) -> bytes: ...
    async def evaluate(self, expression: str) -> Any: ...
    async def wait_for_timeout(self, timeout: float) -> None: ...
    async def wait_for_selector(
        self, selector: str, **kwargs: Any
    ) -> Any: ...
    async def query_selector(self, selector: str) -> Any: ...

    @property
    def url(self) -> str: ...


class BrowserLike(Protocol):
    """Minimal browser interface — provides a page."""

    async def get_page(self) -> PageLike: ...


# ── Result dataclass ──


@dataclass
class ExecutionResult:
    """Outcome of a bundle execution run."""

    success: bool = False
    steps_completed: int = 0
    total_steps: int = 0
    duration_ms: float = 0.0
    error: str | None = None
    failure_evidence: FailureEvidence | None = None
    screenshots: list[bytes] = field(default_factory=list)


# ── Executor ──


class BundleExecutor:
    """Execute a GeneratedBundle's DSL workflow steps sequentially.

    Each step dict has the shape::

        {"action": "goto|click|fill|...", "selector": "...", "value": "...",
         "fallback_selectors": [...], "timeout_ms": 10000}
    """

    def __init__(
        self,
        *,
        default_timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> None:
        self._default_timeout_ms = default_timeout_ms

    async def execute(
        self,
        bundle: GeneratedBundle,
        browser: BrowserLike,
        task: str,
    ) -> ExecutionResult:
        """Run all DSL steps from the bundle.

        Args:
            bundle: The generated execution bundle containing workflow_dsl.
            browser: Browser wrapper providing page access.
            task: Human-readable task description (for logging).

        Returns:
            ExecutionResult with metrics and optional failure evidence.
        """
        dsl = bundle.workflow_dsl
        steps: list[dict[str, Any]] = dsl.get("steps", [])
        total = len(steps)

        result = ExecutionResult(total_steps=total)
        if total == 0:
            result.success = True
            return result

        page = await browser.get_page()
        t0 = time.monotonic()

        for idx, step in enumerate(steps):
            action = step.get("action", "")
            if action not in _VALID_ACTIONS:
                logger.warning(
                    "Step %d: unknown action '%s', skipping", idx, action
                )
                continue

            try:
                screenshot = await self._run_step(page, step, idx)
                if screenshot is not None:
                    result.screenshots.append(screenshot)
                result.steps_completed = idx + 1
            except Exception as exc:
                elapsed = (time.monotonic() - t0) * 1000
                result.duration_ms = elapsed
                result.error = f"Step {idx} ({action}): {exc}"
                result.failure_evidence = self._build_evidence(
                    step, str(exc), page.url
                )
                logger.error(
                    "Task '%s' failed at step %d/%d: %s",
                    task, idx, total, exc,
                )
                return result

        result.duration_ms = (time.monotonic() - t0) * 1000
        result.success = True
        logger.info(
            "Task '%s' completed: %d/%d steps in %.0fms",
            task, result.steps_completed, total, result.duration_ms,
        )
        return result

    async def _run_step(
        self,
        page: PageLike,
        step: dict[str, Any],
        idx: int,
    ) -> bytes | None:
        """Execute a single DSL step.

        Returns:
            Screenshot bytes if the action is 'screenshot', else None.
        """
        action = step["action"]
        selector = step.get("selector", "")
        value = step.get("value", "")
        timeout_ms = step.get("timeout_ms", self._default_timeout_ms)
        fallbacks: list[str] = step.get("fallback_selectors", [])

        logger.debug("Step %d: %s selector=%s", idx, action, selector)

        if action == "goto":
            url = value or selector
            await page.goto(url, wait_until="domcontentloaded")
            return None

        if action == "screenshot":
            return await page.screenshot()

        if action == "wait":
            wait_ms = float(value) if value else _DEFAULT_WAIT_MS
            await page.wait_for_timeout(wait_ms)
            return None

        if action == "scroll":
            direction = value or "down"
            pixels = step.get("pixels", 500)
            delta = pixels if direction == "down" else -pixels
            await page.evaluate(f"window.scrollBy(0, {delta})")
            return None

        if action == "evaluate":
            expression = value or selector
            await page.evaluate(expression)
            return None

        # Actions requiring a selector — try primary, then fallbacks.
        resolved = await self._resolve_selector(
            page, selector, fallbacks, timeout_ms
        )

        if action == "click":
            await page.click(resolved, timeout=timeout_ms)
        elif action == "fill":
            await page.fill(resolved, value, timeout=timeout_ms)
        elif action == "hover":
            await page.hover(resolved, timeout=timeout_ms)
        elif action == "select":
            await page.select_option(resolved, value, timeout=timeout_ms)
        elif action == "press":
            key = value or "Enter"
            await page.press(resolved, key, timeout=timeout_ms)

        return None

    async def _resolve_selector(
        self,
        page: PageLike,
        primary: str,
        fallbacks: list[str],
        timeout_ms: int,
    ) -> str:
        """Try primary selector, then each fallback.

        Args:
            page: Current page.
            primary: Primary CSS/XPath selector.
            fallbacks: Ordered fallback selectors.
            timeout_ms: Timeout per attempt.

        Returns:
            The first selector that resolves to an element.

        Raises:
            RuntimeError: If no selector resolves.
        """
        candidates = [primary] + fallbacks if primary else fallbacks
        if not candidates:
            raise RuntimeError("No selector provided for action")

        for sel in candidates:
            try:
                el = await page.query_selector(sel)
                if el is not None:
                    return sel
            except Exception:
                continue

        # Last resort: wait for primary with full timeout.
        if primary:
            try:
                await page.wait_for_selector(
                    primary, timeout=timeout_ms
                )
                return primary
            except Exception:
                pass

        tried = ", ".join(candidates)
        raise RuntimeError(
            f"Selector not found (tried: {tried})"
        )

    @staticmethod
    def _build_evidence(
        step: dict[str, Any],
        error_msg: str,
        url: str,
    ) -> FailureEvidence:
        """Build failure evidence from a failed step."""
        action = step.get("action", "")
        selector = step.get("selector")

        if "not found" in error_msg.lower():
            ftype = FailureType.SELECTOR_NOT_FOUND
        elif "timeout" in error_msg.lower():
            ftype = FailureType.TIMEOUT
        elif "navigation" in error_msg.lower():
            ftype = FailureType.NAVIGATION_FAILED
        else:
            ftype = FailureType.UNKNOWN

        evidence = FailureEvidence(
            failure_type=ftype,
            error_message=error_msg,
            selector=selector,
            url=url,
            extra={"action": action, "step": step},
        )
        evidence.classify_remediation()
        return evidence
