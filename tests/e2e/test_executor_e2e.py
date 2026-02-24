"""E2E tests for Executor (X) -- real Playwright browser."""
from __future__ import annotations

import pytest

from src.core.executor import Executor
from src.core.types import WaitCondition

pytestmark = pytest.mark.e2e


class TestExecutorE2E:
    async def test_goto(self, page, fixture_server):
        executor = Executor(page=page)
        await executor.goto(f"{fixture_server}/simple_buttons.html")
        assert "Simple Buttons" in await page.title()

    async def test_click(self, page, fixture_server):
        executor = Executor(page=page)
        await executor.goto(f"{fixture_server}/simple_buttons.html")
        await executor.click("#btn-search")
        result = await page.text_content("#result")
        assert result is not None
        assert "검색" in result

    async def test_type_text(self, page, fixture_server):
        executor = Executor(page=page)
        await executor.goto(f"{fixture_server}/search_form.html")
        await executor.type_text("#search-input", "테스트 검색")
        value = await page.input_value("#search-input")
        assert value == "테스트 검색"

    async def test_screenshot(self, page, fixture_server):
        executor = Executor(page=page)
        await executor.goto(f"{fixture_server}/simple_buttons.html")
        data = await executor.screenshot()
        assert isinstance(data, bytes)
        assert len(data) > 100  # PNG header at minimum

    async def test_wait_for_selector(self, page, fixture_server):
        executor = Executor(page=page)
        await executor.goto(f"{fixture_server}/dynamic_content.html")
        await executor.wait_for(
            WaitCondition(type="selector", value="#content", timeout_ms=5000)
        )
        text = await page.text_content("#content")
        assert text is not None
        assert "Dynamic content loaded" in text

    async def test_press_key(self, page, fixture_server):
        executor = Executor(page=page)
        await executor.goto(f"{fixture_server}/search_form.html")
        await executor.type_text("#search-input", "키보드 테스트")
        await executor.press_key("Enter")
        # The form onsubmit calls doSearch(), so a result should appear
        count_text = await page.text_content("#result-count")
        assert count_text is not None
        assert int(count_text) >= 1

    async def test_scroll(self, page, fixture_server):
        executor = Executor(page=page)
        await executor.goto(f"{fixture_server}/simple_buttons.html")
        await executor.scroll(direction="down", amount=200)
        # Just verify no error is raised; scroll position may vary

    async def test_click_multiple_buttons(self, page, fixture_server):
        executor = Executor(page=page)
        await executor.goto(f"{fixture_server}/simple_buttons.html")

        await executor.click("#btn-sort")
        result = await page.text_content("#result")
        assert result is not None
        assert "인기순" in result

        await executor.click("#btn-next")
        result = await page.text_content("#result")
        assert result is not None
        assert "다음" in result
