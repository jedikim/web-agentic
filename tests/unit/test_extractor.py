"""Unit tests for E(Extractor) module — DOMExtractor.

Tests all four extract_* methods with mocked Playwright pages,
covering normal cases, edge cases (empty page, no products,
iframe content), and data validation.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.extractor import _MAX_VISIBLE_TEXT, DOMExtractor
from src.core.types import ExtractedElement, PageState, ProductData


@pytest.fixture
def extractor() -> DOMExtractor:
    """Create a fresh DOMExtractor instance."""
    return DOMExtractor()


def _mock_page(evaluate_return: object) -> AsyncMock:
    """Create a mock Playwright Page whose evaluate() returns the given data."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=evaluate_return)
    return page


# ── extract_inputs tests ─────────────────────────────


class TestExtractInputs:
    """Tests for extract_inputs()."""

    async def test_basic_inputs(self, extractor: DOMExtractor) -> None:
        """Should convert raw JS dicts to ExtractedElement list."""
        raw = [
            {
                "eid": "#search-box",
                "type": "input",
                "text": "Search...",
                "role": "textbox",
                "bbox": [10, 20, 300, 40],
                "visible": True,
                "parent_context": "search-form",
            },
            {
                "eid": "select:nth-of-type(1)",
                "type": "input",
                "text": "Country",
                "role": None,
                "bbox": [10, 80, 200, 30],
                "visible": True,
                "parent_context": None,
            },
        ]
        page = _mock_page(raw)
        result = await extractor.extract_inputs(page)

        assert len(result) == 2
        assert isinstance(result[0], ExtractedElement)
        assert result[0].eid == "#search-box"
        assert result[0].type == "input"
        assert result[0].text == "Search..."
        assert result[0].role == "textbox"
        assert result[0].bbox == (10, 20, 300, 40)
        assert result[0].visible is True
        assert result[0].parent_context == "search-form"

    async def test_empty_page_returns_empty_list(self, extractor: DOMExtractor) -> None:
        """Should return empty list when page has no inputs."""
        page = _mock_page([])
        result = await extractor.extract_inputs(page)
        assert result == []

    async def test_iframe_prefix_in_eid(self, extractor: DOMExtractor) -> None:
        """Should preserve iframe prefix in eid for elements inside iframes."""
        raw = [
            {
                "eid": "iframe[0] #email",
                "type": "input",
                "text": "Email",
                "role": None,
                "bbox": [5, 5, 250, 30],
                "visible": True,
                "parent_context": None,
            },
        ]
        page = _mock_page(raw)
        result = await extractor.extract_inputs(page)

        assert len(result) == 1
        assert result[0].eid == "iframe[0] #email"

    async def test_shadow_dom_prefix_in_eid(self, extractor: DOMExtractor) -> None:
        """Should preserve shadow DOM prefix in eid."""
        raw = [
            {
                "eid": "shadow(my-component) input:nth-of-type(1)",
                "type": "input",
                "text": None,
                "role": None,
                "bbox": [0, 0, 100, 25],
                "visible": True,
                "parent_context": None,
            },
        ]
        page = _mock_page(raw)
        result = await extractor.extract_inputs(page)

        assert result[0].eid.startswith("shadow(")


# ── extract_clickables tests ─────────────────────────


class TestExtractClickables:
    """Tests for extract_clickables()."""

    async def test_basic_clickables(self, extractor: DOMExtractor) -> None:
        """Should extract buttons and links with correct types."""
        raw = [
            {
                "eid": "#submit-btn",
                "type": "button",
                "text": "Submit",
                "role": "button",
                "bbox": [100, 200, 80, 36],
                "visible": True,
                "parent_context": "form-actions",
            },
            {
                "eid": "a:nth-of-type(3)",
                "type": "link",
                "text": "Privacy Policy",
                "role": None,
                "bbox": [10, 500, 120, 20],
                "visible": True,
                "parent_context": "footer",
            },
        ]
        page = _mock_page(raw)
        result = await extractor.extract_clickables(page)

        assert len(result) == 2
        assert result[0].type == "button"
        assert result[1].type == "link"

    async def test_tab_type(self, extractor: DOMExtractor) -> None:
        """Should handle tab elements with correct type."""
        raw = [
            {
                "eid": "#tab-reviews",
                "type": "tab",
                "text": "Reviews",
                "role": "tab",
                "bbox": [200, 10, 80, 30],
                "visible": True,
                "parent_context": "tab-bar",
            },
        ]
        page = _mock_page(raw)
        result = await extractor.extract_clickables(page)

        assert result[0].type == "tab"
        assert result[0].role == "tab"

    async def test_invisible_element(self, extractor: DOMExtractor) -> None:
        """Should correctly mark invisible elements."""
        raw = [
            {
                "eid": "#hidden-btn",
                "type": "button",
                "text": "Hidden",
                "role": None,
                "bbox": [0, 0, 0, 0],
                "visible": False,
                "parent_context": None,
            },
        ]
        page = _mock_page(raw)
        result = await extractor.extract_clickables(page)

        assert result[0].visible is False
        assert result[0].bbox == (0, 0, 0, 0)


