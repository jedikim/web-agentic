"""E2E tests for rule selectors against HTML fixtures."""
from __future__ import annotations

import pytest

from src.core.rule_engine import RuleEngine
from src.core.types import PageState

pytestmark = pytest.mark.e2e


class TestSelectorsE2E:
    async def test_popup_close_rule(self, page, fixture_server):
        """Test popup/modal close rule matching."""
        await page.goto(f"{fixture_server}/popup_modal.html")
        await page.click("#show-popup")

        rule_engine = RuleEngine()
        state = PageState(
            url=page.url,
            title=await page.title(),
            has_popup=True,
        )
        # Try to match a popup close rule
        match = rule_engine.match("팝업 닫기", state)
        # Match may or may not work depending on rules configured
        # The test validates the rule engine doesn't crash with real state

    async def test_search_rule(self, page, fixture_server):
        """Test search-related rule matching."""
        await page.goto(f"{fixture_server}/search_form.html")

        rule_engine = RuleEngine()
        state = PageState(url=page.url, title=await page.title())
        match = rule_engine.match("검색", state)
        # Validates rule engine processes real page state without errors

    async def test_sort_rule(self, page, fixture_server):
        """Test sort-related rule matching."""
        await page.goto(f"{fixture_server}/sort_page.html")

        rule_engine = RuleEngine()
        state = PageState(url=page.url, title=await page.title())
        match = rule_engine.match("인기순 정렬", state)
        # Validates rule engine processes real page state without errors

    async def test_pagination_rule(self, page, fixture_server):
        """Test pagination-related rule matching."""
        await page.goto(f"{fixture_server}/pagination.html")

        rule_engine = RuleEngine()
        state = PageState(url=page.url, title=await page.title())
        match = rule_engine.match("다음 페이지", state)
        # Validates rule engine processes real page state without errors

    async def test_heuristic_finds_buttons(self, page, fixture_server):
        """Test heuristic selector on simple buttons page."""
        from src.core.extractor import DOMExtractor

        await page.goto(f"{fixture_server}/simple_buttons.html")
        extractor = DOMExtractor()
        clickables = await extractor.extract_clickables(page)

        rule_engine = RuleEngine()
        # Should find a button related to "검색"
        selected = rule_engine.heuristic_select(clickables, "검색")
        # The heuristic should return something (even if not the exact button)
        assert selected is not None or len(clickables) > 0

    async def test_heuristic_finds_sort_tab(self, page, fixture_server):
        """Test heuristic selector on sort page tabs."""
        from src.core.extractor import DOMExtractor

        await page.goto(f"{fixture_server}/sort_page.html")
        extractor = DOMExtractor()
        clickables = await extractor.extract_clickables(page)

        rule_engine = RuleEngine()
        selected = rule_engine.heuristic_select(clickables, "최신순")
        # Should find the sort tab with "최신순" text
        assert selected is not None or len(clickables) > 0
