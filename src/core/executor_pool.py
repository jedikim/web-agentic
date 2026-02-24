"""Executor Pool — reuses a single browser across multiple sessions.

Avoids the overhead of launching a new Chromium browser for each task.
The pool owns the browser; individual executors own only their context+page.

Usage::

    pool = await ExecutorPool.create(headless=True)
    executor = await pool.acquire()
    # ... use executor ...
    await pool.release(executor)
    await pool.close()
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from playwright.async_api import async_playwright

from src.core.executor import Executor

if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright

logger = logging.getLogger(__name__)


class ExecutorPool:
    """Pool that reuses a single Playwright browser instance.

    Use the ``create`` classmethod to construct an instance.
    Call ``acquire`` to get a fresh Executor (new context+page).
    Call ``release`` to dispose of the executor's context only.
    Call ``close`` to shut down the browser and Playwright.

    Attributes:
        _pw: Playwright instance.
        _browser: Shared Chromium browser.
        _active: Number of currently acquired executors.
    """

    def __init__(self, pw: Playwright, browser: Browser) -> None:
        self._pw = pw
        self._browser = browser
        self._active: int = 0
        self._closed: bool = False

    @classmethod
    async def create(cls, headless: bool = True) -> ExecutorPool:
        """Create a new ExecutorPool with a launched browser.

        Args:
            headless: Whether to run browser in headless mode.

        Returns:
            A ready-to-use ExecutorPool.
        """
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=headless)
        logger.info("ExecutorPool created (headless=%s)", headless)
        return cls(pw=pw, browser=browser)

    async def acquire(self) -> Executor:
        """Acquire a new Executor with a fresh BrowserContext and Page.

        The returned Executor does NOT own the browser — only its context.
        Call ``release`` when done to clean up the context.

        Returns:
            A fresh Executor instance.

        Raises:
            RuntimeError: If the pool has been closed.
        """
        if self._closed:
            raise RuntimeError("Cannot acquire from a closed pool")

        context = await self._browser.new_context()
        page = await context.new_page()
        # Pass browser=None so Executor.close() won't kill the shared browser
        executor = Executor(page=page, browser=None, context=context)
        self._active += 1
        logger.debug("Acquired executor (active=%d)", self._active)
        return executor

    async def release(self, executor: Executor) -> None:
        """Release an executor, closing only its context.

        Args:
            executor: The executor to release.
        """
        await executor.close()
        self._active = max(0, self._active - 1)
        logger.debug("Released executor (active=%d)", self._active)

    @property
    def active_count(self) -> int:
        """Number of currently acquired executors."""
        return self._active

    @property
    def is_closed(self) -> bool:
        """Whether the pool has been closed."""
        return self._closed

    async def close(self) -> None:
        """Close the browser and Playwright instance.

        Safe to call multiple times.
        """
        if self._closed:
            return
        self._closed = True
        try:
            await self._browser.close()
        except Exception:
            logger.warning("Error closing browser", exc_info=True)
        try:
            await self._pw.stop()
        except Exception:
            logger.warning("Error stopping playwright", exc_info=True)
        logger.info("ExecutorPool closed")
