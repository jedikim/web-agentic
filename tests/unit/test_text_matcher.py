"""Tests for TextMatcher — multilingual keyword_weights scoring."""

from __future__ import annotations

import pytest

from src.core.text_matcher import TextMatcher, _detect_language, _has_cjk, _is_cjk_char
from src.core.types import DOMNode


@pytest.fixture
def matcher() -> TextMatcher:
    return TextMatcher()


def _node(
    text: str = "",
    tag: str = "button",
    attrs: dict[str, str] | None = None,
    ax_role: str | None = None,
    ax_name: str | None = None,
) -> DOMNode:
    """Helper to create a DOMNode."""
    return DOMNode(
        node_id=1,
        tag=tag,
        text=text,
        attrs=attrs or {},
        ax_role=ax_role,
        ax_name=ax_name,
    )


class TestCJKDetection:
    def test_is_cjk_korean(self) -> None:
        assert _is_cjk_char("검")
        assert _is_cjk_char("ㅎ")

    def test_is_cjk_japanese(self) -> None:
        assert _is_cjk_char("あ")
        assert _is_cjk_char("ア")

    def test_is_cjk_chinese(self) -> None:
        assert _is_cjk_char("中")

    def test_not_cjk(self) -> None:
        assert not _is_cjk_char("A")
        assert not _is_cjk_char("1")
        assert not _is_cjk_char(" ")

    def test_has_cjk(self) -> None:
        assert _has_cjk("검색")
        assert _has_cjk("search검색")
        assert not _has_cjk("search")


class TestLanguageDetection:
    def test_korean(self) -> None:
        assert _detect_language("검색어를 입력하세요") == "ko"

    def test_japanese(self) -> None:
        assert _detect_language("検索してください") == "ja"

    def test_chinese(self) -> None:
        assert _detect_language("搜索关键词") == "zh"

    def test_english(self) -> None:
        assert _detect_language("search query") == "en"

    def test_empty(self) -> None:
        assert _detect_language("") == "en"

    def test_mixed_korean_english(self) -> None:
        # Korean dominates
        assert _detect_language("검색 search 입력") == "ko"


class TestTextMatcherScoring:
    def test_exact_match_korean(self, matcher: TextMatcher) -> None:
        node = _node(text="검색")
        score = matcher.score(node, {"검색": 1.0})
        assert score == 1.0

    def test_exact_match_english(self, matcher: TextMatcher) -> None:
        node = _node(text="Search button")
        score = matcher.score(node, {"search": 1.0})
        assert score == 1.0

    def test_no_match(self, matcher: TextMatcher) -> None:
        node = _node(text="Submit form")
        score = matcher.score(node, {"검색": 1.0})
        assert score == 0.0

    def test_multiple_keywords(self, matcher: TextMatcher) -> None:
        node = _node(text="검색어를 입력하세요", attrs={"placeholder": "search"})
        score = matcher.score(node, {"검색": 1.0, "search": 0.8, "입력": 0.5})
        assert score == pytest.approx(2.3)  # 1.0 + 0.8 + 0.5

    def test_partial_match(self, matcher: TextMatcher) -> None:
        node = _node(text="검색창에 입력")
        score = matcher.score(node, {"검색": 1.0, "로그인": 0.5})
        assert score == 1.0  # Only 검색 matches

    def test_weighted_scoring(self, matcher: TextMatcher) -> None:
        node = _node(text="가격 필터 적용")
        score = matcher.score(node, {"가격": 2.0, "필터": 1.0})
        assert score == 3.0

    def test_zero_weight(self, matcher: TextMatcher) -> None:
        node = _node(text="검색")
        score = matcher.score(node, {"검색": 0.0})
        assert score == 0.0

    def test_empty_text(self, matcher: TextMatcher) -> None:
        node = _node(text="")
        score = matcher.score(node, {"검색": 1.0})
        assert score == 0.0

    def test_empty_keywords(self, matcher: TextMatcher) -> None:
        node = _node(text="검색")
        score = matcher.score(node, {})
        assert score == 0.0


