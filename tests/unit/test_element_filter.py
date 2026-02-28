"""Tests for ElementFilter — TextMatcher-based DOM node filtering."""

from __future__ import annotations

import pytest

from src.core.element_filter import ElementFilter
from src.core.text_matcher import TextMatcher
from src.core.types import DOMNode


def _node(
    text: str = "",
    tag: str = "button",
    attrs: dict[str, str] | None = None,
    ax_name: str | None = None,
    node_id: int = 1,
) -> DOMNode:
    return DOMNode(
        node_id=node_id,
        tag=tag,
        text=text,
        attrs=attrs or {},
        ax_name=ax_name,
    )


@pytest.fixture
def ef() -> ElementFilter:
    return ElementFilter()


class TestElementFilterBasic:
    def test_filter_returns_scored_nodes(self, ef: ElementFilter) -> None:
        nodes = [
            _node(text="검색", node_id=1),
            _node(text="로그인", node_id=2),
        ]
        results = ef.filter(nodes, {"검색": 1.0})
        assert len(results) == 1
        assert results[0].node.text == "검색"
        assert results[0].score == 1.0

    def test_filter_top_k(self, ef: ElementFilter) -> None:
        nodes = [_node(text=f"item {i}", node_id=i) for i in range(30)]
        results = ef.filter(nodes, {"item": 1.0}, top_k=5)
        assert len(results) == 5

    def test_filter_empty_input(self, ef: ElementFilter) -> None:
        assert ef.filter([], {"검색": 1.0}) == []

    def test_filter_no_matches(self, ef: ElementFilter) -> None:
        nodes = [_node(text="홈", node_id=1)]
        assert ef.filter(nodes, {"검색": 1.0}) == []


class TestElementFilterWithThreshold:
    def test_threshold_filters_low_scores(self, ef: ElementFilter) -> None:
        nodes = [
            _node(text="검색 입력", node_id=1),   # score = 1.0 (검색)
            _node(text="다른 것", node_id=2),      # score = 0
        ]
        results = ef.filter_with_threshold(
            nodes, {"검색": 0.3, "query": 0.2}, threshold=0.5,
        )
        # Only node with score >= 0.5 should be included
        assert len(results) <= 1

    def test_threshold_default(self, ef: ElementFilter) -> None:
        nodes = [
            _node(text="검색 query 입력", node_id=1),  # score > threshold
            _node(text="x", node_id=2),  # score = 0
        ]
        results = ef.filter_with_threshold(
            nodes, {"검색": 1.0, "query": 0.5},
        )
        assert len(results) >= 1

    def test_threshold_zero_returns_all_matching(self, ef: ElementFilter) -> None:
        nodes = [
            _node(text="a", attrs={"class": "item"}, node_id=1),
            _node(text="b", attrs={"class": "item"}, node_id=2),
        ]
        results = ef.filter_with_threshold(
            nodes, {"item": 0.1}, threshold=0.0,
        )
        assert len(results) == 2


class TestElementFilterMatcher:
    def test_custom_matcher(self) -> None:
        matcher = TextMatcher()
        ef = ElementFilter(matcher=matcher)
        assert ef.matcher is matcher

    def test_default_matcher(self, ef: ElementFilter) -> None:
        assert isinstance(ef.matcher, TextMatcher)


class TestElementFilterIntegration:
    """Integration tests simulating real-world DOM filtering."""

    def test_search_box_detection(self, ef: ElementFilter) -> None:
        """Simulate finding a search box on a Korean e-commerce site."""
        nodes = [
            _node(text="네이버쇼핑", tag="a", node_id=1),
            _node(
                text="",
                tag="input",
                attrs={"placeholder": "검색어를 입력해 주세요", "name": "query"},
                ax_name="검색",
                node_id=2,
            ),
            _node(text="로그인", tag="button", node_id=3),
            _node(text="장바구니", tag="a", node_id=4),
            _node(text="마이페이지", tag="a", node_id=5),
        ]
        results = ef.filter(
            nodes,
            {"검색": 1.0, "query": 0.8, "입력": 0.5},
        )
        assert len(results) >= 1
        # Search input should be the top result
        assert results[0].node.tag == "input"
        assert results[0].node.attrs.get("name") == "query"

    def test_price_filter_detection(self, ef: ElementFilter) -> None:
        """Simulate finding price filter inputs."""
        nodes = [
            _node(text="", tag="input", attrs={"id": "minPrice", "type": "text"}, node_id=1),
            _node(text="", tag="input", attrs={"id": "maxPrice", "type": "text"}, node_id=2),
            _node(text="적용", tag="button", node_id=3),
            _node(text="검색", tag="button", node_id=4),
            _node(text="정렬", tag="select", node_id=5),
        ]
        results = ef.filter(
            nodes,
            {"price": 1.0, "가격": 0.8, "max": 0.5},
        )
        assert len(results) >= 1
        # maxPrice should score highest
        top = results[0]
        assert "Price" in top.node.attrs.get("id", "") or "price" in str(top.node.attrs)

    def test_sorting_dropdown(self, ef: ElementFilter) -> None:
        """Simulate finding a sort dropdown."""
        nodes = [
            _node(text="정렬", tag="select", attrs={"id": "sortBy"}, node_id=1),
            _node(text="검색", tag="input", node_id=2),
            _node(text="가격순", tag="option", node_id=3),
            _node(text="인기순", tag="option", node_id=4),
        ]
        results = ef.filter(
            nodes,
            {"정렬": 1.0, "sort": 0.5, "인기순": 0.8},
        )
        assert len(results) >= 1
