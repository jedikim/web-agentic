"""Browser wrapper — Playwright (execution) + CDP (extraction) hybrid.

Provides a unified interface for both high-level browser automation (Playwright)
and low-level DOM/accessibility extraction (Chrome DevTools Protocol).

Usage:
    page = await browser_context.new_page()
    browser = Browser(page)
    screenshot = await browser.screenshot()
    nodes = await extractor.extract(browser)  # Uses CDP internally
"""

from __future__ import annotations

import asyncio
from typing import Any

from playwright.async_api import CDPSession, Page


class Browser:
    """Hybrid browser wrapper: Playwright for execution, CDP for extraction.

    Attributes:
        _page: Playwright Page instance.
        _cdp: Lazy-initialized CDP session.
    """

    def __init__(self, page: Page) -> None:
        self._page = page
        self._cdp: CDPSession | None = None

    async def get_cdp(self) -> CDPSession:
        """Get or create a CDP session for this page."""
        if self._cdp is None:
            self._cdp = await self._page.context.new_cdp_session(self._page)
        return self._cdp

    # ── Execution methods (Playwright) ────────────────────

    async def click_selector(self, selector: str, timeout: int = 5000) -> None:
        """Click an element by CSS selector."""
        await self._page.click(selector, timeout=timeout)

    async def fill_selector(self, selector: str, value: str, timeout: int = 5000) -> None:
        """Fill a text field by CSS selector."""
        await self._page.fill(selector, value, timeout=timeout)

    async def mouse_click(self, x: float, y: float) -> None:
        """Click at viewport coordinates."""
        await self._page.mouse.click(x, y)

    async def key_press(self, key: str) -> None:
        """Press a keyboard key."""
        await self._page.keyboard.press(key)

    async def type_text(self, text: str, delay: float = 0) -> None:
        """Type text character by character."""
        await self._page.keyboard.type(text, delay=delay)

    async def scroll(self, direction: str = "down", amount: int = 300) -> None:
        """Scroll the page in a direction."""
        delta_x = 0
        delta_y = 0
        if direction == "down":
            delta_y = amount
        elif direction == "up":
            delta_y = -amount
        elif direction == "right":
            delta_x = amount
        elif direction == "left":
            delta_x = -amount
        await self._page.mouse.wheel(delta_x, delta_y)

    async def wait(self, ms: int) -> None:
        """Wait for a specified number of milliseconds."""
        await asyncio.sleep(ms / 1000.0)

    async def goto(self, url: str) -> None:
        """Navigate to a URL."""
        await self._page.goto(url)

    async def wait_for_selector(self, selector: str, timeout: int = 5000) -> None:
        """Wait for a selector to appear."""
        await self._page.wait_for_selector(selector, timeout=timeout)

    # ── Extraction methods (CDP + Playwright) ─────────────

    async def screenshot(self) -> bytes:
        """Take a full-page screenshot as PNG bytes."""
        return await self._page.screenshot(type="png")

    async def screenshot_clip(
        self, clip: dict[str, float],
    ) -> bytes:
        """Take a clipped screenshot of a specific region."""
        return await self._page.screenshot(
            type="png",
            clip={
                "x": clip["x"],
                "y": clip["y"],
                "width": clip["width"],
                "height": clip["height"],
            },
        )

    async def evaluate(self, expression: str) -> Any:
        """Evaluate a JavaScript expression on the page."""
        return await self._page.evaluate(expression)

    async def get_viewport_size(self) -> dict[str, int]:
        """Get the current viewport size."""
        size = self._page.viewport_size
        if size is None:
            return {"width": 1280, "height": 720}
        return {"width": size["width"], "height": size["height"]}

    @property
    def url(self) -> str:
        """Get the current page URL."""
        return self._page.url

    @property
    def page(self) -> Page:
        """Access the underlying Playwright Page (for advanced use)."""
        return self._page

    async def close(self) -> None:
        """Close the CDP session and page."""
        if self._cdp is not None:
            await self._cdp.detach()
            self._cdp = None
        await self._page.close()
