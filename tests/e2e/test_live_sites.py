"""Live site tests -- only run when RUN_LIVE_TESTS=1."""
from __future__ import annotations

import os

import pytest

from src.core.executor import Executor
from src.core.extractor import DOMExtractor

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("RUN_LIVE_TESTS"),
        reason="Live tests disabled (set RUN_LIVE_TESTS=1 to enable)",
    ),
]


class TestLiveSites:
    async def test_example_com_navigation(self, page):
        executor = Executor(page=page)
        await executor.goto("https://example.com")
        title = await page.title()
        assert "Example" in title

    async def test_example_com_dom_extraction(self, page):
        await page.goto("https://example.com")
        extractor = DOMExtractor()
        _ = await extractor.extract_clickables(page)
        state = await extractor.extract_state(page)
        assert state.url.startswith("https://example.com")
        assert state.title != ""
