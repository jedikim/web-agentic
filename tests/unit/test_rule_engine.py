"""Unit tests for R(Rule Engine) — ``src.core.rule_engine``."""
from __future__ import annotations

import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml

from src.core.rule_engine import RuleEngine, VALID_CATEGORIES, _normalise, _text_similarity
from src.core.types import ExtractedElement, PageState, RuleDefinition


# ── Fixtures ─────────────────────────────────────────


@pytest.fixture()
def tmp_config(tmp_path: Path) -> Path:
    """Create a temporary config directory with synonyms and rules."""
    # synonyms.yaml
    synonyms = {
        "sort_synonyms": {
            "popular": ["인기순", "인기", "베스트", "popular", "best"],
            "latest": ["최신순", "최신", "newest", "latest"],
            "price_low": ["낮은가격순", "저가순", "cheapest"],
        },
        "popup_close_synonyms": {
            "cookie": ["쿠키", "cookie", "동의", "agree"],
        },
    }
    (tmp_path / "synonyms.yaml").write_text(
        yaml.dump(synonyms, allow_unicode=True), encoding="utf-8"
    )

    # rules directory
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    # sort_popular rule
    rule1 = {
        "rule": {
            "name": "sort_by_popular",
            "category": "sort",
            "trigger": {"intent": "인기순 정렬", "site_pattern": "*"},
            "selector": ".sort-popular",
            "method": "click",
            "priority": 10,
            "guardrail": {"max_retries": 3, "timeout_ms": 10000},
        }
    }
    (rules_dir / "sort_popular.yaml").write_text(
        yaml.dump(rule1, allow_unicode=True), encoding="utf-8"
    )

    # popup_close rule
    rule2 = {
        "rule": {
            "name": "popup_close_cookie",
            "category": "popup",
            "trigger": {"intent": "쿠키 팝업 닫기", "site_pattern": "*.naver.com"},
            "selector": "#cookie-close-btn",
            "method": "click",
            "priority": 20,
        }
    }
    (rules_dir / "popup_close.yaml").write_text(
        yaml.dump(rule2, allow_unicode=True), encoding="utf-8"
    )

    # Low priority sort rule
    rule3 = {
        "rule": {
            "name": "sort_by_latest",
            "category": "sort",
            "trigger": {"intent": "최신순 정렬"},
            "selector": ".sort-latest",
            "method": "click",
            "priority": 5,
        }
    }
    (rules_dir / "sort_latest.yaml").write_text(
        yaml.dump(rule3, allow_unicode=True), encoding="utf-8"
    )

    return tmp_path


@pytest.fixture()
def engine(tmp_config: Path) -> RuleEngine:
    """Create a RuleEngine backed by the temporary config."""
    return RuleEngine(config_dir=tmp_config)


@pytest.fixture()
def page_state() -> PageState:
    """Default PageState for testing."""
    return PageState(
        url="https://shopping.naver.com/search?query=laptop",
        title="Naver Shopping",
    )


@pytest.fixture()
def candidates() -> list[ExtractedElement]:
    """Mock candidate elements."""
    return [
        ExtractedElement(
            eid="btn-popular",
            type="button",
            text="인기순",
            role="tab",
            bbox=(100, 200, 80, 30),
            visible=True,
        ),
        ExtractedElement(
            eid="btn-latest",
            type="button",
            text="최신순",
            role="tab",
            bbox=(200, 200, 80, 30),
            visible=True,
        ),
        ExtractedElement(
            eid="btn-price",
            type="button",
            text="낮은가격순",
            role="tab",
            bbox=(300, 200, 80, 30),
            visible=True,
        ),
        ExtractedElement(
            eid="link-home",
            type="link",
            text="Home",
            role="link",
            bbox=(10, 10, 60, 20),
            visible=True,
        ),
        ExtractedElement(
            eid="hidden-elem",
            type="button",
            text="인기순",
            role="button",
            bbox=(100, 800, 80, 30),
            visible=False,
        ),
    ]


# ── Test: Rule Loading ───────────────────────────────


