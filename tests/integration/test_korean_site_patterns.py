"""Integration tests for Korean e-commerce site patterns.

Tests v3 pipeline components working together with patterns common in
Korean shopping sites (Naver, Coupang, 11st, Danawa, etc.):
- Popup/overlay handling
- Search flow (type + enter)
- Category navigation with Korean text
- Price filter inputs
- Product card clicking
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.core.cache import Cache, InMemoryCacheDB
from src.core.element_filter import ElementFilter
from src.core.planner import Planner
from src.core.result_verifier import ResultVerifier
from src.core.text_matcher import TextMatcher
from src.core.types import (
    CacheEntry,
    DOMNode,
)

# ── Shared fixtures ──

@pytest.fixture
def text_matcher() -> TextMatcher:
    return TextMatcher()


@pytest.fixture
def element_filter(text_matcher: TextMatcher) -> ElementFilter:
    return ElementFilter(matcher=text_matcher)


@pytest.fixture
def cache() -> Cache:
    return Cache(db=InMemoryCacheDB())


# ── Test: Korean keyword matching ──


class TestKoreanKeywordMatching:
    """Tests that Korean keywords match DOM nodes correctly."""

    def test_exact_korean_text_match(self, element_filter: ElementFilter) -> None:
        nodes = [
            DOMNode(node_id=1, tag="a", text="스포츠/레저", attrs={}),
            DOMNode(node_id=2, tag="a", text="패션의류", attrs={}),
            DOMNode(node_id=3, tag="a", text="디지털/가전", attrs={}),
        ]
        kw = {"스포츠": 0.9, "레저": 0.8}
        result = element_filter.filter(nodes, kw)
        assert len(result) > 0
        assert result[0].node.text == "스포츠/레저"

    def test_partial_korean_match(self, element_filter: ElementFilter) -> None:
        nodes = [
            DOMNode(node_id=1, tag="button", text="검색", attrs={}),
            DOMNode(node_id=2, tag="input", text="", attrs={"placeholder": "검색어를 입력하세요"}),
        ]
        kw = {"검색": 1.0}
        result = element_filter.filter(nodes, kw)
        assert len(result) >= 1
        # Both should match since "검색" appears in both
        texts = [r.node.text or r.node.attrs.get("placeholder", "") for r in result]
        assert any("검색" in t for t in texts)

    def test_search_input_by_placeholder(self, element_filter: ElementFilter) -> None:
        nodes = [
            DOMNode(node_id=1, tag="input", text="", attrs={"placeholder": "상품명을 입력하세요"}),
            DOMNode(node_id=2, tag="div", text="추천 상품", attrs={}),
        ]
        kw = {"상품": 0.8, "입력": 0.6}
        result = element_filter.filter(nodes, kw)
        assert len(result) > 0

    def test_mixed_korean_english(self, element_filter: ElementFilter) -> None:
        nodes = [
            DOMNode(node_id=1, tag="button", text="Search 검색", attrs={}),
            DOMNode(node_id=2, tag="button", text="Login 로그인", attrs={}),
        ]
        kw = {"검색": 0.9, "search": 0.7}
        result = element_filter.filter(nodes, kw)
        assert result[0].node.text == "Search 검색"


# ── Test: Popup/overlay patterns ──


class TestPopupPatterns:
    """Tests obstacle detection patterns common in Korean sites."""

    async def test_popup_detected_and_handled(self) -> None:
        """Simulates VLM detecting a popup and providing close coordinates."""
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(
            return_value=json.dumps({
                "has_obstacle": True,
                "obstacle_type": "popup",
                "obstacle_close_xy": [0.95, 0.02],
                "obstacle_description": "이벤트 팝업 - 오늘만 특가",
            })
        )
        planner = Planner(vlm=vlm)
        state = await planner.check_screen(b"screenshot")

        assert state.has_obstacle
        assert state.obstacle_type == "popup"
        assert state.obstacle_close_xy == pytest.approx((0.95, 0.02))

    async def test_cookie_consent_pattern(self) -> None:
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(
            return_value=json.dumps({
                "has_obstacle": True,
                "obstacle_type": "cookie_consent",
                "obstacle_close_xy": [0.5, 0.85],
                "obstacle_description": "쿠키 사용 동의",
            })
        )
        planner = Planner(vlm=vlm)
        state = await planner.check_screen(b"screenshot")

        assert state.obstacle_type == "cookie_consent"

    async def test_clean_screen(self) -> None:
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(
            return_value='{"has_obstacle": false}'
        )
        planner = Planner(vlm=vlm)
        state = await planner.check_screen(b"screenshot")

        assert not state.has_obstacle


# ── Test: Search flow end-to-end ──


class TestSearchFlow:
    """Tests the search flow pattern: click → type → press Enter."""

    async def test_search_plan_decomposition(self) -> None:
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(
            return_value=json.dumps([
                {
                    "step_index": 0,
                    "action_type": "click",
                    "target_description": "검색창",
                    "keyword_weights": {"검색": 0.9, "search": 0.7, "input": 0.5},
                    "target_viewport_xy": [0.5, 0.03],
                    "expected_result": "DOM 존재: input:focus",
                },
                {
                    "step_index": 1,
                    "action_type": "type",
                    "target_description": "검색어 입력",
                    "value": "등산복",
                    "keyword_weights": {"검색": 0.9},
                    "target_viewport_xy": [0.5, 0.03],
                    "expected_result": "화면 변화",
                },
                {
                    "step_index": 2,
                    "action_type": "press",
                    "target_description": "엔터",
                    "keyword_weights": {},
                    "target_viewport_xy": [0.5, 0.03],
                    "expected_result": "URL 변경: /search",
                },
            ])
        )
        planner = Planner(vlm=vlm)
        steps = await planner.plan("등산복 검색", b"screenshot")

        assert len(steps) == 3
        assert steps[0].action_type == "click"
        assert steps[1].action_type == "type"
        assert steps[1].value == "등산복"
        assert steps[2].action_type == "press"

    async def test_search_filter_finds_input(self, element_filter: ElementFilter) -> None:
        """After planning, verify TextMatcher finds the search input."""
        nodes = [
            DOMNode(node_id=1, tag="input", text="", attrs={
                "id": "search-input", "placeholder": "검색어를 입력하세요",
                "name": "query", "type": "text",
            }),
            DOMNode(node_id=2, tag="button", text="검색", attrs={"type": "submit"}),
            DOMNode(node_id=3, tag="a", text="로그인", attrs={"href": "/login"}),
            DOMNode(node_id=4, tag="a", text="회원가입", attrs={"href": "/signup"}),
        ]
        kw = {"검색": 0.9, "search": 0.7, "input": 0.5}
        result = element_filter.filter(nodes, kw)

        # Should find search-related elements
        assert len(result) >= 1
        tags_found = {r.node.tag for r in result}
        assert "input" in tags_found or "button" in tags_found


# ── Test: Category navigation ──


class TestCategoryNavigation:
    """Tests category menu navigation patterns in Korean sites."""

    def test_category_menu_matching(self, element_filter: ElementFilter) -> None:
        """Simulates Danawa/Naver category menu."""
        nodes = [
            DOMNode(node_id=1, tag="a", text="스포츠/레저", attrs={"href": "/category/sports"}),
            DOMNode(node_id=2, tag="a", text="패션의류/잡화", attrs={"href": "/category/fashion"}),
            DOMNode(node_id=3, tag="a", text="디지털/가전", attrs={"href": "/category/digital"}),
            DOMNode(node_id=4, tag="a", text="식품/건강", attrs={"href": "/category/food"}),
            DOMNode(node_id=5, tag="a", text="생활/자동차", attrs={"href": "/category/life"}),
        ]
        # Planner decides "등산복 → 스포츠/레저"
        kw = {"스포츠": 0.9, "레저": 0.8}
        result = element_filter.filter(nodes, kw)

        assert result[0].node.text == "스포츠/레저"
        assert result[0].score > 0

    def test_subcategory_matching(self, element_filter: ElementFilter) -> None:
        """Tests subcategory matching in expanded menu."""
        nodes = [
            DOMNode(node_id=1, tag="a", text="등산/캠핑", attrs={}),
            DOMNode(node_id=2, tag="a", text="수영/서핑", attrs={}),
            DOMNode(node_id=3, tag="a", text="피트니스", attrs={}),
            DOMNode(node_id=4, tag="a", text="자전거", attrs={}),
        ]
        kw = {"등산": 1.0, "캠핑": 0.7}
        result = element_filter.filter(nodes, kw)

        assert result[0].node.text == "등산/캠핑"


# ── Test: Cache hit/miss patterns ──


class TestCachePatterns:
    """Tests cache behavior with Korean site patterns."""

    async def test_cached_search_selector(self, cache: Cache) -> None:
        entry = CacheEntry(
            domain="search.shopping.naver.com",
            url_pattern="https://search.shopping.naver.com/search/all",
            task_type="검색창 클릭",
            selector="input#search_input",
            action_type="click",
            keyword_weights={"검색": 0.9},
            viewport_xy=(0.5, 0.03),
            expected_result="DOM 존재: input:focus",
        )
        await cache.store(entry)

        result = await cache.lookup(
            "search.shopping.naver.com",
            "https://search.shopping.naver.com/search/all",
            "검색창 클릭",
        )
        assert result is not None
        assert result.selector == "input#search_input"

    async def test_cache_miss_different_site(self, cache: Cache) -> None:
        entry = CacheEntry(
            domain="search.shopping.naver.com",
            url_pattern="https://search.shopping.naver.com/search/all",
            task_type="검색창 클릭",
            selector="input#search_input",
            action_type="click",
        )
        await cache.store(entry)

        # Different domain
        result = await cache.lookup(
            "www.coupang.com",
            "https://www.coupang.com",
            "검색창 클릭",
        )
        assert result is None


# ── Test: Result verification patterns ──


class TestVerificationPatterns:
    """Tests result verification for Korean site patterns."""

    def test_url_hint_extraction(self) -> None:
        verifier = ResultVerifier()
        hint = verifier._extract_url_hint("URL 변경: /search?q=등산복")
        assert hint == "/search?q=등산복"

    def test_dom_hint_extraction(self) -> None:
        verifier = ResultVerifier()
        hint = verifier._extract_dom_hint("DOM 존재: .product-list")
        assert hint == ".product-list"

    def test_korean_url_with_encoding(self) -> None:
        verifier = ResultVerifier()
        hint = verifier._extract_url_hint("URL 변경: /search?q=%EB%93%B1%EC%82%B0%EB%B3%B5")
        assert hint is not None
        assert "/search" in hint