class TestTextMatcherAttributes:
    def test_matches_placeholder(self, matcher: TextMatcher) -> None:
        node = _node(text="", attrs={"placeholder": "Search..."})
        score = matcher.score(node, {"search": 1.0})
        assert score == 1.0

    def test_matches_aria_label(self, matcher: TextMatcher) -> None:
        node = _node(text="", attrs={"aria-label": "검색 버튼"})
        score = matcher.score(node, {"검색": 1.0})
        assert score == 1.0

    def test_matches_ax_name(self, matcher: TextMatcher) -> None:
        node = _node(text="", ax_name="Search field")
        score = matcher.score(node, {"search": 1.0})
        assert score == 1.0

    def test_matches_ax_role(self, matcher: TextMatcher) -> None:
        node = _node(text="", ax_role="searchbox")
        score = matcher.score(node, {"searchbox": 1.0})
        assert score == 1.0

    def test_combines_all_sources(self, matcher: TextMatcher) -> None:
        """All text sources are combined for matching."""
        node = _node(
            text="OK",
            attrs={"title": "검색"},
            ax_name="search",
            ax_role="button",
        )
        score = matcher.score(node, {"검색": 1.0, "search": 0.5, "button": 0.3})
        assert score == pytest.approx(1.8)


class TestTextMatcherCJK:
    def test_korean_substring(self, matcher: TextMatcher) -> None:
        """Korean substring matching (no spaces needed)."""
        node = _node(text="네이버쇼핑검색")
        score = matcher.score(node, {"검색": 1.0})
        assert score == 1.0

    def test_korean_no_space_match(self, matcher: TextMatcher) -> None:
        """Spaces in text shouldn't prevent CJK matching."""
        node = _node(text="네이버 쇼핑 검색")
        score = matcher.score(node, {"쇼핑검색": 1.0})
        assert score == 1.0  # Matched after removing spaces

    def test_japanese_substring(self, matcher: TextMatcher) -> None:
        node = _node(text="商品を検索する")
        score = matcher.score(node, {"検索": 1.0})
        assert score == 1.0

    def test_chinese_substring(self, matcher: TextMatcher) -> None:
        node = _node(text="搜索商品")
        score = matcher.score(node, {"搜索": 1.0})
        assert score == 1.0


class TestTextMatcherStemming:
    def test_english_stemming(self, matcher: TextMatcher) -> None:
        """English stemmed matching (searching -> search)."""
        node = _node(text="Searching for products")
        score = matcher.score(node, {"search": 1.0})
        # Should match via stemming or substring
        assert score > 0

    def test_english_plural(self, matcher: TextMatcher) -> None:
        """Plural forms should match via stemming."""
        node = _node(text="Products listing")
        score = matcher.score(node, {"product": 1.0})
        # "Products" contains "product" as substring
        assert score > 0


class TestTextMatcherFilterNodes:
    def test_filter_returns_top_k(self, matcher: TextMatcher) -> None:
        nodes = [
            _node(text="검색", tag="input"),
            _node(text="로그인", tag="button"),
            _node(text="검색 버튼", tag="button"),
            _node(text="홈", tag="a"),
        ]
        results = matcher.filter_nodes(nodes, {"검색": 1.0}, top_k=2)
        assert len(results) == 2
        assert results[0].score >= results[1].score

    def test_filter_excludes_zero_score(self, matcher: TextMatcher) -> None:
        nodes = [
            _node(text="검색", tag="input"),
            _node(text="로그인", tag="button"),
        ]
        results = matcher.filter_nodes(nodes, {"검색": 1.0})
        assert len(results) == 1
        assert results[0].node.text == "검색"

    def test_filter_sorted_by_score(self, matcher: TextMatcher) -> None:
        nodes = [
            _node(text="search", tag="button"),
            _node(text="검색 search query", tag="input"),
        ]
        results = matcher.filter_nodes(nodes, {"검색": 1.0, "search": 0.5})
        assert len(results) == 2
        # Second node has both keywords
        assert results[0].score > results[1].score

    def test_filter_empty_nodes(self, matcher: TextMatcher) -> None:
        results = matcher.filter_nodes([], {"검색": 1.0})
        assert results == []

    def test_filter_empty_keywords(self, matcher: TextMatcher) -> None:
        nodes = [_node(text="검색")]
        results = matcher.filter_nodes(nodes, {})
        assert results == []
