"""CanvasDetector — detect Canvas-based pages with minimal DOM.

Canvas pages (games, lottery, some SPAs) have no meaningful DOM.
The standard DOM Extractor → TextMatcher → CSS selector pipeline
does not work. This detector identifies such pages so the orchestrator
can switch to the vision-only path (CanvasExecutor).

Detection criteria:
1. <canvas> tag exists → Canvas page
2. Clickable DOM elements <= CANVAS_THRESHOLD → likely Canvas
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class ICanvasBrowser(Protocol):
    """Browser interface for canvas detection."""

    async def evaluate(self, expression: str) -> object: ...


class CanvasDetector:
    """Detect Canvas pages where DOM-based automation won't work.

    Usage:
        detector = CanvasDetector()
        if await detector.is_canvas_page(browser):
            # Switch to vision-only path
            ...
    """

    CANVAS_THRESHOLD = 5

    async def is_canvas_page(self, browser: ICanvasBrowser) -> bool:
        """Determine if the current page is Canvas-based.

        Checks:
        1. Presence of <canvas> elements
        2. Very few clickable DOM elements (buttons, links, inputs)

        Args:
            browser: Browser instance with evaluate() support.

        Returns:
            True if the page appears to be Canvas-based.
        """
        has_canvas = await browser.evaluate(
            "document.querySelectorAll('canvas').length > 0"
        )
        if has_canvas:
            logger.debug("Canvas page detected: <canvas> tag found")
            return True

        clickable_count = await browser.evaluate(
            "document.querySelectorAll("
            "'a, button, input, select, textarea, "
            "[role=button], [onclick]'"
            ").length"
        )

        if isinstance(clickable_count, (int, float)):
            is_canvas = int(clickable_count) <= self.CANVAS_THRESHOLD
            if is_canvas:
                logger.debug(
                    "Canvas page detected: only %d clickable elements",
                    int(clickable_count),
                )
            return is_canvas

        return False
