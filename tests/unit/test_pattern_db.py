"""Tests for PatternDB — SQLite-backed pattern tracking.

Covers CRUD operations, upsert semantics, promotable queries,
concurrent operations, and ID generation consistency.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from src.learning.pattern_db import PatternDB, Pattern, _generate_pattern_id


# ── Fixtures ────────────────────────────────────────


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> PatternDB:
    """Create a fresh PatternDB in a temp directory."""
    db_path = tmp_path / "test_patterns.db"
    pattern_db = PatternDB(db_path=db_path)
    await pattern_db.init_db()
    return pattern_db


# ── Pattern ID Generation ───────────────────────────


class TestPatternIdGeneration:
    """Tests for deterministic pattern_id generation."""

    def test_same_inputs_produce_same_id(self) -> None:
        """Identical inputs must yield the same pattern_id."""
        id1 = _generate_pattern_id("search", "example.com", "#btn")
        id2 = _generate_pattern_id("search", "example.com", "#btn")
        assert id1 == id2

    def test_different_inputs_produce_different_id(self) -> None:
        """Different inputs must yield different pattern_ids."""
        id1 = _generate_pattern_id("search", "example.com", "#btn")
        id2 = _generate_pattern_id("sort", "example.com", "#btn")
        assert id1 != id2

    def test_id_is_16_chars_hex(self) -> None:
        """Pattern ID should be a 16-character hex string."""
        pid = _generate_pattern_id("intent", "site", "selector")
        assert len(pid) == 16
        assert all(c in "0123456789abcdef" for c in pid)

    def test_id_consistent_across_calls(self) -> None:
        """Multiple calls with same args must be deterministic."""
        results = [
            _generate_pattern_id("click button", "naver.com", ".btn-class")
            for _ in range(100)
        ]
        assert len(set(results)) == 1


# ── Record Success ──────────────────────────────────


class TestRecordSuccess:
    """Tests for record_success upsert behaviour."""

    @pytest.mark.asyncio
    async def test_creates_new_pattern(self, db: PatternDB) -> None:
        """First success should create a new pattern with count=1."""
        pattern = await db.record_success("search", "example.com", "#q", "type")
        assert pattern.success_count == 1
        assert pattern.fail_count == 0
        assert pattern.intent == "search"
        assert pattern.site == "example.com"
        assert pattern.selector == "#q"
        assert pattern.method == "type"
        assert pattern.pattern_id != ""
        assert pattern.created != ""
        assert pattern.last_used != ""

    @pytest.mark.asyncio
    async def test_increments_existing(self, db: PatternDB) -> None:
        """Subsequent successes should increment success_count."""
        await db.record_success("search", "example.com", "#q", "type")
        await db.record_success("search", "example.com", "#q", "type")
        pattern = await db.record_success("search", "example.com", "#q", "type")
        assert pattern.success_count == 3
        assert pattern.fail_count == 0

    @pytest.mark.asyncio
    async def test_preserves_pattern_id(self, db: PatternDB) -> None:
        """Same input must always produce the same pattern_id."""
        p1 = await db.record_success("click", "naver.com", ".btn", "click")
        p2 = await db.record_success("click", "naver.com", ".btn", "click")
        assert p1.pattern_id == p2.pattern_id

    @pytest.mark.asyncio
    async def test_updates_last_used(self, db: PatternDB) -> None:
        """last_used should update on each record."""
        p1 = await db.record_success("x", "y.com", "#a", "click")
        p2 = await db.record_success("x", "y.com", "#a", "click")
        # Both should have timestamps; the second should be >= first
        assert p2.last_used >= p1.last_used


# ── Record Failure ──────────────────────────────────


class TestRecordFailure:
    """Tests for record_failure upsert behaviour."""

    @pytest.mark.asyncio
    async def test_creates_new_pattern_on_failure(self, db: PatternDB) -> None:
        """First failure should create a new pattern with fail_count=1."""
        pattern = await db.record_failure("sort", "shop.com", "#sort", "click")
        assert pattern.success_count == 0
        assert pattern.fail_count == 1

    @pytest.mark.asyncio
    async def test_increments_fail_count(self, db: PatternDB) -> None:
        """Subsequent failures should increment fail_count."""
        await db.record_failure("sort", "shop.com", "#sort", "click")
        pattern = await db.record_failure("sort", "shop.com", "#sort", "click")
        assert pattern.fail_count == 2
        assert pattern.success_count == 0

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self, db: PatternDB) -> None:
        """Both success and failure should accumulate independently."""
        await db.record_success("sort", "shop.com", "#sort", "click")
        await db.record_success("sort", "shop.com", "#sort", "click")
        await db.record_failure("sort", "shop.com", "#sort", "click")
        pattern = await db.record_success("sort", "shop.com", "#sort", "click")
        assert pattern.success_count == 3
        assert pattern.fail_count == 1


# ── Get Pattern ─────────────────────────────────────


class TestGetPattern:
    """Tests for get_pattern lookup."""

    @pytest.mark.asyncio
    async def test_returns_match(self, db: PatternDB) -> None:
        """Should return a pattern when intent and site match."""
        await db.record_success("search", "google.com", "#q", "type")
        pattern = await db.get_pattern("search", "google.com")
        assert pattern is not None
        assert pattern.intent == "search"
        assert pattern.site == "google.com"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self, db: PatternDB) -> None:
        """Should return None when no pattern exists."""
        result = await db.get_pattern("nonexistent", "nowhere.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_best_by_success_count(self, db: PatternDB) -> None:
        """When multiple selectors exist, return the one with most successes."""
        await db.record_success("search", "google.com", "#q1", "type")
        for _ in range(5):
            await db.record_success("search", "google.com", "#q2", "type")

        pattern = await db.get_pattern("search", "google.com")
        assert pattern is not None
        assert pattern.selector == "#q2"


# ── Get Promotable ──────────────────────────────────


class TestGetPromotable:
    """Tests for get_promotable threshold queries."""

    @pytest.mark.asyncio
    async def test_returns_patterns_above_threshold(self, db: PatternDB) -> None:
        """Patterns meeting both min_success and min_ratio should be returned."""
        for _ in range(5):
            await db.record_success("sort", "shop.com", "#sort", "click")
        promotable = await db.get_promotable(min_success=3, min_ratio=0.8)
        assert len(promotable) == 1
        assert promotable[0].intent == "sort"

    @pytest.mark.asyncio
    async def test_excludes_below_min_success(self, db: PatternDB) -> None:
        """Patterns with too few successes should be excluded."""
        await db.record_success("sort", "shop.com", "#sort", "click")
        promotable = await db.get_promotable(min_success=3, min_ratio=0.5)
        assert len(promotable) == 0

    @pytest.mark.asyncio
    async def test_excludes_below_min_ratio(self, db: PatternDB) -> None:
        """Patterns with low success ratio should be excluded."""
        for _ in range(3):
            await db.record_success("sort", "shop.com", "#sort", "click")
        for _ in range(10):
            await db.record_failure("sort", "shop.com", "#sort", "click")
        promotable = await db.get_promotable(min_success=3, min_ratio=0.8)
        assert len(promotable) == 0

    @pytest.mark.asyncio
    async def test_multiple_promotable(self, db: PatternDB) -> None:
        """Multiple patterns can be promotable simultaneously."""
        for _ in range(5):
            await db.record_success("sort", "shop.com", "#sort", "click")
        for _ in range(4):
            await db.record_success("search", "google.com", "#q", "type")

        promotable = await db.get_promotable(min_success=3, min_ratio=0.8)
        assert len(promotable) == 2

    @pytest.mark.asyncio
    async def test_custom_thresholds(self, db: PatternDB) -> None:
        """Custom thresholds should be respected."""
        for _ in range(2):
            await db.record_success("sort", "shop.com", "#sort", "click")

        # Should find with min_success=2
        promotable = await db.get_promotable(min_success=2, min_ratio=0.5)
        assert len(promotable) == 1

        # Should not find with min_success=5
        promotable = await db.get_promotable(min_success=5, min_ratio=0.5)
        assert len(promotable) == 0


# ── List Patterns ───────────────────────────────────


class TestListPatterns:
    """Tests for list_patterns with optional site filter."""

    @pytest.mark.asyncio
    async def test_list_all(self, db: PatternDB) -> None:
        """Should list all patterns when no site filter is given."""
        await db.record_success("sort", "shop.com", "#sort", "click")
        await db.record_success("search", "google.com", "#q", "type")
        patterns = await db.list_patterns()
        assert len(patterns) == 2

    @pytest.mark.asyncio
    async def test_filter_by_site(self, db: PatternDB) -> None:
        """Should only return patterns for the given site."""
        await db.record_success("sort", "shop.com", "#sort", "click")
        await db.record_success("search", "google.com", "#q", "type")
        patterns = await db.list_patterns(site="shop.com")
        assert len(patterns) == 1
        assert patterns[0].site == "shop.com"

    @pytest.mark.asyncio
    async def test_empty_list(self, db: PatternDB) -> None:
        """Should return empty list when no patterns exist."""
        patterns = await db.list_patterns()
        assert patterns == []

    @pytest.mark.asyncio
    async def test_filter_no_match(self, db: PatternDB) -> None:
        """Should return empty list when site filter matches nothing."""
        await db.record_success("sort", "shop.com", "#sort", "click")
        patterns = await db.list_patterns(site="unknown.com")
        assert patterns == []


# ── Delete Pattern ──────────────────────────────────


class TestDeletePattern:
    """Tests for delete_pattern."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, db: PatternDB) -> None:
        """Should delete an existing pattern and return True."""
        pattern = await db.record_success("sort", "shop.com", "#sort", "click")
        result = await db.delete_pattern(pattern.pattern_id)
        assert result is True

        # Verify it's gone
        remaining = await db.list_patterns()
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, db: PatternDB) -> None:
        """Should return False when pattern does not exist."""
        result = await db.delete_pattern("nonexistent_id")
        assert result is False


