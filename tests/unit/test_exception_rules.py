"""Unit tests for Phase 5 exception detection rules and extended synonyms.

Tests cover:
- YAML rule file loading and validation
- Required field presence and value ranges
- Category validity
- Total rule count
- Synonym dictionary loading via RuleEngine
- Korean synonym matching for new groups
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.core.rule_engine import VALID_CATEGORIES, RuleEngine
from src.core.types import PageState

# ── Constants ────────────────────────────────────────

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_RULES_DIR = _CONFIG_DIR / "rules"
_SYNONYMS_FILE = _CONFIG_DIR / "synonyms.yaml"

# Rule files created in Phase 5.
_PHASE5_RULE_FILES = [
    "popup_common.yaml",
    "error_detection.yaml",
    "login_detection.yaml",
    "pagination.yaml",
    "filter_sort.yaml",
]

# Required fields for every rule.
_REQUIRED_FIELDS = {"name", "category"}


# ── Helpers ──────────────────────────────────────────


def _load_rules_from_file(filename: str) -> list[dict]:
    """Load all rule dicts from a YAML file."""
    path = _RULES_DIR / filename
    assert path.exists(), f"Rule file not found: {path}"

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Multi-rule format.
    if "rules" in data and isinstance(data["rules"], list):
        return data["rules"]
    # Single-rule format.
    if "rule" in data:
        return [data["rule"]]
    return [data]


def _load_all_rules() -> list[dict]:
    """Load all rules from all YAML files in config/rules/."""
    all_rules = []
    for path in sorted(_RULES_DIR.glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "rules" in data and isinstance(data["rules"], list):
            all_rules.extend(data["rules"])
        elif "rule" in data:
            all_rules.append(data["rule"])
        else:
            all_rules.append(data)
    return all_rules


# ── Fixtures ─────────────────────────────────────────


@pytest.fixture(scope="module")
def all_rules() -> list[dict]:
    """All rules from all YAML files."""
    return _load_all_rules()


@pytest.fixture(scope="module")
def engine() -> RuleEngine:
    """RuleEngine loaded from the real config directory."""
    return RuleEngine(config_dir=_CONFIG_DIR)


@pytest.fixture()
def generic_page_state() -> PageState:
    """A generic page state for testing rule matching."""
    return PageState(
        url="https://www.example.com/products",
        title="Products",
    )


# ── Test: Rule File Validity ─────────────────────────


class TestRuleFileValidity:
    """Each Phase 5 rule YAML file is valid and loadable."""

    @pytest.mark.parametrize("filename", _PHASE5_RULE_FILES)
    def test_rule_file_exists(self, filename: str) -> None:
        """Rule file exists in config/rules/."""
        path = _RULES_DIR / filename
        assert path.exists(), f"Missing rule file: {path}"

    @pytest.mark.parametrize("filename", _PHASE5_RULE_FILES)
    def test_rule_file_is_valid_yaml(self, filename: str) -> None:
        """Rule file can be parsed as valid YAML."""
        rules = _load_rules_from_file(filename)
        assert len(rules) > 0, f"No rules found in {filename}"

    @pytest.mark.parametrize("filename", _PHASE5_RULE_FILES)
    def test_rules_have_required_fields(self, filename: str) -> None:
        """Every rule in the file has name and category fields."""
        rules = _load_rules_from_file(filename)
        for i, rule in enumerate(rules):
            for field in _REQUIRED_FIELDS:
                assert field in rule, (
                    f"Rule #{i} in {filename} missing required field '{field}': "
                    f"keys={list(rule.keys())}"
                )

    @pytest.mark.parametrize("filename", _PHASE5_RULE_FILES)
    def test_rules_have_trigger(self, filename: str) -> None:
        """Every rule has a trigger with intent."""
        rules = _load_rules_from_file(filename)
        for i, rule in enumerate(rules):
            trigger = rule.get("trigger", {})
            assert "intent" in trigger, (
                f"Rule #{i} '{rule.get('name')}' in {filename} "
                f"missing trigger.intent"
            )

    @pytest.mark.parametrize("filename", _PHASE5_RULE_FILES)
    def test_rules_have_selector(self, filename: str) -> None:
        """Every rule has a non-empty selector."""
        rules = _load_rules_from_file(filename)
        for i, rule in enumerate(rules):
            selector = rule.get("selector", "")
            assert selector, (
                f"Rule #{i} '{rule.get('name')}' in {filename} "
                f"has empty selector"
            )


# ── Test: Category Validity ──────────────────────────


class TestCategoryValidity:
    """All rule categories are from VALID_CATEGORIES."""

    @pytest.mark.parametrize("filename", _PHASE5_RULE_FILES)
    def test_categories_are_valid(self, filename: str) -> None:
        rules = _load_rules_from_file(filename)
        for i, rule in enumerate(rules):
            category = rule.get("category", "")
            assert category in VALID_CATEGORIES, (
                f"Rule #{i} '{rule.get('name')}' in {filename} "
                f"has invalid category '{category}'. "
                f"Valid: {sorted(VALID_CATEGORIES)}"
            )


# ── Test: Priority Range ─────────────────────────────


class TestPriorityRange:
    """Rule priorities are within the reasonable range 1-100."""

    @pytest.mark.parametrize("filename", _PHASE5_RULE_FILES)
    def test_priority_in_range(self, filename: str) -> None:
        rules = _load_rules_from_file(filename)
        for i, rule in enumerate(rules):
            priority = rule.get("priority", 0)
            assert 0 <= priority <= 100, (
                f"Rule #{i} '{rule.get('name')}' in {filename} "
                f"has out-of-range priority: {priority}"
            )


# ── Test: Total Rule Count ───────────────────────────


class TestTotalRuleCount:
    """There are at least 60 rules across all files."""

    def test_total_rules_at_least_60(self, all_rules: list[dict]) -> None:
        assert len(all_rules) >= 60, (
            f"Expected >= 60 rules total, found {len(all_rules)}"
        )

    def test_popup_rules_count(self) -> None:
        rules = _load_rules_from_file("popup_common.yaml")
        assert len(rules) >= 15, f"Expected >= 15 popup rules, found {len(rules)}"

    def test_error_rules_count(self) -> None:
        rules = _load_rules_from_file("error_detection.yaml")
        assert len(rules) >= 10, f"Expected >= 10 error rules, found {len(rules)}"

    def test_login_rules_count(self) -> None:
        rules = _load_rules_from_file("login_detection.yaml")
        assert len(rules) >= 9, f"Expected >= 9 login rules, found {len(rules)}"

    def test_pagination_rules_count(self) -> None:
        rules = _load_rules_from_file("pagination.yaml")
        assert len(rules) >= 10, f"Expected >= 10 pagination rules, found {len(rules)}"

    def test_filter_sort_rules_count(self) -> None:
        rules = _load_rules_from_file("filter_sort.yaml")
        assert len(rules) >= 10, f"Expected >= 10 filter/sort rules, found {len(rules)}"


# ── Test: Category-Specific Checks ──────────────────


class TestCategorySpecificChecks:
    """Rules in each category have appropriate properties."""

    def test_popup_rules_have_close_selectors(self) -> None:
        """Popup rules should have selectors with close/dismiss/confirm patterns."""
        rules = _load_rules_from_file("popup_common.yaml")
        close_keywords = {
            "close", "dismiss", "accept", "agree", "skip", "deny",
            "no-thanks", "confirm", "enter", "yes",
        }
        for rule in rules:
            selector = rule.get("selector", "").lower()
            has_close = any(kw in selector for kw in close_keywords)
            assert has_close, (
                f"Popup rule '{rule.get('name')}' selector lacks close-related patterns: "
                f"{selector[:80]}"
            )

    def test_error_rules_have_detection_intents(self) -> None:
        """Error rules should have detection-related intents."""
        rules = _load_rules_from_file("error_detection.yaml")
        detection_keywords = {"감지", "detect", "error", "오류"}
        for rule in rules:
            intent = rule.get("trigger", {}).get("intent", "").lower()
            has_detect = any(kw in intent for kw in detection_keywords)
            assert has_detect, (
                f"Error rule '{rule.get('name')}' intent lacks detection keywords: "
                f"{intent}"
            )

    def test_login_rules_have_auth_related_selectors(self) -> None:
        """Login rules should reference auth/login/captcha patterns."""
        rules = _load_rules_from_file("login_detection.yaml")
        auth_keywords = {
            "login", "signin", "password", "captcha", "sitekey",
            "otp", "verification", "one-time-code",
            "account", "email", "provider", "expired", "locked",
        }
        for rule in rules:
            selector = rule.get("selector", "").lower()
            has_auth = any(kw in selector for kw in auth_keywords)
            assert has_auth, (
                f"Login rule '{rule.get('name')}' selector lacks auth patterns: "
                f"{selector[:80]}"
            )

    def test_pagination_rules_have_nav_selectors(self) -> None:
        """Pagination rules should reference navigation patterns."""
        rules = _load_rules_from_file("pagination.yaml")
        nav_keywords = {
            "next", "prev", "page", "more", "load", "scroll",
            "pagination", "first", "last", "infinite",
            "per_page", "pagesize", "보기", "전체",
        }
        for rule in rules:
            selector = rule.get("selector", "").lower()
            has_nav = any(kw in selector for kw in nav_keywords)
            assert has_nav, (
                f"Pagination rule '{rule.get('name')}' selector lacks nav patterns: "
                f"{selector[:80]}"
            )


# ── Test: RuleEngine Loading ─────────────────────────


class TestRuleEngineLoading:
    """RuleEngine correctly loads all Phase 5 rules and synonyms."""

    def test_engine_loads_all_rules(self, engine: RuleEngine) -> None:
        """RuleEngine loads at least 55 rules from config/rules/."""
        assert len(engine.rules) >= 55, (
            f"RuleEngine loaded {len(engine.rules)} rules, expected >= 55"
        )

    def test_engine_loads_synonyms(self, engine: RuleEngine) -> None:
        """RuleEngine loads the extended synonyms."""
        synonyms = engine.synonyms
        assert "sort_synonyms" in synonyms
        assert "filter_synonyms" in synonyms
        assert "popup_close_synonyms" in synonyms
        assert "pagination_synonyms" in synonyms
        assert "error_synonyms" in synonyms
        assert "auth_synonyms" in synonyms

    def test_engine_has_popup_rules(self, engine: RuleEngine) -> None:
        popup_rules = [r for r in engine.rules if r.category == "popup"]
        assert len(popup_rules) >= 15

    def test_engine_has_error_rules(self, engine: RuleEngine) -> None:
        error_rules = [r for r in engine.rules if r.category == "error"]
        assert len(error_rules) >= 10

    def test_engine_has_login_rules(self, engine: RuleEngine) -> None:
        login_rules = [r for r in engine.rules if r.category == "login"]
        assert len(login_rules) >= 9

    def test_engine_has_pagination_rules(self, engine: RuleEngine) -> None:
        pagination_rules = [r for r in engine.rules if r.category == "pagination"]
        assert len(pagination_rules) >= 10

    def test_engine_has_filter_rules(self, engine: RuleEngine) -> None:
        filter_rules = [r for r in engine.rules if r.category == "filter"]
        assert len(filter_rules) >= 5

    def test_engine_has_sort_rules(self, engine: RuleEngine) -> None:
        sort_rules = [r for r in engine.rules if r.category == "sort"]
        assert len(sort_rules) >= 5


# ── Test: Synonym Matching ───────────────────────────


class TestExtendedSynonymMatching:
    """Extended synonyms correctly resolve through the RuleEngine."""

    def test_korean_popup_close_synonym(self, engine: RuleEngine) -> None:
        """'닫기' is in popup_close_synonyms.close_actions group."""
        synonyms = engine.synonyms
        close_actions = synonyms.get("popup_close_synonyms", {}).get("close_actions", [])
        assert "닫기" in close_actions

    def test_korean_pagination_synonym(self, engine: RuleEngine) -> None:
        """'더보기' is in pagination_synonyms.more group."""
        synonyms = engine.synonyms
        more_terms = synonyms.get("pagination_synonyms", {}).get("more", [])
        assert "더보기" in more_terms

    def test_korean_error_synonym(self, engine: RuleEngine) -> None:
        """'오류' is in error_synonyms.error group."""
        synonyms = engine.synonyms
        error_terms = synonyms.get("error_synonyms", {}).get("error", [])
        assert "오류" in error_terms

    def test_korean_auth_synonym(self, engine: RuleEngine) -> None:
        """'로그인' is in auth_synonyms.login group."""
        synonyms = engine.synonyms
        login_terms = synonyms.get("auth_synonyms", {}).get("login", [])
        assert "로그인" in login_terms

    def test_english_filter_synonym(self, engine: RuleEngine) -> None:
        """'refine' is in filter_synonyms.filter_general group."""
        synonyms = engine.synonyms
        filter_terms = synonyms.get("filter_synonyms", {}).get("filter_general", [])
        assert "refine" in filter_terms

    def test_pagination_match_load_more(
        self, engine: RuleEngine, generic_page_state: PageState
    ) -> None:
        """Intent '더보기 버튼 클릭' matches a pagination rule."""
        match = engine.match("더보기 버튼 클릭", generic_page_state)
        assert match is not None
        assert "pagination" in match.rule_id or "more" in match.rule_id

    def test_popup_match_cookie(
        self, engine: RuleEngine, generic_page_state: PageState
    ) -> None:
        """Intent '쿠키 동의 수락' matches a popup rule."""
        match = engine.match("쿠키 동의 수락", generic_page_state)
        assert match is not None


# ── Test: Synonyms YAML Integrity ────────────────────


class TestSynonymsYamlIntegrity:
    """The synonyms.yaml file has the expected structure and content."""

    def test_synonyms_file_exists(self) -> None:
        assert _SYNONYMS_FILE.exists()

    def test_synonyms_file_valid_yaml(self) -> None:
        with open(_SYNONYMS_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)

    def test_synonyms_has_all_groups(self) -> None:
        with open(_SYNONYMS_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        expected_groups = {
            "sort_synonyms",
            "filter_synonyms",
            "popup_close_synonyms",
            "pagination_synonyms",
            "error_synonyms",
            "auth_synonyms",
        }
        for group in expected_groups:
            assert group in data, f"Missing synonym group: {group}"

    def test_each_group_has_entries(self) -> None:
        with open(_SYNONYMS_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for group_name, group_dict in data.items():
            assert isinstance(group_dict, dict), (
                f"Group '{group_name}' should be a dict"
            )
            assert len(group_dict) > 0, (
                f"Group '{group_name}' is empty"
            )
            for canonical, terms in group_dict.items():
                assert isinstance(terms, list), (
                    f"Synonyms for '{group_name}.{canonical}' should be a list"
                )
                assert len(terms) > 0, (
                    f"No synonyms for '{group_name}.{canonical}'"
                )
