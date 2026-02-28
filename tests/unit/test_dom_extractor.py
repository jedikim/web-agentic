"""Tests for CDP-based DOM Extractor."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.browser import Browser
from src.core.dom_extractor import DOMExtractor


def _make_dom_node(
    node_id: int = 1,
    tag: str = "button",
    attrs: list[str] | None = None,
    children: list[dict] | None = None,
    node_value: str | None = None,
) -> dict:
    """Helper to build a CDP DOM node dict."""
    node: dict = {
        "nodeType": 1,
        "nodeName": tag.upper(),
        "backendNodeId": node_id,
        "nodeId": node_id,
        "attributes": attrs or [],
        "children": children or [],
    }
    if node_value:
        node["nodeValue"] = node_value
    return node


def _text_node(text: str) -> dict:
    """Helper to build a CDP text node."""
    return {"nodeType": 3, "nodeValue": text}


@pytest.fixture
def extractor() -> DOMExtractor:
    return DOMExtractor()


@pytest.fixture
def mock_browser() -> Browser:
    """Create a mock Browser with CDP support."""
    page = AsyncMock()
    page.url = "https://example.com"
    page.context = AsyncMock()
    cdp = AsyncMock()
    page.context.new_cdp_session = AsyncMock(return_value=cdp)
    return Browser(page)


class TestDOMExtractorBasic:
    async def test_extracts_button(self, extractor: DOMExtractor, mock_browser: Browser) -> None:
        cdp = await mock_browser.get_cdp()
        cdp.send = AsyncMock(side_effect=[
            # DOM.getDocument
            {"root": _make_dom_node(
                node_id=1, tag="button",
                children=[_text_node("Submit")],
            )},
            # Accessibility.getFullAXTree
            {"nodes": [
                {"backendDOMNodeId": 1, "role": {"value": "button"}, "name": {"value": "Submit"}},
            ]},
        ])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes) == 1
        assert nodes[0].tag == "button"
        assert nodes[0].text == "Submit"
        assert nodes[0].ax_role == "button"
        assert nodes[0].ax_name == "Submit"

    async def test_extracts_link(self, extractor: DOMExtractor, mock_browser: Browser) -> None:
        cdp = await mock_browser.get_cdp()
        cdp.send = AsyncMock(side_effect=[
            {"root": _make_dom_node(
                node_id=2, tag="a",
                attrs=["href", "https://example.com/page"],
                children=[_text_node("Click here")],
            )},
            {"nodes": [
                {"backendDOMNodeId": 2, "role": {"value": "link"}, "name": {"value": "Click here"}},
            ]},
        ])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes) == 1
        assert nodes[0].tag == "a"
        assert nodes[0].attrs["href"] == "https://example.com/page"

    async def test_extracts_input(self, extractor: DOMExtractor, mock_browser: Browser) -> None:
        cdp = await mock_browser.get_cdp()
        cdp.send = AsyncMock(side_effect=[
            {"root": _make_dom_node(
                node_id=3, tag="input",
                attrs=["type", "text", "placeholder", "검색어를 입력하세요"],
            )},
            {"nodes": [
                {"backendDOMNodeId": 3, "role": {"value": "textbox"}, "name": {"value": "검색"}},
            ]},
        ])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes) == 1
        assert nodes[0].tag == "input"
        assert nodes[0].attrs["placeholder"] == "검색어를 입력하세요"
        assert nodes[0].ax_name == "검색"


class TestDOMExtractorInteractive:
    async def test_skips_non_interactive_div(
        self, extractor: DOMExtractor, mock_browser: Browser,
    ) -> None:
        cdp = await mock_browser.get_cdp()
        cdp.send = AsyncMock(side_effect=[
            {"root": _make_dom_node(node_id=5, tag="div", children=[_text_node("Just text")])},
            {"nodes": []},
        ])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes) == 0

    async def test_includes_div_with_role(
        self, extractor: DOMExtractor, mock_browser: Browser,
    ) -> None:
        cdp = await mock_browser.get_cdp()
        cdp.send = AsyncMock(side_effect=[
            {"root": _make_dom_node(
                node_id=6, tag="div",
                attrs=["role", "button"],
                children=[_text_node("Clickable div")],
            )},
            {"nodes": [
                {"backendDOMNodeId": 6, "role": {"value": "button"}, "name": {"value": "Clickable div"}},
            ]},
        ])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes) == 1
        assert nodes[0].ax_role == "button"

    async def test_includes_div_with_onclick(
        self, extractor: DOMExtractor, mock_browser: Browser,
    ) -> None:
        cdp = await mock_browser.get_cdp()
        cdp.send = AsyncMock(side_effect=[
            {"root": _make_dom_node(
                node_id=7, tag="div",
                attrs=["onclick", "doSomething()"],
                children=[_text_node("Click me")],
            )},
            {"nodes": []},
        ])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes) == 1

    async def test_includes_div_with_tabindex(
        self, extractor: DOMExtractor, mock_browser: Browser,
    ) -> None:
        cdp = await mock_browser.get_cdp()
        cdp.send = AsyncMock(side_effect=[
            {"root": _make_dom_node(
                node_id=8, tag="div",
                attrs=["tabindex", "0"],
                children=[_text_node("Focusable")],
            )},
            {"nodes": []},
        ])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes) == 1


class TestDOMExtractorTree:
    async def test_nested_structure(
        self, extractor: DOMExtractor, mock_browser: Browser,
    ) -> None:
        """Test extraction from nested DOM tree."""
        cdp = await mock_browser.get_cdp()
        root = {
            "nodeType": 1,
            "nodeName": "DIV",
            "backendNodeId": 100,
            "attributes": [],
            "children": [
                _make_dom_node(node_id=101, tag="button", children=[_text_node("Save")]),
                {
                    "nodeType": 1,
                    "nodeName": "NAV",
                    "backendNodeId": 102,
                    "attributes": [],
                    "children": [
                        _make_dom_node(
                            node_id=103, tag="a",
                            attrs=["href", "/home"],
                            children=[_text_node("Home")],
                        ),
                        _make_dom_node(
                            node_id=104, tag="a",
                            attrs=["href", "/about"],
                            children=[_text_node("About")],
                        ),
                    ],
                },
            ],
        }
        cdp.send = AsyncMock(side_effect=[
            {"root": root},
            {"nodes": []},
        ])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes) == 3  # button + 2 links
        tags = {n.tag for n in nodes}
        assert tags == {"button", "a"}

    async def test_shadow_dom(
        self, extractor: DOMExtractor, mock_browser: Browser,
    ) -> None:
        """Test extraction includes shadow DOM nodes."""
        cdp = await mock_browser.get_cdp()
        root = {
            "nodeType": 1,
            "nodeName": "DIV",
            "backendNodeId": 200,
            "attributes": [],
            "children": [],
            "shadowRoots": [{
                "nodeType": 1,
                "nodeName": "#shadow-root",
                "backendNodeId": 201,
                "attributes": [],
                "children": [
                    _make_dom_node(
                        node_id=202, tag="button",
                        children=[_text_node("Shadow button")],
                    ),
                ],
            }],
        }
        cdp.send = AsyncMock(side_effect=[{"root": root}, {"nodes": []}])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes) == 1
        assert nodes[0].text == "Shadow button"

    async def test_content_document_iframe(
        self, extractor: DOMExtractor, mock_browser: Browser,
    ) -> None:
        """Test extraction includes iframe content documents."""
        cdp = await mock_browser.get_cdp()
        root = {
            "nodeType": 1,
            "nodeName": "IFRAME",
            "backendNodeId": 300,
            "attributes": [],
            "children": [],
            "contentDocument": {
                "nodeType": 1,
                "nodeName": "HTML",
                "backendNodeId": 301,
                "attributes": [],
                "children": [
                    _make_dom_node(
                        node_id=302, tag="input",
                        attrs=["type", "text"],
                    ),
                ],
            },
        }
        cdp.send = AsyncMock(side_effect=[{"root": root}, {"nodes": []}])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes) == 1
        assert nodes[0].tag == "input"


class TestDOMExtractorAXMerge:
    async def test_ax_info_merged(
        self, extractor: DOMExtractor, mock_browser: Browser,
    ) -> None:
        """Test that AX tree info is correctly merged into DOM nodes."""
        cdp = await mock_browser.get_cdp()
        cdp.send = AsyncMock(side_effect=[
            {"root": _make_dom_node(
                node_id=10, tag="select",
                children=[
                    _make_dom_node(node_id=11, tag="option", children=[_text_node("Red")]),
                    _make_dom_node(node_id=12, tag="option", children=[_text_node("Blue")]),
                ],
            )},
            {"nodes": [
                {"backendDOMNodeId": 10, "role": {"value": "combobox"}, "name": {"value": "Color"}},
                {"backendDOMNodeId": 11, "role": {"value": "option"}, "name": {"value": "Red"}},
                {"backendDOMNodeId": 12, "role": {"value": "option"}, "name": {"value": "Blue"}},
            ]},
        ])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes) == 3  # select + 2 options
        select_node = next(n for n in nodes if n.tag == "select")
        assert select_node.ax_role == "combobox"
        assert select_node.ax_name == "Color"

    async def test_no_ax_info(
        self, extractor: DOMExtractor, mock_browser: Browser,
    ) -> None:
        """Test nodes without AX info have None values."""
        cdp = await mock_browser.get_cdp()
        cdp.send = AsyncMock(side_effect=[
            {"root": _make_dom_node(node_id=20, tag="button", children=[_text_node("OK")])},
            {"nodes": []},  # No AX data
        ])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes) == 1
        assert nodes[0].ax_role is None
        assert nodes[0].ax_name is None


class TestDOMExtractorTextCollection:
    async def test_text_truncation(
        self, extractor: DOMExtractor, mock_browser: Browser,
    ) -> None:
        """Test that long text is truncated to 500 chars."""
        long_text = "A" * 1000
        cdp = await mock_browser.get_cdp()
        cdp.send = AsyncMock(side_effect=[
            {"root": _make_dom_node(
                node_id=30, tag="button",
                children=[_text_node(long_text)],
            )},
            {"nodes": []},
        ])

        nodes = await extractor.extract(mock_browser)
        assert len(nodes[0].text) == 500

    async def test_empty_text_nodes(
        self, extractor: DOMExtractor, mock_browser: Browser,
    ) -> None:
        """Test that whitespace-only text nodes are ignored."""
        cdp = await mock_browser.get_cdp()
        cdp.send = AsyncMock(side_effect=[
            {"root": _make_dom_node(
                node_id=31, tag="button",
                children=[_text_node("  \n  "), _text_node("Click")],
            )},
            {"nodes": []},
        ])

        nodes = await extractor.extract(mock_browser)
        assert nodes[0].text == "Click"
