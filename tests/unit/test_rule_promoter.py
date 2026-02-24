"""Tests for RulePromoter — promotes proven patterns to Rule Engine rules.

Covers check_and_promote, promote_pattern, category inference,
record_step_result, and rule registration.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.types import RuleDefinition, StepResult
from src.learning.pattern_db import Pattern, PatternDB
from src.learning.rule_promoter import RulePromoter, _infer_category


# ── Fixtures ────────────────────────────────────────


def _make_pattern(
    intent: str = "search",
    site: str = "example.com",
    selector: str = "#q",
    method: str = "click",
    success_count: int = 5,
    fail_count: int = 0,
    pattern_id: str = "abc123",
) -> Pattern:
    """Helper to create a Pattern with sensible defaults."""
    return Pattern(
        pattern_id=pattern_id,
        intent=intent,
        site=site,
        selector=selector,
        method=method,
        success_count=success_count,
        fail_count=fail_count,
        last_used="2024-01-01T00:00:00",
        created="2024-01-01T00:00:00",
    )


@pytest.fixture
def mock_pattern_db() -> MagicMock:
    """Create a mock PatternDB."""
    db = MagicMock(spec=PatternDB)
    db.get_promotable = AsyncMock(return_value=[])
    db.record_success = AsyncMock()
    db.record_failure = AsyncMock()
    # Canary gate support: default to passing canary checks
    db.get_success_rate = AsyncMock(return_value=(10, 0, 1.0))
    db.get_baseline_rate = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mock_rule_engine() -> MagicMock:
    """Create a mock IRuleEngine."""
    engine = MagicMock()
    engine.register_rule = MagicMock()
    return engine


@pytest.fixture
def promoter(mock_pattern_db: MagicMock, mock_rule_engine: MagicMock) -> RulePromoter:
    """Create a RulePromoter with mock dependencies."""
    return RulePromoter(
        pattern_db=mock_pattern_db,
        rule_engine=mock_rule_engine,
        min_success=3,
        min_ratio=0.8,
    )


# ── Category Inference ──────────────────────────────


class TestCategoryInference:
    """Tests for _infer_category function."""

    def test_sort_korean(self) -> None:
        assert _infer_category("인기순 정렬", "click") == "sort"

    def test_sort_english(self) -> None:
        assert _infer_category("sort by popularity", "click") == "sort"

    def test_popup_korean(self) -> None:
        assert _infer_category("팝업 닫기", "click") == "popup"

    def test_popup_english(self) -> None:
        assert _infer_category("close popup dialog", "click") == "popup"

    def test_popup_close(self) -> None:
        assert _infer_category("close the overlay", "click") == "popup"

    def test_search_korean(self) -> None:
        assert _infer_category("검색어 입력", "type") == "search"

    def test_search_english(self) -> None:
        assert _infer_category("search for laptops", "type") == "search"

    def test_filter_korean(self) -> None:
        assert _infer_category("필터 적용", "click") == "filter"

    def test_filter_english(self) -> None:
        assert _infer_category("filter by price", "click") == "filter"

    def test_pagination_korean(self) -> None:
        assert _infer_category("다음 페이지", "click") == "pagination"

    def test_pagination_english(self) -> None:
        assert _infer_category("go to next page", "click") == "pagination"

    def test_pagination_next(self) -> None:
        assert _infer_category("click next", "click") == "pagination"

    def test_login(self) -> None:
        assert _infer_category("login to account", "click") == "login"

    def test_error(self) -> None:
        assert _infer_category("handle error message", "click") == "error"

    def test_default_fallback(self) -> None:
        """Unknown intents should default to 'search'."""
        assert _infer_category("do something unknown", "click") == "search"

    def test_type_method_fallback(self) -> None:
        """When method is 'type' and no keyword matches, default to 'search'."""
        assert _infer_category("enter some text", "type") == "search"


# ── Check and Promote ──────────────────────────────


class TestCheckAndPromote:
    """Tests for check_and_promote method."""

    @pytest.mark.asyncio
    async def test_with_promotable_patterns(
        self, promoter: RulePromoter, mock_pattern_db: MagicMock, mock_rule_engine: MagicMock
    ) -> None:
        """Should promote patterns that meet thresholds."""
        pattern = _make_pattern(success_count=5)
        mock_pattern_db.get_promotable.return_value = [pattern]

        promoted = await promoter.check_and_promote()

        assert len(promoted) == 1
        assert promoted[0].intent_pattern == "search"
        mock_rule_engine.register_rule.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_no_promotable(
        self, promoter: RulePromoter, mock_pattern_db: MagicMock, mock_rule_engine: MagicMock
    ) -> None:
        """Should return empty list when no patterns meet thresholds."""
        mock_pattern_db.get_promotable.return_value = []

        promoted = await promoter.check_and_promote()

        assert len(promoted) == 0
        mock_rule_engine.register_rule.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_already_promoted(
        self, promoter: RulePromoter, mock_pattern_db: MagicMock, mock_rule_engine: MagicMock
    ) -> None:
        """Should not re-promote patterns already promoted in this session."""
        pattern = _make_pattern(pattern_id="already_done")
        mock_pattern_db.get_promotable.return_value = [pattern]

        # First call promotes
        promoted1 = await promoter.check_and_promote()
        assert len(promoted1) == 1

        # Second call should skip the same pattern
        promoted2 = await promoter.check_and_promote()
        assert len(promoted2) == 0

    @pytest.mark.asyncio
    async def test_multiple_patterns(
        self, promoter: RulePromoter, mock_pattern_db: MagicMock, mock_rule_engine: MagicMock
    ) -> None:
        """Should promote multiple patterns at once."""
        patterns = [
            _make_pattern(intent="sort", pattern_id="p1"),
            _make_pattern(intent="search", pattern_id="p2"),
            _make_pattern(intent="filter", pattern_id="p3"),
        ]
        mock_pattern_db.get_promotable.return_value = patterns

        promoted = await promoter.check_and_promote()

        assert len(promoted) == 3
        assert mock_rule_engine.register_rule.call_count == 3

    @pytest.mark.asyncio
    async def test_passes_thresholds_to_db(
        self, mock_pattern_db: MagicMock, mock_rule_engine: MagicMock
    ) -> None:
        """Should pass custom thresholds to PatternDB."""
        promoter = RulePromoter(
            pattern_db=mock_pattern_db,
            rule_engine=mock_rule_engine,
            min_success=10,
            min_ratio=0.95,
        )
        mock_pattern_db.get_promotable.return_value = []

        await promoter.check_and_promote()

        mock_pattern_db.get_promotable.assert_called_once_with(
            min_success=10,
            min_ratio=0.95,
        )


# ── Promote Pattern ────────────────────────────────


class TestPromotePattern:
    """Tests for promote_pattern method."""

    @pytest.mark.asyncio
    async def test_generates_correct_rule(
        self, promoter: RulePromoter, mock_rule_engine: MagicMock
    ) -> None:
        """Should create a RuleDefinition with correct fields."""
        pattern = _make_pattern(
            intent="인기순 정렬",
            site="shopping.naver.com",
            selector="#sort-popular",
            method="click",
        )

        rule = await promoter.promote_pattern(pattern)

        assert isinstance(rule, RuleDefinition)
        assert rule.intent_pattern == "인기순 정렬"
        assert rule.selector == "#sort-popular"
        assert rule.method == "click"
        assert rule.site_pattern == "shopping.naver.com"
        assert rule.category == "sort"
        assert rule.priority == 10
        assert rule.rule_id.startswith("promoted_")

    @pytest.mark.asyncio
    async def test_registers_with_engine(
        self, promoter: RulePromoter, mock_rule_engine: MagicMock
    ) -> None:
        """Should register the rule with the rule engine."""
        pattern = _make_pattern()
        await promoter.promote_pattern(pattern)
        mock_rule_engine.register_rule.assert_called_once()

        registered_rule = mock_rule_engine.register_rule.call_args[0][0]
        assert isinstance(registered_rule, RuleDefinition)

    @pytest.mark.asyncio
    async def test_rule_id_is_deterministic(
        self, promoter: RulePromoter, mock_rule_engine: MagicMock
    ) -> None:
        """Same pattern should produce the same rule_id."""
        p1 = _make_pattern(intent="sort", site="x.com", selector="#s", method="click")
        p2 = _make_pattern(intent="sort", site="x.com", selector="#s", method="click")

        # Reset promoted_ids for second call
        promoter._promoted_ids.clear()

        r1 = await promoter.promote_pattern(p1)
        promoter._promoted_ids.clear()
        r2 = await promoter.promote_pattern(p2)

        assert r1.rule_id == r2.rule_id


# ── Record Step Result ──────────────────────────────


class TestRecordStepResult:
    """Tests for record_step_result method."""

    @pytest.mark.asyncio
    async def test_success_path(
        self, promoter: RulePromoter, mock_pattern_db: MagicMock
    ) -> None:
        """Successful step should record success in PatternDB."""
        result = StepResult(step_id="s1", success=True, method="R")

        await promoter.record_step_result(
            result, intent="search", site="google.com", selector="#q", method="type"
        )

        mock_pattern_db.record_success.assert_called_once_with(
            "search", "google.com", "#q", "type"
        )
        mock_pattern_db.record_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_path(
        self, promoter: RulePromoter, mock_pattern_db: MagicMock
    ) -> None:
        """Failed step should record failure in PatternDB."""
        result = StepResult(step_id="s1", success=False, method="R")

        await promoter.record_step_result(
            result, intent="sort", site="shop.com", selector="#sort", method="click"
        )

        mock_pattern_db.record_failure.assert_called_once_with(
            "sort", "shop.com", "#sort", "click"
        )
        mock_pattern_db.record_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_results(
        self, promoter: RulePromoter, mock_pattern_db: MagicMock
    ) -> None:
        """Multiple results should be recorded independently."""
        success = StepResult(step_id="s1", success=True, method="R")
        failure = StepResult(step_id="s2", success=False, method="L1")

        await promoter.record_step_result(
            success, intent="a", site="b.com", selector="#c", method="click"
        )
        await promoter.record_step_result(
            failure, intent="d", site="e.com", selector="#f", method="type"
        )

        assert mock_pattern_db.record_success.call_count == 1
        assert mock_pattern_db.record_failure.call_count == 1
