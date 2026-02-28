"""Tests for v3 Executor — selector-first with viewport fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.browser import Browser
from src.core.types import Action
from src.core.v3_executor import V3Executor


@pytest.fixture
def mock_browser() -> Browser:
    page = AsyncMock()
    page.url = "https://example.com"
    page.viewport_size = {"width": 1280, "height": 720}
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.hover = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.keyboard.type = AsyncMock()
    page.mouse = AsyncMock()
    page.mouse.click = AsyncMock()
    page.mouse.move = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.goto = AsyncMock()
    page.context = AsyncMock()
    page.context.new_cdp_session = AsyncMock(return_value=AsyncMock())
    return Browser(page)


@pytest.fixture
def executor() -> V3Executor:
    return V3Executor()


class TestClickAction:
    async def test_click_by_selector(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector="#btn", action_type="click")
        await executor.execute_action(action, mock_browser)
        mock_browser._page.click.assert_called_once_with("#btn", timeout=3000)

    async def test_click_by_viewport(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(
            selector=None, action_type="click",
            viewport_xy=(0.5, 0.3),
        )
        await executor.execute_action(action, mock_browser)
        mock_browser._page.mouse.click.assert_called_once_with(640, 216)

    async def test_click_selector_fallback_to_viewport(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        mock_browser._page.click = AsyncMock(side_effect=Exception("not found"))
        action = Action(
            selector="#missing", action_type="click",
            viewport_xy=(0.5, 0.3),
        )
        await executor.execute_action(action, mock_browser)
        mock_browser._page.mouse.click.assert_called_once_with(640, 216)

    async def test_click_no_selector_no_viewport_raises(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector=None, action_type="click")
        with pytest.raises(RuntimeError, match="no selector"):
            await executor.execute_action(action, mock_browser)


class TestTypeAction:
    async def test_type_by_selector(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector="input#q", action_type="type", value="등산복")
        await executor.execute_action(action, mock_browser)
        mock_browser._page.fill.assert_called_once_with("input#q", "등산복", timeout=3000)

    async def test_type_by_viewport(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(
            selector=None, action_type="type",
            value="등산복", viewport_xy=(0.3, 0.1),
        )
        await executor.execute_action(action, mock_browser)
        mock_browser._page.mouse.click.assert_called_once_with(384, 72)
        mock_browser._page.keyboard.type.assert_called_once_with("등산복", delay=0)

    async def test_type_selector_fallback_to_viewport(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        mock_browser._page.fill = AsyncMock(side_effect=Exception("not found"))
        action = Action(
            selector="#missing", action_type="type",
            value="test", viewport_xy=(0.5, 0.5),
        )
        await executor.execute_action(action, mock_browser)
        mock_browser._page.mouse.click.assert_called_once()
        mock_browser._page.keyboard.type.assert_called_once()

    async def test_fill_alias(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector="input#q", action_type="fill", value="test")
        await executor.execute_action(action, mock_browser)
        mock_browser._page.fill.assert_called_once()


class TestScrollAction:
    async def test_scroll_down(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector=None, action_type="scroll", value="down 500")
        await executor.execute_action(action, mock_browser)
        mock_browser._page.mouse.wheel.assert_called_once_with(0, 500)

    async def test_scroll_default(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector=None, action_type="scroll")
        await executor.execute_action(action, mock_browser)
        mock_browser._page.mouse.wheel.assert_called_once_with(0, 300)

    async def test_scroll_invalid_amount(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector=None, action_type="scroll", value="down window")
        await executor.execute_action(action, mock_browser)
        mock_browser._page.mouse.wheel.assert_called_once_with(0, 300)


class TestHoverAction:
    async def test_hover_by_selector(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector="#menu", action_type="hover")
        await executor.execute_action(action, mock_browser)
        mock_browser._page.hover.assert_called_once_with("#menu", timeout=3000)

    async def test_hover_by_viewport(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector=None, action_type="hover", viewport_xy=(0.5, 0.5))
        await executor.execute_action(action, mock_browser)
        mock_browser._page.mouse.move.assert_called_once_with(640, 360)


class TestOtherActions:
    async def test_press_key(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector=None, action_type="press", value="Enter")
        await executor.execute_action(action, mock_browser)
        mock_browser._page.keyboard.press.assert_called_once_with("Enter")

    async def test_goto(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector=None, action_type="goto", value="https://example.com/page")
        await executor.execute_action(action, mock_browser)
        mock_browser._page.goto.assert_called_once_with("https://example.com/page")

    async def test_wait(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector=None, action_type="wait", value="100")
        await executor.execute_action(action, mock_browser)

    async def test_unknown_action_defaults_to_click(
        self, executor: V3Executor, mock_browser: Browser,
    ) -> None:
        action = Action(selector="#btn", action_type="tap")
        await executor.execute_action(action, mock_browser)
        mock_browser._page.click.assert_called_once()
