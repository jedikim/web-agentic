"""Shared fixtures for E2E tests.

Provides a local HTTP server serving HTML fixtures and a Playwright browser.
"""
from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_PORT = 18932
FIXTURE_BASE = f"http://127.0.0.1:{FIXTURE_PORT}"


class _FixtureHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files from the fixtures directory."""

    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(*args, directory=str(FIXTURE_DIR), **kwargs)

    def log_message(self, format, *args):  # type: ignore[no-untyped-def]  # noqa: A002
        pass  # Suppress request logs during tests


@pytest.fixture(scope="session")
def fixture_server():
    """Start an HTTP server for HTML fixtures (session scope)."""
    server = http.server.HTTPServer(("127.0.0.1", FIXTURE_PORT), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield FIXTURE_BASE
    server.shutdown()


@pytest_asyncio.fixture
async def browser():
    """Launch a Playwright Chromium browser (per-test)."""
    pw = await async_playwright().start()
    _browser = await pw.chromium.launch(headless=True)
    yield _browser
    await _browser.close()
    await pw.stop()


@pytest_asyncio.fixture
async def page(browser):
    """Create a fresh BrowserContext + Page per test."""
    context = await browser.new_context()
    _page = await context.new_page()
    yield _page
    await context.close()