# ── extract_products tests ───────────────────────────


class TestExtractProducts:
    """Tests for extract_products()."""

    async def test_basic_products(self, extractor: DOMExtractor) -> None:
        """Should extract product data with all fields."""
        raw = [
            {
                "name": "Wireless Mouse",
                "price": "$29.99",
                "url": "https://shop.example.com/mouse",
                "image_url": "https://shop.example.com/mouse.jpg",
                "rating": 4.5,
                "review_count": 128,
            },
            {
                "name": "USB Keyboard",
                "price": "$49.00",
                "url": "https://shop.example.com/keyboard",
                "image_url": None,
                "rating": 4.2,
                "review_count": 56,
            },
        ]
        page = _mock_page(raw)
        result = await extractor.extract_products(page)

        assert len(result) == 2
        assert isinstance(result[0], ProductData)
        assert result[0].name == "Wireless Mouse"
        assert result[0].price == "$29.99"
        assert result[0].url == "https://shop.example.com/mouse"
        assert result[0].image_url == "https://shop.example.com/mouse.jpg"
        assert result[0].rating == 4.5
        assert result[0].review_count == 128

    async def test_no_products_returns_empty_list(self, extractor: DOMExtractor) -> None:
        """Should return empty list when no product cards are found."""
        page = _mock_page([])
        result = await extractor.extract_products(page)
        assert result == []

    async def test_product_with_missing_optional_fields(self, extractor: DOMExtractor) -> None:
        """Should handle products where optional fields are null."""
        raw = [
            {
                "name": "Mystery Item",
                "price": None,
                "url": None,
                "image_url": None,
                "rating": None,
                "review_count": None,
            },
        ]
        page = _mock_page(raw)
        result = await extractor.extract_products(page)

        assert len(result) == 1
        assert result[0].name == "Mystery Item"
        assert result[0].price is None
        assert result[0].url is None
        assert result[0].image_url is None
        assert result[0].rating is None
        assert result[0].review_count is None


# ── extract_state tests ──────────────────────────────


class TestExtractState:
    """Tests for extract_state()."""

    async def test_basic_state(self, extractor: DOMExtractor) -> None:
        """Should capture all page state fields."""
        raw = {
            "url": "https://shop.example.com/search?q=mouse",
            "title": "Search Results",
            "visible_text": "Showing 20 products for 'mouse'",
            "element_count": 45,
            "has_popup": False,
            "has_captcha": False,
            "scroll_position": 0,
        }
        page = _mock_page(raw)
        result = await extractor.extract_state(page)

        assert isinstance(result, PageState)
        assert result.url == "https://shop.example.com/search?q=mouse"
        assert result.title == "Search Results"
        assert result.visible_text == "Showing 20 products for 'mouse'"
        assert result.element_count == 45
        assert result.has_popup is False
        assert result.has_captcha is False
        assert result.scroll_position == 0

    async def test_popup_detected(self, extractor: DOMExtractor) -> None:
        """Should detect popup/modal on the page."""
        raw = {
            "url": "https://example.com",
            "title": "Example",
            "visible_text": "Welcome! Sign up for newsletter.",
            "element_count": 10,
            "has_popup": True,
            "has_captcha": False,
            "scroll_position": 0,
        }
        page = _mock_page(raw)
        result = await extractor.extract_state(page)
        assert result.has_popup is True

    async def test_captcha_detected(self, extractor: DOMExtractor) -> None:
        """Should detect CAPTCHA on the page."""
        raw = {
            "url": "https://example.com/verify",
            "title": "Verification",
            "visible_text": "Please complete the captcha.",
            "element_count": 3,
            "has_popup": False,
            "has_captcha": True,
            "scroll_position": 0,
        }
        page = _mock_page(raw)
        result = await extractor.extract_state(page)
        assert result.has_captcha is True

    async def test_visible_text_truncation(self, extractor: DOMExtractor) -> None:
        """Should truncate visible_text to _MAX_VISIBLE_TEXT characters."""
        long_text = "x" * 5000
        raw = {
            "url": "https://example.com",
            "title": "Long Page",
            "visible_text": long_text,
            "element_count": 1,
            "has_popup": False,
            "has_captcha": False,
            "scroll_position": 0,
        }
        page = _mock_page(raw)
        result = await extractor.extract_state(page)

        assert len(result.visible_text) == _MAX_VISIBLE_TEXT

    async def test_empty_page_state(self, extractor: DOMExtractor) -> None:
        """Should handle a minimally-populated state dict gracefully."""
        raw = {
            "url": "about:blank",
            "title": "",
            "visible_text": "",
            "element_count": 0,
            "has_popup": False,
            "has_captcha": False,
            "scroll_position": 0,
        }
        page = _mock_page(raw)
        result = await extractor.extract_state(page)

        assert result.url == "about:blank"
        assert result.title == ""
        assert result.visible_text == ""
        assert result.element_count == 0

    async def test_state_with_scroll_position(self, extractor: DOMExtractor) -> None:
        """Should capture current scroll position."""
        raw = {
            "url": "https://example.com/long-page",
            "title": "Long Page",
            "visible_text": "Content here",
            "element_count": 50,
            "has_popup": False,
            "has_captcha": False,
            "scroll_position": 1200,
        }
        page = _mock_page(raw)
        result = await extractor.extract_state(page)
        assert result.scroll_position == 1200


