"""X(Executor) — Playwright async wrapper for browser automation.

Implements the IExecutor Protocol defined in types.py.
All browser operations use async/await with explicit timeout handling.
Playwright errors are mapped to domain-specific exceptions.

See docs/PRD.md section 3.1 and docs/ARCHITECTURE.md for design rationale.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)
from playwright.async_api import (
    async_playwright,
)

from src.core.types import (
    ClickOptions,
    NetworkError,
    NotInteractableError,
    SelectorNotFoundError,
    WaitCondition,
)

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

    from src.core.config import StealthConfig

logger = logging.getLogger(__name__)

# Default timeouts in milliseconds
_DEFAULT_NAVIGATION_TIMEOUT_MS = 30_000
_DEFAULT_ACTION_TIMEOUT_MS = 5_000
_DEFAULT_WAIT_TIMEOUT_MS = 10_000


def _map_playwright_error(err: PlaywrightError, selector: str | None = None) -> Exception:
    """Map a Playwright error to the appropriate domain exception.

    Args:
        err: The original Playwright error.
        selector: The CSS selector involved, if any.

    Returns:
        A domain-specific AutomationError subclass.
    """
    msg = str(err).lower()

    if isinstance(err, PlaywrightTimeoutError):
        if selector:
            return SelectorNotFoundError(
                f"Timed out waiting for selector: {selector}"
            )
        return NetworkError(f"Operation timed out: {err}")

    if "waiting for selector" in msg or "no element matches" in msg:
        return SelectorNotFoundError(
            f"Element not found: {selector or '(unknown)'}"
        )

    if "element is not visible" in msg or "element is not enabled" in msg:
        return NotInteractableError(
            f"Element not interactable: {selector or '(unknown)'}"
        )

    if "intercept" in msg or "detached" in msg or "not attached" in msg:
        return NotInteractableError(
            f"Element detached or intercepted: {selector or '(unknown)'}"
        )

    if (
        "net::" in msg
        or "err_connection" in msg
        or "err_name_not_resolved" in msg
        or "navigation failed" in msg
    ):
        return NetworkError(f"Network error: {err}")

    # Fallback: wrap in the most general browser error
    return SelectorNotFoundError(f"Playwright error: {err}")


class Executor:
    """Playwright async wrapper implementing IExecutor Protocol.

    Wraps a Playwright Page object and translates all browser interactions
    into typed async methods with timeout handling and exception mapping.

    Attributes:
        _page: The underlying Playwright Page.
        _browser: The Playwright Browser instance (owned if created via factory).
        _context: The Playwright BrowserContext (owned if created via factory).
        _default_timeout_ms: Default timeout for actions in milliseconds.
    """

    def __init__(
        self,
        page: Page,
        browser: Browser | None = None,
        context: BrowserContext | None = None,
        default_timeout_ms: int = _DEFAULT_ACTION_TIMEOUT_MS,
        behavior: Any | None = None,
        nav_guard: Any | None = None,
    ) -> None:
        """Initialize the Executor.

        Args:
            page: An active Playwright Page object.
            browser: Optional Browser instance for lifecycle management.
            context: Optional BrowserContext for lifecycle management.
            default_timeout_ms: Default timeout for actions in milliseconds.
            behavior: Optional HumanBehavior for natural interactions.
            nav_guard: Optional NavigationGuard for smart navigation.
        """
        self._page = page
        self._browser = browser
        self._context = context
        self._default_timeout_ms = default_timeout_ms
        self._behavior = behavior
        self._nav_guard = nav_guard

    async def goto(self, url: str) -> None:
        """Navigate to a URL.

        If a ``NavigationGuard`` is attached, it is consulted first
        (rate-limiting, robots.txt, homepage warming).

        Args:
            url: The URL to navigate to.

        Raises:
            NetworkError: If navigation fails or times out.
        """
        try:
            if self._nav_guard is not None:
                await self._nav_guard.pre_navigate(url, self._page)
            logger.debug("Navigating to %s", url)
            await self._page.goto(url, timeout=_DEFAULT_NAVIGATION_TIMEOUT_MS)
        except PlaywrightError as err:
            raise _map_playwright_error(err) from err

    async def click(self, selector: str, options: ClickOptions | None = None) -> None:
        """Click an element identified by a CSS selector.

        Args:
            selector: CSS selector for the target element.
            options: Optional click configuration (button, count, force, timeout).

        Raises:
            SelectorNotFoundError: If the element is not found within timeout.
            NotInteractableError: If the element exists but cannot be clicked.
        """
        opts = options or ClickOptions()
        try:
            if self._behavior is not None and not opts.force:
                logger.debug("Natural clicking %s", selector)
                await self._behavior.natural_click(
                    selector, timeout_ms=opts.timeout_ms,
                )
            else:
                logger.debug("Clicking %s with options %s", selector, opts)
                await self._page.click(
                    selector,
                    button=opts.button,  # type: ignore[arg-type]
                    click_count=opts.click_count,
                    force=opts.force,
                    timeout=opts.timeout_ms,
                )
        except PlaywrightError as err:
            raise _map_playwright_error(err, selector) from err

    async def type_text(self, selector: str, text: str) -> None:
        """Type text into an input element.

        Focuses the element, clears existing content, then types the text.

        Args:
            selector: CSS selector for the input element.
            text: The text to type.

        Raises:
            SelectorNotFoundError: If the element is not found within timeout.
            NotInteractableError: If the element exists but is not editable.
        """
        try:
            if self._behavior is not None:
                logger.debug("Natural typing into %s: %r", selector, text[:50])
                await self._behavior.natural_type(selector, text)
            else:
                logger.debug("Typing into %s: %r", selector, text[:50])
                await self._page.fill(
                    selector, text, timeout=self._default_timeout_ms
                )
        except PlaywrightError as err:
            raise _map_playwright_error(err, selector) from err

    async def hover(self, selector: str, timeout_ms: int = 5000) -> None:
        """Hover over an element identified by a CSS selector.

        Args:
            selector: CSS selector for the target element.
            timeout_ms: Maximum time to wait for the element.

        Raises:
            SelectorNotFoundError: If the element is not found within timeout.
        """
        try:
            logger.debug("Hovering %s", selector)
            await self._page.hover(selector, timeout=timeout_ms)
        except PlaywrightError as err:
            raise _map_playwright_error(err, selector) from err

    async def press_key(self, key: str) -> None:
        """Press a keyboard key.

        Args:
            key: Key name (e.g. "Enter", "Tab", "ArrowDown", "Control+a").

        Raises:
            NetworkError: If the key press triggers a failed navigation.
        """
        try:
            logger.debug("Pressing key: %s", key)
            await self._page.keyboard.press(key)
        except PlaywrightError as err:
            raise _map_playwright_error(err) from err

    async def scroll(self, direction: str = "down", amount: int = 300) -> None:
        """Scroll the page.

        Args:
            direction: Scroll direction — "up" or "down".
            amount: Scroll distance in pixels (positive value).

        Raises:
            NetworkError: If a scroll-triggered navigation fails.
        """
        try:
            if self._behavior is not None and self._behavior._config.scroll_smooth:
                logger.debug("Natural scrolling %s by %d pixels", direction, amount)
                await self._behavior.natural_scroll(direction, amount)
            else:
                delta_y = amount if direction == "down" else -amount
                logger.debug("Scrolling %s by %d pixels", direction, amount)
                await self._page.mouse.wheel(0, delta_y)
        except PlaywrightError as err:
            raise _map_playwright_error(err) from err

    async def screenshot(
        self, region: tuple[int, int, int, int] | None = None
    ) -> bytes:
        """Take a screenshot of the page or a specific region.

        Args:
            region: Optional (x, y, width, height) tuple for a partial screenshot.
                If None, captures the full viewport.

        Returns:
            PNG image data as bytes.

        Raises:
            NetworkError: If the screenshot operation fails.
        """
        try:
            if region is not None:
                x, y, width, height = region
                logger.debug("Taking region screenshot: %s", region)
                data: bytes = await self._page.screenshot(
                    clip={"x": x, "y": y, "width": width, "height": height},
                    type="png",
                )
            else:
                logger.debug("Taking full-page screenshot")
                data = await self._page.screenshot(type="png")
            return data
        except PlaywrightError as err:
            raise _map_playwright_error(err) from err

    async def wait_for(self, condition: WaitCondition) -> None:
        """Wait for a condition to be satisfied.

        Supported condition types:
            - "selector": Wait for a CSS selector to appear.
            - "url": Wait for URL to match the given pattern.
            - "text": Wait for specific text to appear on the page.
            - "network_idle": Wait for no network activity.
            - "timeout": Wait for a fixed duration.

        Args:
            condition: The WaitCondition describing what to wait for.

        Raises:
            SelectorNotFoundError: If a selector condition times out.
            NetworkError: If a network-related wait fails.
        """
        timeout = condition.timeout_ms
        try:
            match condition.type:
                case "selector":
                    logger.debug("Waiting for selector: %s", condition.value)
                    await self._page.wait_for_selector(
                        condition.value, timeout=timeout
                    )
                case "url":
                    logger.debug("Waiting for URL: %s", condition.value)
                    await self._page.wait_for_url(
                        condition.value, timeout=timeout
                    )
                case "text":
                    logger.debug("Waiting for text: %s", condition.value)
                    await self._page.wait_for_selector(
                        f"text={condition.value}", timeout=timeout
                    )
                case "network_idle":
                    logger.debug("Waiting for network idle")
                    await self._page.wait_for_load_state(
                        "networkidle", timeout=timeout
                    )
                case "timeout":
                    ms = int(condition.value) if condition.value else timeout
                    logger.debug("Waiting for %d ms", ms)
                    await self._page.wait_for_timeout(ms)
                case _:
                    raise ValueError(
                        f"Unknown wait condition type: {condition.type}"
                    )
        except PlaywrightError as err:
            raise _map_playwright_error(err, condition.value) from err

    async def get_page(self) -> Page:
        """Return the underlying Playwright Page object.

        Returns:
            The active Playwright Page instance.
        """
        return self._page

    async def get_page_state(self) -> dict[str, Any]:
        """Return a snapshot of the current page state.

        Returns:
            Dictionary with url, title, and viewport information.
        """
        return {
            "url": self._page.url,
            "title": await self._page.title(),
        }

    async def evaluate(self, expression: str) -> object:
        """Evaluate a JavaScript expression on the page.

        Args:
            expression: JavaScript expression to evaluate.

        Returns:
            The result of the expression evaluation.

        Raises:
            NetworkError: If the evaluation fails.
        """
        try:
            return await self._page.evaluate(expression)
        except PlaywrightError as err:
            raise _map_playwright_error(err) from err

    async def wait_for_selector(self, selector: str, timeout: int = 5000) -> None:
        """Wait for a CSS selector to appear on the page.

        Args:
            selector: CSS selector to wait for.
            timeout: Maximum wait time in milliseconds.

        Raises:
            SelectorNotFoundError: If the selector is not found within timeout.
        """
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
        except PlaywrightError as err:
            raise _map_playwright_error(err, selector) from err

    async def close(self) -> None:
        """Close the browser and release resources.

        Safe to call multiple times. Closes context and browser if owned.
        """
        try:
            if self._context is not None:
                await self._context.close()
                self._context = None
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
        except PlaywrightError:
            logger.warning("Error during executor close", exc_info=True)


async def create_executor(
    headless: bool = True,
    stealth: StealthConfig | None = None,
) -> Executor:
    """Factory function to create a fully-initialized Executor.

    Launches a Chromium browser, creates a context and page, then wraps
    them in an Executor instance.  When *stealth* is provided the context
    is created via :func:`create_stealth_context` which injects anti-
    detection JS patches.

    Args:
        headless: Whether to run the browser in headless mode.
        stealth: Optional stealth configuration for anti-detection.

    Returns:
        A ready-to-use Executor instance.

    Example:
        >>> executor = await create_executor(headless=True)
        >>> await executor.goto("https://example.com")
        >>> await executor.close()
    """
    from src.core.stealth import create_stealth_context

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=headless)

    if stealth is not None and stealth.enabled:
        context = await create_stealth_context(browser, stealth)
    else:
        context = await browser.new_context()

    page = await context.new_page()
    return Executor(page=page, browser=browser, context=context)
