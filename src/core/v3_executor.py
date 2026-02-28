"""v3 Executor — selector-first with viewport coordinate fallback.

Executes actions on the browser. Does NOT verify results or retry —
that's the Orchestrator's responsibility.

Strategy:
- selector available → try click/fill via CSS selector → fail → viewport fallback
- selector None → use viewport_xy directly (coordinate-based click)
"""

from __future__ import annotations

from src.core.browser import Browser
from src.core.types import Action


class V3Executor:
    """Execute browser actions. Selector first, viewport_xy fallback.

    Usage:
        executor = V3Executor()
        await executor.execute_action(action, browser)
    """

    async def execute_action(self, action: Action, browser: Browser) -> None:
        """Execute an action on the browser.

        Args:
            action: Action to execute (click, type, scroll, hover, etc).
            browser: Browser instance.

        Raises:
            RuntimeError: If no selector and no viewport coordinates.
        """
        action_type = action.action_type.lower()

        if action_type == "click":
            await self._do_click(action, browser)
        elif action_type in ("type", "fill"):
            await self._do_type(action, browser)
        elif action_type == "scroll":
            await self._do_scroll(action, browser)
        elif action_type == "hover":
            await self._do_hover(action, browser)
        elif action_type == "press":
            await self._do_press(action, browser)
        elif action_type == "goto":
            await self._do_goto(action, browser)
        elif action_type == "wait":
            await self._do_wait(action, browser)
        else:
            # Default to click for unknown action types
            await self._do_click(action, browser)

    async def _do_click(self, action: Action, browser: Browser) -> None:
        """Click — selector first, viewport fallback."""
        if action.selector:
            try:
                await browser.click_selector(action.selector, timeout=3000)
                return
            except Exception:
                pass  # Selector failed → try viewport fallback

        if action.viewport_xy:
            size = await browser.get_viewport_size()
            x = int(action.viewport_xy[0] * size["width"])
            y = int(action.viewport_xy[1] * size["height"])
            await browser.mouse_click(x, y)
            return

        raise RuntimeError(
            f"Click failed: no selector ({action.selector}) "
            f"and no viewport coordinates ({action.viewport_xy})"
        )

    async def _do_type(self, action: Action, browser: Browser) -> None:
        """Type text — selector fill first, viewport click+type fallback."""
        value = action.value or ""

        if action.selector:
            try:
                await browser.fill_selector(action.selector, value, timeout=3000)
                return
            except Exception:
                pass

        if action.viewport_xy:
            size = await browser.get_viewport_size()
            x = int(action.viewport_xy[0] * size["width"])
            y = int(action.viewport_xy[1] * size["height"])
            await browser.mouse_click(x, y)
            await browser.type_text(value)
            return

        raise RuntimeError(
            f"Type failed: no selector ({action.selector}) "
            f"and no viewport coordinates ({action.viewport_xy})"
        )

    async def _do_scroll(self, action: Action, browser: Browser) -> None:
        """Scroll the page."""
        value = action.value or "down"
        parts = value.split()
        direction = parts[0] if parts else "down"
        try:
            amount = int(parts[1]) if len(parts) > 1 else 300
        except (ValueError, IndexError):
            amount = 300
        await browser.scroll(direction, amount)

    async def _do_hover(self, action: Action, browser: Browser) -> None:
        """Hover over an element."""
        if action.selector:
            try:
                await browser.page.hover(action.selector, timeout=3000)
                return
            except Exception:
                pass

        if action.viewport_xy:
            size = await browser.get_viewport_size()
            x = int(action.viewport_xy[0] * size["width"])
            y = int(action.viewport_xy[1] * size["height"])
            await browser.page.mouse.move(x, y)
            return

    async def _do_press(self, action: Action, browser: Browser) -> None:
        """Press a keyboard key."""
        key = action.value or "Enter"
        await browser.key_press(key)

    async def _do_goto(self, action: Action, browser: Browser) -> None:
        """Navigate to a URL."""
        url = action.value or ""
        if url:
            await browser.goto(url)

    async def _do_wait(self, action: Action, browser: Browser) -> None:
        """Wait for a condition or time."""
        try:
            ms = int(action.value or "1000")
        except ValueError:
            ms = 1000
        await browser.wait(ms)