class TestRuleLoading:
    """Tests for rule loading from YAML files."""

    def test_rules_loaded_from_yaml(self, engine: RuleEngine) -> None:
        """Rules are correctly loaded from config/rules/*.yaml."""
        assert len(engine.rules) == 3

    def test_rule_fields_parsed(self, engine: RuleEngine) -> None:
        """Loaded rule has correct field values."""
        rule = next(r for r in engine.rules if r.rule_id == "sort_by_popular")
        assert rule.category == "sort"
        assert rule.intent_pattern == "인기순 정렬"
        assert rule.selector == ".sort-popular"
        assert rule.method == "click"
        assert rule.site_pattern == "*"
        assert rule.priority == 10

    def test_synonyms_loaded(self, engine: RuleEngine) -> None:
        """Synonym dictionary is populated."""
        synonyms = engine.synonyms
        assert "sort_synonyms" in synonyms
        assert "popular" in synonyms["sort_synonyms"]
        assert "인기순" in synonyms["sort_synonyms"]["popular"]

    def test_empty_rules_dir(self, tmp_path: Path) -> None:
        """Engine initialises cleanly with no rule files."""
        (tmp_path / "synonyms.yaml").write_text("{}", encoding="utf-8")
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        engine = RuleEngine(config_dir=tmp_path)
        assert len(engine.rules) == 0

    def test_missing_config_dir(self, tmp_path: Path) -> None:
        """Engine handles missing config directory gracefully."""
        engine = RuleEngine(config_dir=tmp_path / "nonexistent")
        assert len(engine.rules) == 0


# ── Test: Synonym Matching ───────────────────────────


class TestSynonymMatching:
    """Tests for synonym-based intent matching."""

    def test_korean_synonym_match(self, engine: RuleEngine, page_state: PageState) -> None:
        """Korean synonym '인기순' matches sort_by_popular rule."""
        match = engine.match("인기순 정렬", page_state)
        assert match is not None
        assert match.rule_id == "sort_by_popular"
        assert match.selector == ".sort-popular"

    def test_english_synonym_match(self, engine: RuleEngine, page_state: PageState) -> None:
        """English synonym 'popular' resolves to the same rule."""
        match = engine.match("sort by popular", page_state)
        assert match is not None
        assert match.rule_id == "sort_by_popular"

    def test_synonym_best_match(self, engine: RuleEngine, page_state: PageState) -> None:
        """'베스트' is a synonym for popular and matches."""
        match = engine.match("베스트 정렬", page_state)
        assert match is not None
        assert match.rule_id == "sort_by_popular"

    def test_no_match_for_unknown_intent(
        self, engine: RuleEngine, page_state: PageState
    ) -> None:
        """Unknown intent returns None."""
        match = engine.match("completely unrelated task xyz", page_state)
        assert match is None


# ── Test: Site Pattern Matching ──────────────────────


class TestSitePatternMatching:
    """Tests for glob-based site pattern matching."""

    def test_wildcard_matches_any_site(
        self, engine: RuleEngine, page_state: PageState
    ) -> None:
        """Site pattern '*' matches any URL."""
        match = engine.match("인기순 정렬", page_state)
        assert match is not None

    def test_specific_site_pattern_matches(self, engine: RuleEngine) -> None:
        """'*.naver.com' pattern matches shopping.naver.com."""
        state = PageState(
            url="https://shopping.naver.com/products",
            title="Naver",
        )
        match = engine.match("쿠키 팝업 닫기", state)
        assert match is not None
        assert match.rule_id == "popup_close_cookie"

    def test_site_pattern_rejects_mismatch(self, engine: RuleEngine) -> None:
        """'*.naver.com' pattern does NOT match google.com."""
        state = PageState(
            url="https://www.google.com/search",
            title="Google",
        )
        match = engine.match("쿠키 팝업 닫기", state)
        assert match is None


# ── Test: Heuristic Select ───────────────────────────


