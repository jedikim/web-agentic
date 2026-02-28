"""Unit tests for ExecutorPool — browser session reuse.

Tests verify:
  - Pool creation and teardown
  - Acquire returns Executor with fresh context/page
  - Multiple acquires create independent sessions
  - Release closes context but keeps browser alive
  - Acquire after close raises RuntimeError
  - Close is idempotent
  - Executor from pool does not own browser
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.executor_pool import ExecutorPool

# ── Helpers ──────────────────────────────────────────


def _make_mock_page() -> AsyncMock:
    """Create a mock Playwright Page."""
    page = AsyncMock()
    page.goto = AsyncMock()
    page.title = AsyncMock(return_value="Test")
    return page


def _make_mock_context(page: AsyncMock | None = None) -> AsyncMock:
    """Create a mock BrowserContext that yields a page."""
    ctx = AsyncMock()
    ctx.new_page = AsyncMock(return_value=page or _make_mock_page())
    ctx.close = AsyncMock()
    return ctx


def _make_mock_browser() -> AsyncMock:
    """Create a mock Browser that yields contexts."""
    browser = AsyncMock()
    browser.new_context = AsyncMock(side_effect=lambda: _make_mock_context())
    browser.close = AsyncMock()
    return browser


def _make_mock_pw(browser: AsyncMock | None = None) -> AsyncMock:
    """Create a mock Playwright instance."""
    pw = AsyncMock()
    pw.chromium = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser or _make_mock_browser())
    pw.stop = AsyncMock()
    return pw


# ── Tests ────────────────────────────────────────────


class TestExecutorPool:
    """Tests for ExecutorPool lifecycle and session management."""

    async def test_create_and_close(self) -> None:
        """Pool can be created and closed."""
        browser = _make_mock_browser()
        pw = _make_mock_pw(browser)

        with patch("src.core.executor_pool.async_playwright") as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=pw)
            pool = await ExecutorPool.create(headless=True)

        assert not pool.is_closed
        await pool.close()
        assert pool.is_closed
        browser.close.assert_awaited_once()
        pw.stop.assert_awaited_once()

    async def test_acquire_returns_executor(self) -> None:
        """Acquire returns an Executor with a page."""
        browser = _make_mock_browser()
        pw = _make_mock_pw(browser)
        pool = ExecutorPool(pw=pw, browser=browser)

        executor = await pool.acquire()
        assert executor is not None
        assert pool.active_count == 1
        browser.new_context.assert_awaited_once()

    async def test_acquire_multiple(self) -> None:
        """Multiple acquires create independent executors."""
        browser = _make_mock_browser()
        pw = _make_mock_pw(browser)
        pool = ExecutorPool(pw=pw, browser=browser)

        ex1 = await pool.acquire()
        ex2 = await pool.acquire()
        assert pool.active_count == 2
        assert ex1 is not ex2

    async def test_release_decrements_count(self) -> None:
        """Release decrements active count."""
        browser = _make_mock_browser()
        pw = _make_mock_pw(browser)
        pool = ExecutorPool(pw=pw, browser=browser)

        executor = await pool.acquire()
        assert pool.active_count == 1
        await pool.release(executor)
        assert pool.active_count == 0

    async def test_release_closes_context_not_browser(self) -> None:
        """Release closes the executor's context but not the shared browser."""
        ctx = _make_mock_context()
        browser = _make_mock_browser()
        browser.new_context = AsyncMock(return_value=ctx)
        pw = _make_mock_pw(browser)
        pool = ExecutorPool(pw=pw, browser=browser)

        executor = await pool.acquire()
        await pool.release(executor)

        ctx.close.assert_awaited_once()
        browser.close.assert_not_awaited()  # Browser still alive

    async def test_acquire_after_close_raises(self) -> None:
        """Cannot acquire from a closed pool."""
        browser = _make_mock_browser()
        pw = _make_mock_pw(browser)
        pool = ExecutorPool(pw=pw, browser=browser)
        await pool.close()

        with pytest.raises(RuntimeError, match="closed pool"):
            await pool.acquire()

    async def test_close_idempotent(self) -> None:
        """Closing an already-closed pool is safe."""
        browser = _make_mock_browser()
        pw = _make_mock_pw(browser)
        pool = ExecutorPool(pw=pw, browser=browser)

        await pool.close()
        await pool.close()  # Should not raise
        assert browser.close.await_count == 1  # Only called once

    async def test_executor_does_not_own_browser(self) -> None:
        """Executor from pool should have browser=None."""
        browser = _make_mock_browser()
        pw = _make_mock_pw(browser)
        pool = ExecutorPool(pw=pw, browser=browser)

        executor = await pool.acquire()
        # The executor's _browser should be None (pool owns the browser)
        assert executor._browser is None
