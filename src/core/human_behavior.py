"""Human-like behavior simulation — natural mouse, typing, and scrolling.

Replaces instant Playwright actions with realistic timing patterns:

- **Bézier-curve mouse movement** before clicks.
- **Per-character typing** with variable delay.
- **Smooth incremental scrolling**.
- **Jittered waits** (base ± ratio).
- **Homepage warming** for deep URLs.

All delays are randomised within configured ranges to defeat timing analysis.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from src.core.config import BehaviorConfig

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


# ── Bézier Helpers ───────────────────────────────────


def _bezier_points(
    start: tuple[float, float],
    end: tuple[float, float],
    num_points: int = 20,
) -> list[tuple[float, float]]:
    """Generate points along a cubic Bézier curve with random control points.

    Args:
        start: Starting (x, y) coordinate.
        end: Ending (x, y) coordinate.
        num_points: Number of interpolation points.

    Returns:
        List of (x, y) points along the curve, always starting with
        *start* and ending with *end*.
    """
    sx, sy = start
    ex, ey = end

    # Two random control points in the bounding rectangle
    min_x, max_x = min(sx, ex), max(sx, ex)
    min_y, max_y = min(sy, ey), max(sy, ey)
    pad_x = max(abs(ex - sx) * 0.3, 30)
    pad_y = max(abs(ey - sy) * 0.3, 30)

    cp1 = (
        random.uniform(min_x - pad_x, max_x + pad_x),
        random.uniform(min_y - pad_y, max_y + pad_y),
    )
    cp2 = (
        random.uniform(min_x - pad_x, max_x + pad_x),
        random.uniform(min_y - pad_y, max_y + pad_y),
    )

    points: list[tuple[float, float]] = []
    for i in range(num_points + 1):
        t = i / num_points
        u = 1 - t
        x = (
            u ** 3 * sx
            + 3 * u ** 2 * t * cp1[0]
            + 3 * u * t ** 2 * cp2[0]
            + t ** 3 * ex
        )
        y = (
            u ** 3 * sy
            + 3 * u ** 2 * t * cp1[1]
            + 3 * u * t ** 2 * cp2[1]
            + t ** 3 * ey
        )
        points.append((x, y))

    return points


# ── HumanBehavior ────────────────────────────────────


class HumanBehavior:
    """Wraps a Playwright Page with human-like interaction methods.

    Args:
        page: The Playwright Page to act on.
        config: Behavior timing configuration.
    """

    def __init__(self, page: Page, config: BehaviorConfig) -> None:
        self._page = page
        self._config = config
        self._visited_domains: set[str] = set()

    # ── Mouse ─────────────────────────────────────

    async def natural_click(
        self,
        selector: str,
        *,
        timeout_ms: int = 5000,
    ) -> None:
        """Move mouse along a Bézier curve to the element, hover briefly, click.

        Args:
            selector: CSS selector of the target element.
            timeout_ms: Maximum time to wait for the element.
        """
        locator = self._page.locator(selector)
        bbox = await locator.bounding_box(timeout=timeout_ms)
        if bbox is None:
            # Fall back to plain click
            await self._page.click(selector, timeout=timeout_ms)
            return

        # Target: random point within the element
        target_x = bbox["x"] + random.uniform(0.3, 0.7) * bbox["width"]
        target_y = bbox["y"] + random.uniform(0.3, 0.7) * bbox["height"]

        if self._config.mouse_movement:
            # Get current mouse position (default 0,0 if not moved before)
            current = await self._page.evaluate(
                "() => ({ x: window._mouseX || 0, y: window._mouseY || 0 })"
            )
            start = (current["x"], current["y"])

            points = _bezier_points(start, (target_x, target_y))
            for px, py in points:
                await self._page.mouse.move(px, py)
                await asyncio.sleep(random.uniform(0.005, 0.015))

            # Track position for next move
            await self._page.evaluate(
                f"() => {{ window._mouseX = {target_x}; window._mouseY = {target_y}; }}"
            )

        # Hover delay
        delay_min, delay_max = self._config.click_delay_ms
        await asyncio.sleep(random.uniform(delay_min, delay_max) / 1000)

        await self._page.mouse.click(target_x, target_y)

    # ── Typing ────────────────────────────────────

    async def natural_type(self, selector: str, text: str) -> None:
        """Click the input, then type character-by-character with variable delays.

        Args:
            selector: CSS selector of the input element.
            text: The text to type.
        """
        # Focus the field first
        await self._page.click(selector)

        delay_min, delay_max = self._config.typing_delay_ms
        for ch in text:
            await self._page.keyboard.type(ch)
            await asyncio.sleep(random.uniform(delay_min, delay_max) / 1000)

    # ── Scrolling ─────────────────────────────────

    async def natural_scroll(
        self,
        direction: str = "down",
        amount: int = 300,
    ) -> None:
        """Scroll in small increments with micro-pauses.

        Args:
            direction: "up" or "down".
            amount: Total pixels to scroll.
        """
        step = self._config.scroll_step_px
        remaining = amount
        sign = 1 if direction == "down" else -1

        while remaining > 0:
            delta = min(step, remaining)
            await self._page.mouse.wheel(0, sign * delta)
            remaining -= delta
            await asyncio.sleep(random.uniform(0.03, 0.08))

    # ── Wait ──────────────────────────────────────

    async def jittered_wait(self, base_ms: int) -> None:
        """Wait for *base_ms* ± jitter.

        Args:
            base_ms: Base wait time in milliseconds.
        """
        jitter = self._config.step_delay_jitter
        low = base_ms * (1 - jitter)
        high = base_ms * (1 + jitter)
        ms = random.uniform(low, high)
        await asyncio.sleep(ms / 1000)

    # ── Navigation ────────────────────────────────

    async def warm_navigate(self, url: str) -> None:
        """Navigate to *url*, visiting the root domain first for deep URLs.

        Args:
            url: The target URL.
        """
        parsed = urlparse(url)
        domain = parsed.hostname or ""
        path_depth = len([p for p in parsed.path.strip("/").split("/") if p])

        if path_depth > 1 and domain not in self._visited_domains:
            root_url = f"{parsed.scheme}://{domain}/"
            logger.info("Warming navigation: visiting %s first", root_url)
            await self._page.goto(root_url)
            self._visited_domains.add(domain)
            await self.jittered_wait(1500)

        await self._page.goto(url)
        self._visited_domains.add(domain)
