"""Tests for Browser wrapper (Playwright + CDP hybrid)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.browser import Browser


@pytest.fixture
def mock_page() -> MagicMock:
    """Create a mock Playwright Page."""
    page = AsyncMock()
    page.url = "https://example.com"
    page.viewport_size = {"width": 1280, "height": 720}
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.keyboard.type = AsyncMock()
    page.mouse = AsyncMock()
    page.mouse.click = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"fake-png")
    page.evaluate = AsyncMock(return_value=42)
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.close = AsyncMock()
    page.context = AsyncMock()
    cdp = AsyncMock()
    page.context.new_cdp_session = AsyncMock(return_value=cdp)
    return page


@pytest.fixture
def browser(mock_page: MagicMock) -> Browser:
    """Create a Browser instance with mock page."""
    return Browser(mock_page)


class TestBrowserInit:
    def test_init_stores_page(self, browser: Browser, mock_page: MagicMock) -> None:
        assert browser._page is mock_page
        assert browser._cdp is None

    def test_url_property(self, browser: Browser) -> None:
        assert browser.url == "https://example.com"

    def test_page_property(self, browser: Browser, mock_page: MagicMock) -> None:
        assert browser.page is mock_page


class TestBrowserCDP:
    async def test_get_cdp_creates_session(self, browser: Browser, mock_page: MagicMock) -> None:
        cdp = await browser.get_cdp()
        mock_page.context.new_cdp_session.assert_called_once_with(mock_page)
        assert cdp is not None

    async def test_get_cdp_reuses_session(self, browser: Browser, mock_page: MagicMock) -> None:
        cdp1 = await browser.get_cdp()
        cdp2 = await browser.get_cdp()
        assert cdp1 is cdp2
        mock_page.context.new_cdp_session.assert_called_once()


class TestBrowserExecution:
    async def test_click_selector(self, browser: Browser, mock_page: MagicMock) -> None:
        await browser.click_selector("button#submit", timeout=3000)
        mock_page.click.assert_called_once_with("button#submit", timeout=3000)

    async def test_fill_selector(self, browser: Browser, mock_page: MagicMock) -> None:
        await browser.fill_selector("input#name", "test", timeout=2000)
        mock_page.fill.assert_called_once_with("input#name", "test", timeout=2000)

    async def test_mouse_click(self, browser: Browser, mock_page: MagicMock) -> None:
        await browser.mouse_click(100.0, 200.0)
        mock_page.mouse.click.assert_called_once_with(100.0, 200.0)

    async def test_key_press(self, browser: Browser, mock_page: MagicMock) -> None:
        await browser.key_press("Enter")
        mock_page.keyboard.press.assert_called_once_with("Enter")

    async def test_type_text(self, browser: Browser, mock_page: MagicMock) -> None:
        await browser.type_text("hello", delay=50)
        mock_page.keyboard.type.assert_called_once_with("hello", delay=50)

    async def test_scroll_down(self, browser: Browser, mock_page: MagicMock) -> None:
        await browser.scroll("down", 500)
        mock_page.mouse.wheel.assert_called_once_with(0, 500)

    async def test_scroll_up(self, browser: Browser, mock_page: MagicMock) -> None:
        await browser.scroll("up", 300)
        mock_page.mouse.wheel.assert_called_once_with(0, -300)

    async def test_scroll_right(self, browser: Browser, mock_page: MagicMock) -> None:
        await browser.scroll("right", 200)
        mock_page.mouse.wheel.assert_called_once_with(200, 0)

    async def test_scroll_left(self, browser: Browser, mock_page: MagicMock) -> None:
        await browser.scroll("left", 100)
        mock_page.mouse.wheel.assert_called_once_with(-100, 0)

    async def test_goto(self, browser: Browser, mock_page: MagicMock) -> None:
        await browser.goto("https://example.com/page")
        mock_page.goto.assert_called_once_with("https://example.com/page")

    async def test_wait_for_selector(self, browser: Browser, mock_page: MagicMock) -> None:
        await browser.wait_for_selector("div.loaded", timeout=3000)
        mock_page.wait_for_selector.assert_called_once_with("div.loaded", timeout=3000)


class TestBrowserExtraction:
    async def test_screenshot(self, browser: Browser, mock_page: MagicMock) -> None:
        result = await browser.screenshot()
        assert result == b"fake-png"
        mock_page.screenshot.assert_called_once_with(type="png")

    async def test_screenshot_clip(self, browser: Browser, mock_page: MagicMock) -> None:
        clip = {"x": 10, "y": 20, "width": 100, "height": 50}
        await browser.screenshot_clip(clip)
        mock_page.screenshot.assert_called_once_with(
            type="png",
            clip={"x": 10, "y": 20, "width": 100, "height": 50},
        )

    async def test_evaluate(self, browser: Browser, mock_page: MagicMock) -> None:
        result = await browser.evaluate("1 + 1")
        assert result == 42  # mock returns 42
        mock_page.evaluate.assert_called_once_with("1 + 1")

    async def test_get_viewport_size(self, browser: Browser) -> None:
        size = await browser.get_viewport_size()
        assert size == {"width": 1280, "height": 720}

    async def test_get_viewport_size_none(self, mock_page: MagicMock) -> None:
        mock_page.viewport_size = None
        browser = Browser(mock_page)
        size = await browser.get_viewport_size()
        assert size == {"width": 1280, "height": 720}


class TestBrowserClose:
    async def test_close_detaches_cdp(self, browser: Browser, mock_page: MagicMock) -> None:
        # First get a CDP session
        cdp = await browser.get_cdp()
        await browser.close()
        cdp.detach.assert_called_once()
        mock_page.close.assert_called_once()
        assert browser._cdp is None

    async def test_close_without_cdp(self, browser: Browser, mock_page: MagicMock) -> None:
        await browser.close()
        mock_page.close.assert_called_once()


class TestBrowserWait:
    async def test_wait(self, browser: Browser) -> None:
        """Smoke test — just ensure it doesn't raise."""
        await browser.wait(10)  # 10ms
