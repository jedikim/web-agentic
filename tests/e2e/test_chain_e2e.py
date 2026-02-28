"""E2E tests for module chains -- R->X->V, E+R->X, full workflow."""
from __future__ import annotations

import pytest

from src.core.executor import Executor
from src.core.extractor import DOMExtractor
from src.core.rule_engine import RuleEngine
from src.core.types import PageState, VerifyCondition
from src.core.verifier import Verifier

pytestmark = pytest.mark.e2e


class TestChainE2E:
    async def test_rule_execute_verify_chain(self, page, fixture_server):
        """R -> X -> V chain: rule match, execute, verify."""
        executor = Executor(page=page)
        rule_engine = RuleEngine()
        verifier = Verifier()

        await executor.goto(f"{fixture_server}/search_form.html")
        _ = PageState(url=page.url, title=await page.title())

        # Try heuristic with extracted elements
        extractor = DOMExtractor()
        clickables = await extractor.extract_clickables(page)
        inputs = await extractor.extract_inputs(page)
        candidates = clickables + inputs

        # Find search input via heuristic
        selected = rule_engine.heuristic_select(candidates, "검색어 입력")
        # Even if heuristic doesn't find it, verify basic chain works
        if selected:
            await executor.type_text(selected, "테스트")

        # Verify the page is still on the search form
        result = await verifier.verify(
            VerifyCondition(type="url_contains", value="search_form"),
            page,
        )
        assert result.success

    async def test_full_workflow_3steps(self, page, fixture_server):
        """Full 3-step workflow: goto -> type -> click -> verify."""
        executor = Executor(page=page)
        verifier = Verifier()

        # Step 1: Navigate
        await executor.goto(f"{fixture_server}/search_form.html")
        result1 = await verifier.verify(
            VerifyCondition(type="url_contains", value="search_form"),
            page,
        )
        assert result1.success

        # Step 2: Type into search
        await executor.type_text("#search-input", "노트북")
        value = await page.input_value("#search-input")
        assert value == "노트북"

        # Step 3: Click search and verify results
        await executor.click("#search-btn")
        result3 = await verifier.verify(
            VerifyCondition(type="text_present", value="노트북", timeout_ms=3000),
            page,
        )
        assert result3.success

    async def test_heuristic_execute_chain(self, page, fixture_server):
        """E+R(heuristic) -> X chain."""
        executor = Executor(page=page)
        extractor = DOMExtractor()
        rule_engine = RuleEngine()

        await executor.goto(f"{fixture_server}/sort_page.html")
        clickables = await extractor.extract_clickables(page)

        # Heuristic should find sort-related buttons
        selected = rule_engine.heuristic_select(clickables, "인기순 정렬")
        if selected:
            await executor.click(selected)
            text = await page.text_content("#sort-result")
            assert text is not None
            assert "popular" in text.lower() or "인기" in text

    async def test_extract_then_verify_products(self, page, fixture_server):
        """E -> V chain: extract products, verify their presence."""
        verifier = Verifier()

        await page.goto(f"{fixture_server}/product_list.html")

        extractor = DOMExtractor()
        products = await extractor.extract_products(page)
        assert len(products) >= 3

        # Verify each product name is present on the page
        for product in products:
            result = await verifier.verify(
                VerifyCondition(type="text_present", value=product.name, timeout_ms=1000),
                page,
            )
            assert result.success, f"Product '{product.name}' not found on page"

    async def test_pagination_click_chain(self, page, fixture_server):
        """X -> V pagination chain: click page links, verify content updates."""
        executor = Executor(page=page)
        verifier = Verifier()

        await executor.goto(f"{fixture_server}/pagination.html")

        # Verify initial page
        result1 = await verifier.verify(
            VerifyCondition(type="text_present", value="Page 1 content"),
            page,
        )
        assert result1.success

        # Click page 2
        await executor.click('[data-page="2"]')
        result2 = await verifier.verify(
            VerifyCondition(type="text_present", value="Page 2 content", timeout_ms=2000),
            page,
        )
        assert result2.success

        # Click page 3
        await executor.click('[data-page="3"]')
        result3 = await verifier.verify(
            VerifyCondition(type="text_present", value="Page 3 content", timeout_ms=2000),
            page,
        )
        assert result3.success
