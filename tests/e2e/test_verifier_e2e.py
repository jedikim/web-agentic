"""E2E tests for Verifier (V) -- real page verification."""
from __future__ import annotations

import pytest

from src.core.types import VerifyCondition
from src.core.verifier import Verifier

pytestmark = pytest.mark.e2e


class TestVerifierE2E:
    async def test_url_contains(self, page, fixture_server):
        await page.goto(f"{fixture_server}/simple_buttons.html")
        verifier = Verifier()
        result = await verifier.verify(
            VerifyCondition(type="url_contains", value="simple_buttons"),
            page,
        )
        assert result.success

    async def test_url_contains_negative(self, page, fixture_server):
        await page.goto(f"{fixture_server}/simple_buttons.html")
        verifier = Verifier()
        result = await verifier.verify(
            VerifyCondition(type="url_contains", value="nonexistent_page", timeout_ms=500),
            page,
        )
        assert not result.success

    async def test_element_visible(self, page, fixture_server):
        await page.goto(f"{fixture_server}/simple_buttons.html")
        verifier = Verifier()
        result = await verifier.verify(
            VerifyCondition(type="element_visible", value="#btn-search"),
            page,
        )
        assert result.success

    async def test_element_visible_negative(self, page, fixture_server):
        await page.goto(f"{fixture_server}/dynamic_content.html")
        verifier = Verifier()
        # Content is hidden initially (display:none), should not be visible
        result = await verifier.verify(
            VerifyCondition(type="element_visible", value="#content", timeout_ms=200),
            page,
        )
        # Content shows after 1s, but timeout is 200ms, so should fail
        assert not result.success

    async def test_element_gone_hidden_overlay(self, page, fixture_server):
        await page.goto(f"{fixture_server}/popup_modal.html")
        verifier = Verifier()
        # Modal overlay is display:none initially
        result = await verifier.verify(
            VerifyCondition(type="element_gone", value="#modal-overlay", timeout_ms=1000),
            page,
        )
        assert result.success

    async def test_element_gone_after_close(self, page, fixture_server):
        await page.goto(f"{fixture_server}/popup_modal.html")
        verifier = Verifier()
        # Show popup
        await page.click("#show-popup")
        # Close popup
        await page.click("#close-popup")
        result = await verifier.verify(
            VerifyCondition(type="element_gone", value="#modal-overlay", timeout_ms=2000),
            page,
        )
        assert result.success

    async def test_text_present(self, page, fixture_server):
        await page.goto(f"{fixture_server}/simple_buttons.html")
        verifier = Verifier()
        result = await verifier.verify(
            VerifyCondition(type="text_present", value="검색"),
            page,
        )
        assert result.success

    async def test_text_present_negative(self, page, fixture_server):
        await page.goto(f"{fixture_server}/simple_buttons.html")
        verifier = Verifier()
        result = await verifier.verify(
            VerifyCondition(type="text_present", value="이 텍스트는 없음", timeout_ms=500),
            page,
        )
        assert not result.success

    async def test_network_idle(self, page, fixture_server):
        await page.goto(f"{fixture_server}/simple_buttons.html")
        verifier = Verifier()
        result = await verifier.verify(
            VerifyCondition(type="network_idle"),
            page,
        )
        assert result.success
