"""Unit tests for X(Executor) — Playwright async wrapper.

All Playwright objects (Page, Browser, BrowserContext) are mocked.
Tests verify:
  - Success paths for each method
  - Exception mapping (Playwright errors -> domain exceptions)
  - Timeout behaviour
  - ClickOptions propagation
  - Partial screenshot region handling
  - WaitCondition type dispatching
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.core.executor import Executor, _map_playwright_error, create_executor
from src.core.types import (
    ClickOptions,
    NetworkError,
    NotInteractableError,
    SelectorNotFoundError,
    WaitCondition,
)

# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def mock_page() -> AsyncMock:
    """Create a mock Playwright Page with all needed async methods."""
    page = AsyncMock()
    page.goto = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"\x89PNG_FAKE_DATA")
    page.wait_for_selector = AsyncMock()
    page.wait_for_url = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()

    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()

    page.mouse = AsyncMock()
    page.mouse.wheel = AsyncMock()

    return page


@pytest.fixture
def executor(mock_page: AsyncMock) -> Executor:
    """Create an Executor wrapping a mock page."""
    return Executor(page=mock_page)


# ── 1. goto ───────────────────────────────────────────


async def test_goto_success(executor: Executor, mock_page: AsyncMock) -> None:
    """goto() calls page.goto with URL and navigation timeout."""
    await executor.goto("https://example.com")
    mock_page.goto.assert_awaited_once_with(
        "https://example.com", timeout=30_000
    )


async def test_goto_network_error(executor: Executor, mock_page: AsyncMock) -> None:
    """goto() maps net:: Playwright errors to NetworkError."""
    mock_page.goto.side_effect = PlaywrightError("net::ERR_CONNECTION_REFUSED")
    with pytest.raises(NetworkError, match="Network error"):
        await executor.goto("https://unreachable.test")


async def test_goto_timeout(executor: Executor, mock_page: AsyncMock) -> None:
    """goto() maps PlaywrightTimeoutError to NetworkError."""
    mock_page.goto.side_effect = PlaywrightTimeoutError("Timeout 30000ms exceeded")
    with pytest.raises(NetworkError, match="timed out"):
        await executor.goto("https://slow.test")


# ── 2. click ──────────────────────────────────────────


async def test_click_success(executor: Executor, mock_page: AsyncMock) -> None:
    """click() forwards selector and default ClickOptions to page.click."""
    await executor.click("#submit")
    mock_page.click.assert_awaited_once_with(
        "#submit", button="left", click_count=1, force=False, timeout=5000
    )


async def test_click_with_options(executor: Executor, mock_page: AsyncMock) -> None:
    """click() propagates custom ClickOptions correctly."""
    opts = ClickOptions(button="right", click_count=2, force=True, timeout_ms=8000)
    await executor.click("button.menu", options=opts)
    mock_page.click.assert_awaited_once_with(
        "button.menu", button="right", click_count=2, force=True, timeout=8000
    )


async def test_click_not_found(executor: Executor, mock_page: AsyncMock) -> None:
    """click() raises SelectorNotFoundError when element is missing."""
    mock_page.click.side_effect = PlaywrightTimeoutError(
        "Timeout 5000ms exceeded waiting for selector '#ghost'"
    )
    with pytest.raises(SelectorNotFoundError, match="selector"):
        await executor.click("#ghost")


async def test_click_not_interactable(executor: Executor, mock_page: AsyncMock) -> None:
    """click() raises NotInteractableError when element is not visible."""
    mock_page.click.side_effect = PlaywrightError(
        "Element is not visible"
    )
    with pytest.raises(NotInteractableError, match="not interactable"):
        await executor.click("#hidden-btn")


# ── 3. type_text ──────────────────────────────────────


async def test_type_text_success(executor: Executor, mock_page: AsyncMock) -> None:
    """type_text() fills the input element with the given text."""
    await executor.type_text("#search", "hello world")
    mock_page.fill.assert_awaited_once_with(
        "#search", "hello world", timeout=5000
    )


async def test_type_text_not_found(executor: Executor, mock_page: AsyncMock) -> None:
    """type_text() raises SelectorNotFoundError for missing inputs."""
    mock_page.fill.side_effect = PlaywrightTimeoutError(
        "Timeout 5000ms exceeded waiting for selector '#missing'"
    )
    with pytest.raises(SelectorNotFoundError):
        await executor.type_text("#missing", "data")


# ── 4. press_key ──────────────────────────────────────


async def test_press_key_success(executor: Executor, mock_page: AsyncMock) -> None:
    """press_key() delegates to page.keyboard.press."""
    await executor.press_key("Enter")
    mock_page.keyboard.press.assert_awaited_once_with("Enter")


async def test_press_key_combo(executor: Executor, mock_page: AsyncMock) -> None:
    """press_key() handles key combinations like 'Control+a'."""
    await executor.press_key("Control+a")
    mock_page.keyboard.press.assert_awaited_once_with("Control+a")


# ── 5. scroll ─────────────────────────────────────────


async def test_scroll_down(executor: Executor, mock_page: AsyncMock) -> None:
    """scroll(down) sends positive delta_y to mouse.wheel."""
    await executor.scroll("down", 500)
    mock_page.mouse.wheel.assert_awaited_once_with(0, 500)


async def test_scroll_up(executor: Executor, mock_page: AsyncMock) -> None:
    """scroll(up) sends negative delta_y to mouse.wheel."""
    await executor.scroll("up", 200)
    mock_page.mouse.wheel.assert_awaited_once_with(0, -200)


# ── 6. screenshot ─────────────────────────────────────


async def test_screenshot_full(executor: Executor, mock_page: AsyncMock) -> None:
    """screenshot() without region captures the full viewport."""
    data = await executor.screenshot()
    assert data == b"\x89PNG_FAKE_DATA"
    mock_page.screenshot.assert_awaited_once_with(type="png")


async def test_screenshot_region(executor: Executor, mock_page: AsyncMock) -> None:
    """screenshot(region=...) passes clip dict to Playwright."""
    mock_page.screenshot.return_value = b"\x89PNG_REGION"
    data = await executor.screenshot(region=(10, 20, 300, 400))
    assert data == b"\x89PNG_REGION"
    mock_page.screenshot.assert_awaited_once_with(
        clip={"x": 10, "y": 20, "width": 300, "height": 400},
        type="png",
    )


# ── 7. wait_for ───────────────────────────────────────


async def test_wait_for_selector(executor: Executor, mock_page: AsyncMock) -> None:
    """wait_for(type=selector) delegates to wait_for_selector."""
    cond = WaitCondition(type="selector", value="#results", timeout_ms=3000)
    await executor.wait_for(cond)
    mock_page.wait_for_selector.assert_awaited_once_with("#results", timeout=3000)


async def test_wait_for_url(executor: Executor, mock_page: AsyncMock) -> None:
    """wait_for(type=url) delegates to wait_for_url."""
    cond = WaitCondition(type="url", value="**/search**", timeout_ms=5000)
    await executor.wait_for(cond)
    mock_page.wait_for_url.assert_awaited_once_with("**/search**", timeout=5000)


async def test_wait_for_text(executor: Executor, mock_page: AsyncMock) -> None:
    """wait_for(type=text) waits for a text= selector."""
    cond = WaitCondition(type="text", value="Loading complete", timeout_ms=7000)
    await executor.wait_for(cond)
    mock_page.wait_for_selector.assert_awaited_once_with(
        "text=Loading complete", timeout=7000
    )


async def test_wait_for_network_idle(executor: Executor, mock_page: AsyncMock) -> None:
    """wait_for(type=network_idle) delegates to wait_for_load_state."""
    cond = WaitCondition(type="network_idle", timeout_ms=15000)
    await executor.wait_for(cond)
    mock_page.wait_for_load_state.assert_awaited_once_with(
        "networkidle", timeout=15000
    )


async def test_wait_for_timeout(executor: Executor, mock_page: AsyncMock) -> None:
    """wait_for(type=timeout) waits a fixed number of milliseconds."""
    cond = WaitCondition(type="timeout", value="2000", timeout_ms=10000)
    await executor.wait_for(cond)
    mock_page.wait_for_timeout.assert_awaited_once_with(2000)


async def test_wait_for_selector_timeout_error(
    executor: Executor, mock_page: AsyncMock
) -> None:
    """wait_for raises SelectorNotFoundError when selector times out."""
    mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError(
        "Timeout 3000ms exceeded waiting for selector '#slow'"
    )
    cond = WaitCondition(type="selector", value="#slow", timeout_ms=3000)
    with pytest.raises(SelectorNotFoundError):
        await executor.wait_for(cond)


async def test_wait_for_unknown_type(executor: Executor) -> None:
    """wait_for raises ValueError for unrecognized condition types."""
    cond = WaitCondition(type="magic", value="abracadabra")
    with pytest.raises(ValueError, match="Unknown wait condition type"):
        await executor.wait_for(cond)


# ── 8. get_page ───────────────────────────────────────


async def test_get_page(executor: Executor, mock_page: AsyncMock) -> None:
    """get_page() returns the wrapped Playwright Page."""
    page = await executor.get_page()
    assert page is mock_page


# ── 9. close ──────────────────────────────────────────


async def test_close_with_owned_resources() -> None:
    """close() closes context and browser when owned."""
    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_browser = AsyncMock()
    ex = Executor(page=mock_page, browser=mock_browser, context=mock_context)

    await ex.close()

    mock_context.close.assert_awaited_once()
    mock_browser.close.assert_awaited_once()


async def test_close_without_owned_resources(
    executor: Executor, mock_page: AsyncMock
) -> None:
    """close() is safe when browser/context were not provided."""
    await executor.close()  # should not raise


# ── 10. _map_playwright_error ─────────────────────────


def test_map_timeout_with_selector() -> None:
    """PlaywrightTimeoutError + selector -> SelectorNotFoundError."""
    err = PlaywrightTimeoutError("Timeout 5000ms exceeded")
    result = _map_playwright_error(err, "#btn")
    assert isinstance(result, SelectorNotFoundError)


def test_map_timeout_without_selector() -> None:
    """PlaywrightTimeoutError without selector -> NetworkError."""
    err = PlaywrightTimeoutError("Timeout 30000ms exceeded")
    result = _map_playwright_error(err)
    assert isinstance(result, NetworkError)


def test_map_element_not_visible() -> None:
    """'element is not visible' -> NotInteractableError."""
    err = PlaywrightError("Element is not visible")
    result = _map_playwright_error(err, ".hidden")
    assert isinstance(result, NotInteractableError)


def test_map_element_detached() -> None:
    """'not attached' -> NotInteractableError."""
    err = PlaywrightError("Element is not attached to the DOM")
    result = _map_playwright_error(err, "div.old")
    assert isinstance(result, NotInteractableError)


def test_map_network_err() -> None:
    """'net::' prefix -> NetworkError."""
    err = PlaywrightError("net::ERR_NAME_NOT_RESOLVED")
    result = _map_playwright_error(err)
    assert isinstance(result, NetworkError)


def test_map_fallback() -> None:
    """Unrecognized error maps to SelectorNotFoundError as fallback."""
    err = PlaywrightError("some exotic error")
    result = _map_playwright_error(err)
    assert isinstance(result, SelectorNotFoundError)


# ── 11. create_executor factory ───────────────────────


async def test_create_executor_factory() -> None:
    """create_executor() launches browser, creates context and page."""
    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_start = AsyncMock(return_value=mock_pw)

    with patch("src.core.executor.async_playwright") as mock_ap:
        mock_ap.return_value.start = mock_start
        # async_playwright() returns an object whose .start() returns the pw
        mock_ap_cm = MagicMock()
        mock_ap_cm.start = mock_start
        mock_ap.return_value = mock_ap_cm

        executor = await create_executor(headless=True)

    assert isinstance(executor, Executor)
    page = await executor.get_page()
    assert page is mock_page