class TestHeuristicSelect:
    """Tests for heuristic_select scoring."""

    def test_selects_best_text_match(
        self, engine: RuleEngine, candidates: list[ExtractedElement]
    ) -> None:
        """Selects element whose text best matches the intent."""
        eid = engine.heuristic_select(candidates, "인기순 정렬")
        assert eid == "btn-popular"

    def test_selects_latest_for_latest_intent(
        self, engine: RuleEngine, candidates: list[ExtractedElement]
    ) -> None:
        """Selects '최신순' button for latest intent."""
        eid = engine.heuristic_select(candidates, "최신순")
        assert eid == "btn-latest"

    def test_selects_price_for_price_intent(
        self, engine: RuleEngine, candidates: list[ExtractedElement]
    ) -> None:
        """Selects price button for cheap intent."""
        eid = engine.heuristic_select(candidates, "낮은가격순")
        assert eid == "btn-price"

    def test_returns_none_for_empty_candidates(self, engine: RuleEngine) -> None:
        """Returns None when candidate list is empty."""
        result = engine.heuristic_select([], "인기순")
        assert result is None

    def test_returns_none_for_no_viable_match(self, engine: RuleEngine) -> None:
        """Returns None when no candidate meets the minimum threshold."""
        weak = [
            ExtractedElement(
                eid="div-footer",
                type="link",
                text="Copyright 2024",
                bbox=(0, 2000, 100, 20),
                visible=False,
            ),
        ]
        result = engine.heuristic_select(weak, "인기순 정렬")
        assert result is None


# ── Test: Register Rule ──────────────────────────────


class TestRegisterRule:
    """Tests for dynamic rule registration."""

    def test_register_adds_rule(self, engine: RuleEngine) -> None:
        """register_rule adds a new rule to the engine."""
        initial_count = len(engine.rules)
        new_rule = RuleDefinition(
            rule_id="filter_price_range",
            category="filter",
            intent_pattern="가격대 필터",
            selector=".price-filter",
            method="click",
            priority=15,
        )
        engine.register_rule(new_rule)
        assert len(engine.rules) == initial_count + 1

    def test_register_rule_invalid_category(self, engine: RuleEngine) -> None:
        """register_rule raises ValueError for unknown category."""
        bad_rule = RuleDefinition(
            rule_id="bad_rule",
            category="nonexistent_category",
            intent_pattern="test",
            selector="",
        )
        with pytest.raises(ValueError, match="Unknown rule category"):
            engine.register_rule(bad_rule)

    def test_register_rule_replaces_duplicate(self, engine: RuleEngine) -> None:
        """Registering a rule with existing ID replaces the old one."""
        old_count = len(engine.rules)
        replacement = RuleDefinition(
            rule_id="sort_by_popular",
            category="sort",
            intent_pattern="인기순 정렬",
            selector=".sort-popular-v2",
            method="click",
            priority=99,
        )
        engine.register_rule(replacement)
        assert len(engine.rules) == old_count
        updated = next(r for r in engine.rules if r.rule_id == "sort_by_popular")
        assert updated.selector == ".sort-popular-v2"
        assert updated.priority == 99


# ── Test: Priority Ordering ──────────────────────────


class TestPriorityOrdering:
    """Tests for priority-based rule selection."""

    def test_higher_priority_wins(self, engine: RuleEngine) -> None:
        """When multiple rules could match, higher priority wins.

        popup_close_cookie (priority=20) should be checked before
        sort_by_popular (priority=10).
        """
        state = PageState(
            url="https://shopping.naver.com/search",
            title="Naver",
        )
        # The popup rule has priority 20 and matches *.naver.com.
        match = engine.match("쿠키 팝업 닫기", state)
        assert match is not None
        assert match.rule_id == "popup_close_cookie"

    def test_priority_order_with_registered_rule(
        self, engine: RuleEngine, page_state: PageState
    ) -> None:
        """A dynamically registered rule with higher priority takes precedence."""
        high_priority = RuleDefinition(
            rule_id="sort_popular_override",
            category="sort",
            intent_pattern="인기순 정렬",
            selector=".override-selector",
            method="click",
            priority=100,
        )
        engine.register_rule(high_priority)
        match = engine.match("인기순 정렬", page_state)
        assert match is not None
        assert match.rule_id == "sort_popular_override"
        assert match.selector == ".override-selector"


# ── Test: Helper Functions ───────────────────────────


class TestHelpers:
    """Tests for internal helper functions."""

    def test_normalise_strips_and_lowercases(self) -> None:
        assert _normalise("  Hello   World  ") == "hello world"

    def test_text_similarity_identical(self) -> None:
        assert _text_similarity("hello", "hello") == 1.0

    def test_text_similarity_different(self) -> None:
        assert _text_similarity("hello", "zzzzz") < 0.3

    def test_valid_categories_frozen(self) -> None:
        """VALID_CATEGORIES cannot be modified at runtime."""
        with pytest.raises(AttributeError):
            VALID_CATEGORIES.add("new_cat")  # type: ignore[attr-defined]
