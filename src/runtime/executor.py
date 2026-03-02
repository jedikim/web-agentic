"""Bundle executor — run DSL workflow steps via Playwright.

Processes GeneratedBundle workflow steps sequentially, mapping each DSL
action to the corresponding Playwright call through a BrowserLike protocol.
"""

from __future__ import annotations

import contextlib
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

        text_match = step.get("text_match", "")
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
            page, selector, fallbacks, timeout_ms,
            text_match=text_match, action=action,
        )

        if action == "click":
            await page.click(resolved, timeout=timeout_ms)
        elif action == "fill":
            # Click to focus the input element before filling.
            with contextlib.suppress(Exception):
                await page.click(resolved, timeout=timeout_ms)
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
        *,
        text_match: str = "",
        action: str = "",
    ) -> str:
        """Try primary selector, then each fallback, then text_match.

        Args:
            page: Current page.
            primary: Primary CSS/XPath selector.
            fallbacks: Ordered fallback selectors.
            timeout_ms: Timeout per attempt.
            text_match: Visible text label for Playwright text selector fallback.
            action: DSL action type (fill uses input-specific resolution).

        Returns:
            The first selector that resolves to an element.

        Raises:
            RuntimeError: If no selector resolves.
        """
        candidates = [primary] + fallbacks if primary else fallbacks
        if not candidates and not text_match:
            raise RuntimeError("No selector provided for action")

        # When text_match is provided for click/hover, verify the CSS match
        # contains the expected text (prevents matching wrong elements from
        # generic selectors like [role="menuitem"].class).
        need_text_verify = bool(text_match) and action in ("click", "hover")

        for sel in candidates:
            try:
                el = await page.query_selector(sel)
                if el is not None:
                    if need_text_verify:
                        try:
                            el_text = (
                                await el.text_content() or ""
                            ).strip()
                            if text_match not in el_text:
                                logger.debug(
                                    "Selector %s matched '%s', expected '%s' — skipping",
                                    sel, el_text[:30], text_match,
                                )
                                continue
                        except Exception:
                            pass  # can't verify, accept the match
                    return sel
            except Exception:
                continue

        # text_match fallback — strategy depends on action type.
        if text_match:
            if action in ("fill", "press"):
                # For fill/press: find the actual <input> element, not a label.
                resolved = await self._resolve_input_by_text(
                    page, text_match, timeout_ms,
                )
                if resolved:
                    return resolved
            else:
                # For click/hover: use Playwright text selectors.
                text_candidates = [
                    f'text="{text_match}"',
                    f'a:has-text("{text_match}")',
                ]
                for sel in text_candidates:
                    try:
                        el = await page.query_selector(sel)
                        if el is not None:
                            logger.debug("text_match fallback hit: %s", sel)
                            return sel
                    except Exception:
                        continue
                # Wait for text element to appear.
                try:
                    await page.wait_for_selector(
                        f'text="{text_match}"', timeout=timeout_ms,
                    )
                    logger.debug("text_match wait_for_selector hit: %s", text_match)
                    return f'text="{text_match}"'
                except Exception:
                    pass

        # Last resort: wait for primary with full timeout.
        if primary:
            try:
                await page.wait_for_selector(
                    primary, timeout=timeout_ms,
                )
                return primary
            except Exception:
                pass

        tried_parts = list(candidates)
        if text_match:
            tried_parts.append(f'text="{text_match}"')
        tried = ", ".join(tried_parts)
        raise RuntimeError(
            f"Selector not found (tried: {tried})"
        )

    @staticmethod
    async def _resolve_input_by_text(
        page: PageLike,
        text_match: str,
        timeout_ms: int,
    ) -> str | None:
        """Find an <input>/<textarea> element associated with a text label.

        Tries multiple strategies to locate the input field that corresponds
        to the given text label, rather than the label/text element itself.

        Returns:
            Selector string if found, None otherwise.
        """
        # Strategy 1: input with matching placeholder
        input_candidates = [
            f'input[placeholder*="{text_match}"]',
            f'textarea[placeholder*="{text_match}"]',
            f'input[aria-label*="{text_match}"]',
            f'input[name*="{text_match}"]',
        ]
        for sel in input_candidates:
            try:
                el = await page.query_selector(sel)
                if el is not None:
                    logger.debug("input text_match hit (attr): %s", sel)
                    return sel
            except Exception:
                continue

        # Strategy 2: JS — find label/text near a VISIBLE input.
        # Collects all candidate matches, scores by proximity + visibility,
        # then returns the best one (not the first DOM-order match).
        try:
            js_result = await page.evaluate(
                """(textMatch) => {
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null);
                let node;
                const candidates = [];
                while ((node = walker.nextNode())) {
                    if (!node.textContent.includes(textMatch)) continue;
                    let container = node.parentElement;
                    for (let i = 0; i < 5 && container; i++) {
                        const input = container.querySelector(
                            'input:not([type="hidden"]):not([type="checkbox"])'
                            + ':not([type="radio"]):not([type="submit"])'
                            + ':not([type="button"]), textarea'
                        );
                        if (input && input.offsetWidth > 0 && input.offsetHeight > 0) {
                            let sel;
                            if (input.id) sel = '#' + input.id;
                            else if (input.name) sel = 'input[name=\"' + input.name + '\"]';
                            else {
                                const idx = [...container.querySelectorAll('input, textarea')]
                                    .indexOf(input);
                                const pSel = container.id ? '#' + container.id
                                    : container.className
                                        ? '.' + container.className.trim().split(/\\s+/)[0]
                                        : container.tagName.toLowerCase();
                                sel = pSel + ' input:nth-of-type(' + (idx + 1) + ')';
                            }
                            candidates.push({
                                sel,
                                level: i,
                                isNumber: input.type === 'number' ? 1 : 0,
                            });
                            break;
                        }
                        container = container.parentElement;
                    }
                }
                if (candidates.length === 0) return null;
                candidates.sort((a, b) => {
                    if (a.level !== b.level) return a.level - b.level;
                    return b.isNumber - a.isNumber;
                });
                return candidates[0].sel;
            }"""
            )
            if js_result:
                # Verify the JS-returned selector resolves
                el = await page.query_selector(js_result)
                if el is not None:
                    logger.debug("input text_match hit (JS): %s", js_result)
                    return js_result
        except Exception:
            pass

        # Strategy 3: wait for input with placeholder
        try:
            sel = f'input[placeholder*="{text_match}"]'
            await page.wait_for_selector(sel, timeout=timeout_ms)
            logger.debug("input text_match wait hit: %s", sel)
            return sel
        except Exception:
            pass

        return None

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