# ── Concurrent Operations ──────────────────────────


class TestConcurrent:
    """Tests for concurrent success/failure recording."""

    @pytest.mark.asyncio
    async def test_concurrent_successes(self, db: PatternDB) -> None:
        """Multiple concurrent successes should all be counted."""
        tasks = [
            db.record_success("search", "example.com", "#q", "type")
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks)
        # The last result should have all successes counted
        final = await db.get_pattern("search", "example.com")
        assert final is not None
        assert final.success_count == 10

    @pytest.mark.asyncio
    async def test_concurrent_mixed(self, db: PatternDB) -> None:
        """Concurrent mix of success and failure should be consistent."""
        success_tasks = [
            db.record_success("click", "site.com", "#btn", "click")
            for _ in range(5)
        ]
        fail_tasks = [
            db.record_failure("click", "site.com", "#btn", "click")
            for _ in range(3)
        ]
        await asyncio.gather(*success_tasks, *fail_tasks)

        final = await db.get_pattern("click", "site.com")
        assert final is not None
        assert final.success_count + final.fail_count == 8


# ── Init & Close ────────────────────────────────────


class TestInitAndClose:
    """Tests for initialization and close."""

    @pytest.mark.asyncio
    async def test_auto_init(self, tmp_path: Path) -> None:
        """DB should auto-initialise on first operation."""
        db_path = tmp_path / "auto_init.db"
        db = PatternDB(db_path=db_path)
        # Don't call init_db — should auto-init via _ensure_init
        pattern = await db.record_success("test", "test.com", "#t", "click")
        assert pattern.success_count == 1

    @pytest.mark.asyncio
    async def test_close_is_safe(self, db: PatternDB) -> None:
        """close() should be callable without error."""
        await db.close()

    @pytest.mark.asyncio
    async def test_init_creates_directory(self, tmp_path: Path) -> None:
        """init_db should create parent directory if missing."""
        db_path = tmp_path / "subdir" / "nested" / "patterns.db"
        db = PatternDB(db_path=db_path)
        await db.init_db()
        assert db_path.parent.exists()


# ── Pattern Dataclass ───────────────────────────────


class TestPatternDataclass:
    """Tests for the Pattern dataclass defaults."""

    def test_default_values(self) -> None:
        """Pattern should have sensible defaults."""
        p = Pattern(
            pattern_id="test",
            intent="search",
            site="example.com",
            selector="#q",
            method="type",
        )
        assert p.success_count == 0
        assert p.fail_count == 0
        assert p.last_used == ""
        assert p.created == ""
        assert p.metadata == {}

    def test_metadata_isolation(self) -> None:
        """Default metadata should not be shared between instances."""
        p1 = Pattern(pattern_id="a", intent="x", site="y", selector="z", method="click")
        p2 = Pattern(pattern_id="b", intent="x", site="y", selector="z", method="click")
        p1.metadata["key"] = "value"
        assert "key" not in p2.metadata
