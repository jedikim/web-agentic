"""E2E tests for the Evolution UI — Playwright browser tests.

Starts the FastAPI server + Vite dev server, then uses Playwright
to navigate all 4 pages and verify rendering.

Requires: npm install in evolution-ui/, playwright browsers installed.

Usage:
    pytest tests/e2e/test_evolution_ui_e2e.py -v --headed
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Skip if playwright not available
pytest.importorskip("playwright")

from playwright.async_api import async_playwright, Page

UI_DIR = Path(__file__).resolve().parent.parent.parent / "evolution-ui"
API_PORT = 18766
UI_PORT = 15173
API_URL = f"http://localhost:{API_PORT}"
UI_URL = f"http://localhost:{UI_PORT}"


# ── Fixtures ─────────────────────────────────────────


@pytest.fixture(scope="module")
def api_server():
    """Start the FastAPI server for UI tests."""
    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.api.main:app",
         "--host", "127.0.0.1", "--port", str(API_PORT), "--log-level", "warning"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for server to start
    import requests
    for _ in range(30):
        try:
            resp = requests.get(f"{API_URL}/health", timeout=1)
            if resp.status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.skip("Could not start API server")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def ui_server(api_server):
    """Start the Vite dev server for UI tests."""
    if not (UI_DIR / "node_modules").exists():
        pytest.skip("evolution-ui not installed (run npm install first)")

    env = os.environ.copy()
    # Tell Vite to proxy API calls to our test server port
    env["VITE_API_PORT"] = str(API_PORT)
    proc = subprocess.Popen(
        ["npx", "vite", "--port", str(UI_PORT), "--strictPort"],
        cwd=str(UI_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for Vite to be ready
    import requests
    for _ in range(30):
        try:
            resp = requests.get(UI_URL, timeout=1)
            if resp.status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.skip("Could not start Vite dev server")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
async def page(ui_server) -> Page:
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True)
    p = await b.new_page()
    yield p
    await p.close()
    await b.close()
    await pw.stop()


# ── Tests ────────────────────────────────────────────
# Note: We use wait_for_selector instead of wait_for_load_state("networkidle")
# because the SSE EventSource keeps the network active.


@pytest.mark.e2e
async def test_dashboard_loads(page: Page) -> None:
    """Dashboard page renders with key elements."""
    await page.goto(UI_URL)

    # Wait for the h1 to appear (page loaded + API data fetched)
    await page.wait_for_selector("h1:has-text('Dashboard')", timeout=15000)

    # Navigation bar
    nav = page.locator("nav")
    assert await nav.is_visible()

    # Title in navbar
    title = page.locator("nav >> text=Evolution Engine")
    assert await title.is_visible()

    # Stats cards should exist — "Current Version" label
    card = page.locator("text=Current Version")
    assert await card.is_visible()


@pytest.mark.e2e
async def test_navigation_between_pages(page: Page) -> None:
    """All 4 pages are navigable."""
    await page.goto(UI_URL)
    await page.wait_for_selector("h1:has-text('Dashboard')", timeout=15000)

    # Navigate to Evolutions via nav link
    await page.locator("nav >> text=Evolutions").click()
    await page.wait_for_selector("h1:has-text('Evolutions')", timeout=15000)

    # Navigate to Scenarios
    await page.locator("nav >> text=Scenarios").click()
    await page.wait_for_selector("h1:has-text('Scenarios')", timeout=15000)

    # Navigate to Versions
    await page.locator("nav >> text=Versions").click()
    await page.wait_for_selector("h1:has-text('Versions')", timeout=15000)

    # Back to Dashboard
    await page.locator("nav >> text=Dashboard").click()
    await page.wait_for_selector("h1:has-text('Dashboard')", timeout=15000)


@pytest.mark.e2e
async def test_evolutions_page_trigger_button(page: Page) -> None:
    """Evolutions page has a Trigger Evolution button."""
    await page.goto(f"{UI_URL}/evolutions")
    await page.wait_for_selector("h1:has-text('Evolutions')", timeout=15000)

    btn = page.locator("button:has-text('Trigger Evolution')")
    assert await btn.is_visible()

    # Empty state message
    empty = page.locator("text=No evolution runs yet")
    assert await empty.is_visible()


@pytest.mark.e2e
async def test_scenarios_page_run_button(page: Page) -> None:
    """Scenarios page has a Run Scenarios button."""
    await page.goto(f"{UI_URL}/scenarios")
    await page.wait_for_selector("h1:has-text('Scenarios')", timeout=15000)

    btn = page.locator("button:has-text('Run Scenarios')")
    assert await btn.is_visible()


@pytest.mark.e2e
async def test_versions_page_shows_default(page: Page) -> None:
    """Versions page shows default version."""
    await page.goto(f"{UI_URL}/versions")
    await page.wait_for_selector("h1:has-text('Versions')", timeout=15000)

    # Should show current version (v0.1.0) somewhere on the page
    version_text = page.locator("text=v0.1.0")
    assert await version_text.is_visible()


@pytest.mark.e2e
async def test_api_proxy_works(page: Page) -> None:
    """Vite proxy to API backend works (health check via browser)."""
    resp = await page.request.get(f"{UI_URL}/api/scenarios/results")
    assert resp.status == 200
    data = await resp.json()
    assert isinstance(data, list)