# ── Edge case / conversion tests ─────────────────────


class TestEdgeCases:
    """Tests for edge cases and data conversion."""

    async def test_bbox_with_missing_values(self, extractor: DOMExtractor) -> None:
        """Should default missing bbox values to 0."""
        raw = [{"eid": "x", "type": "input", "bbox": [10]}]
        page = _mock_page(raw)
        result = await extractor.extract_inputs(page)

        assert result[0].bbox == (10, 0, 0, 0)

    async def test_bbox_with_empty_list(self, extractor: DOMExtractor) -> None:
        """Should default to (0,0,0,0) when bbox is empty."""
        raw = [{"eid": "x", "type": "input", "bbox": []}]
        page = _mock_page(raw)
        result = await extractor.extract_inputs(page)

        assert result[0].bbox == (0, 0, 0, 0)

    async def test_element_missing_eid_defaults_to_empty(self, extractor: DOMExtractor) -> None:
        """Should default eid to empty string when missing."""
        raw = [{"type": "input", "bbox": [0, 0, 0, 0]}]
        page = _mock_page(raw)
        result = await extractor.extract_inputs(page)

        assert result[0].eid == ""

    async def test_extracted_element_is_frozen(self, extractor: DOMExtractor) -> None:
        """ExtractedElement should be immutable (frozen dataclass)."""
        raw = [
            {
                "eid": "#test",
                "type": "input",
                "text": "Test",
                "role": None,
                "bbox": [0, 0, 100, 30],
                "visible": True,
                "parent_context": None,
            },
        ]
        page = _mock_page(raw)
        result = await extractor.extract_inputs(page)

        with pytest.raises(AttributeError):
            result[0].eid = "modified"  # type: ignore[misc]

    async def test_product_data_is_frozen(self, extractor: DOMExtractor) -> None:
        """ProductData should be immutable (frozen dataclass)."""
        raw = [{"name": "Item", "price": "$10", "url": None, "image_url": None,
                "rating": None, "review_count": None}]
        page = _mock_page(raw)
        result = await extractor.extract_products(page)

        with pytest.raises(AttributeError):
            result[0].name = "modified"  # type: ignore[misc]

    async def test_page_state_is_frozen(self, extractor: DOMExtractor) -> None:
        """PageState should be immutable (frozen dataclass)."""
        raw = {
            "url": "https://example.com",
            "title": "Test",
            "visible_text": "",
            "element_count": 0,
            "has_popup": False,
            "has_captcha": False,
            "scroll_position": 0,
        }
        page = _mock_page(raw)
        result = await extractor.extract_state(page)

        with pytest.raises(AttributeError):
            result.url = "modified"  # type: ignore[misc]

    async def test_state_missing_visible_text_defaults_empty(
        self, extractor: DOMExtractor
    ) -> None:
        """Should handle missing visible_text by defaulting to empty string."""
        raw = {
            "url": "https://example.com",
            "title": "Test",
            "visible_text": None,
            "element_count": 0,
            "has_popup": False,
            "has_captcha": False,
            "scroll_position": 0,
        }
        page = _mock_page(raw)
        result = await extractor.extract_state(page)
        assert result.visible_text == ""
