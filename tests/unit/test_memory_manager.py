"""Unit tests for the 4-layer Memory Manager — ``src.learning.memory_manager``."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from src.core.types import RuleDefinition
from src.learning.memory_manager import MemoryManager, create_memory_manager

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture()
def mgr(tmp_path: Path) -> MemoryManager:
    """Create a MemoryManager rooted in a temporary directory."""
    return MemoryManager(data_dir=tmp_path)


@pytest.fixture()
def sample_rule() -> RuleDefinition:
    """A sample rule for policy tests."""
    return RuleDefinition(
        rule_id="sort_popular",
        category="sort",
        intent_pattern="인기순 정렬",
        selector=".sort-popular",
        method="click",
        arguments=["arg1"],
        site_pattern="*.naver.com",
        priority=10,
    )


@pytest.fixture()
def sample_rule_b() -> RuleDefinition:
    """A second sample rule for policy tests."""
    return RuleDefinition(
        rule_id="sort_latest",
        category="sort",
        intent_pattern="최신순 정렬",
        selector=".sort-latest",
        method="click",
        site_pattern="*.naver.com",
        priority=5,
    )


# ── Test: Working Memory (Layer 1) ──────────────────


class TestWorkingMemory:
    """Tests for Layer 1 — ephemeral working memory."""

    def test_set_and_get(self, mgr: MemoryManager) -> None:
        """set_working / get_working round-trip."""
        mgr.set_working("url", "https://example.com")
        assert mgr.get_working("url") == "https://example.com"

    def test_get_missing_key_returns_none(self, mgr: MemoryManager) -> None:
        """Missing keys return None instead of raising."""
        assert mgr.get_working("nonexistent") is None

    def test_overwrite_value(self, mgr: MemoryManager) -> None:
        """Setting the same key again overwrites the value."""
        mgr.set_working("counter", 1)
        mgr.set_working("counter", 2)
        assert mgr.get_working("counter") == 2

    def test_clear_working(self, mgr: MemoryManager) -> None:
        """clear_working empties all stored keys."""
        mgr.set_working("a", 1)
        mgr.set_working("b", 2)
        mgr.clear_working()
        assert mgr.get_working("a") is None
        assert mgr.get_working("b") is None

    def test_stores_complex_types(self, mgr: MemoryManager) -> None:
        """Working memory handles dicts, lists, and nested structures."""
        data = {"nested": [1, 2, {"deep": True}]}
        mgr.set_working("complex", data)
        assert mgr.get_working("complex") == data

    def test_none_value_stored_explicitly(self, mgr: MemoryManager) -> None:
        """Storing None explicitly is distinguishable from missing key."""
        mgr.set_working("key", None)
        # The key exists with value None — get_working returns None.
        # We verify via the internal dict to ensure it was actually stored.
        assert "key" in mgr._working


# ── Test: Episode Memory (Layer 2) ──────────────────


class TestEpisodeMemory:
    """Tests for Layer 2 — per-task JSON episode storage."""

    async def test_save_and_load(self, mgr: MemoryManager) -> None:
        """save_episode / load_episode round-trip."""
        data = {"status": "running", "steps": [1, 2, 3]}
        await mgr.save_episode("task-001", data)
        loaded = await mgr.load_episode("task-001")
        assert loaded == data

    async def test_load_nonexistent_returns_none(self, mgr: MemoryManager) -> None:
        """Loading a non-existent episode returns None."""
        result = await mgr.load_episode("no-such-task")
        assert result is None

    async def test_list_episodes_empty(self, mgr: MemoryManager) -> None:
        """list_episodes returns empty list when no episodes exist."""
        episodes = await mgr.list_episodes()
        assert episodes == []

    async def test_list_episodes_multiple(self, mgr: MemoryManager) -> None:
        """list_episodes returns sorted task IDs."""
        await mgr.save_episode("beta", {"x": 1})
        await mgr.save_episode("alpha", {"y": 2})
        await mgr.save_episode("gamma", {"z": 3})
        episodes = await mgr.list_episodes()
        assert episodes == ["alpha", "beta", "gamma"]

    async def test_delete_episode(self, mgr: MemoryManager) -> None:
        """delete_episode removes the file and returns True."""
        await mgr.save_episode("task-del", {"data": True})
        result = await mgr.delete_episode("task-del")
        assert result is True
        assert await mgr.load_episode("task-del") is None

    async def test_delete_nonexistent_returns_false(self, mgr: MemoryManager) -> None:
        """delete_episode returns False for a missing episode."""
        result = await mgr.delete_episode("ghost")
        assert result is False

    async def test_overwrite_episode(self, mgr: MemoryManager) -> None:
        """Saving the same task_id overwrites previous data."""
        await mgr.save_episode("task-ow", {"v": 1})
        await mgr.save_episode("task-ow", {"v": 2})
        loaded = await mgr.load_episode("task-ow")
        assert loaded == {"v": 2}

    async def test_unicode_episode_data(self, mgr: MemoryManager) -> None:
        """Episode data preserves Unicode (Korean text)."""
        data = {"intent": "인기순 정렬", "site": "네이버 쇼핑"}
        await mgr.save_episode("task-kr", data)
        loaded = await mgr.load_episode("task-kr")
        assert loaded == data


# ── Test: Policy Memory (Layer 3) ────────────────────


class TestPolicyMemory:
    """Tests for Layer 3 — persistent SQLite policy store."""

    async def test_save_and_query(
        self, mgr: MemoryManager, sample_rule: RuleDefinition
    ) -> None:
        """save_policy / query_policy round-trip."""
        await mgr.save_policy(sample_rule, success_count=5)
        match = await mgr.query_policy("인기순 정렬", "*.naver.com")
        assert match is not None
        assert match.rule_id == "sort_popular"
        assert match.selector == ".sort-popular"
        assert match.method == "click"
        assert match.arguments == ["arg1"]

    async def test_query_no_match(self, mgr: MemoryManager) -> None:
        """query_policy returns None when no matching entry exists."""
        match = await mgr.query_policy("unknown intent", "unknown.site")
        assert match is None

    async def test_upsert_updates_existing(
        self, mgr: MemoryManager, sample_rule: RuleDefinition
    ) -> None:
        """Saving the same (intent, site) again updates the row."""
        await mgr.save_policy(sample_rule, success_count=3)

        # Update with new success count
        updated_rule = RuleDefinition(
            rule_id="sort_popular_v2",
            category="sort",
            intent_pattern="인기순 정렬",
            selector=".sort-popular-v2",
            method="click",
            site_pattern="*.naver.com",
            priority=20,
        )
        await mgr.save_policy(updated_rule, success_count=10)

        match = await mgr.query_policy("인기순 정렬", "*.naver.com")
        assert match is not None
        assert match.rule_id == "sort_popular_v2"
        assert match.selector == ".sort-popular-v2"

    async def test_confidence_from_success_count(
        self, mgr: MemoryManager, sample_rule: RuleDefinition
    ) -> None:
        """Confidence is capped at 1.0 and scales with success_count."""
        await mgr.save_policy(sample_rule, success_count=5)
        match = await mgr.query_policy("인기순 정렬", "*.naver.com")
        assert match is not None
        assert match.confidence == 0.5  # 5 / 10

        await mgr.save_policy(sample_rule, success_count=15)
        match = await mgr.query_policy("인기순 정렬", "*.naver.com")
        assert match is not None
        assert match.confidence == 1.0  # capped

    async def test_delete_policy(
        self, mgr: MemoryManager, sample_rule: RuleDefinition
    ) -> None:
        """delete_policy removes a policy entry."""
        await mgr.save_policy(sample_rule, success_count=5)
        deleted = await mgr.delete_policy("인기순 정렬", "*.naver.com")
        assert deleted is True
        assert await mgr.query_policy("인기순 정렬", "*.naver.com") is None

    async def test_delete_policy_nonexistent(self, mgr: MemoryManager) -> None:
        """delete_policy returns False when no row matches."""
        deleted = await mgr.delete_policy("no-such", "no-site")
        assert deleted is False

    async def test_multiple_policies_distinct_keys(
        self,
        mgr: MemoryManager,
        sample_rule: RuleDefinition,
        sample_rule_b: RuleDefinition,
    ) -> None:
        """Multiple policies with different (intent, site) keys coexist."""
        await mgr.save_policy(sample_rule, success_count=5)
        await mgr.save_policy(sample_rule_b, success_count=8)

        match_a = await mgr.query_policy("인기순 정렬", "*.naver.com")
        match_b = await mgr.query_policy("최신순 정렬", "*.naver.com")

        assert match_a is not None
        assert match_a.rule_id == "sort_popular"

        assert match_b is not None
        assert match_b.rule_id == "sort_latest"


# ── Test: Artifact Memory (Layer 4) ─────────────────


class TestArtifactMemory:
    """Tests for Layer 4 — binary artifact storage with TTL."""

    async def test_save_and_load(self, mgr: MemoryManager) -> None:
        """save_artifact / load_artifact round-trip."""
        data = b"\x89PNG\r\nfake image data"
        path = await mgr.save_artifact("task-1", "screenshot.png", data)
        assert path.exists()
        loaded = await mgr.load_artifact("task-1", "screenshot.png")
        assert loaded == data

    async def test_load_nonexistent_returns_none(self, mgr: MemoryManager) -> None:
        """Loading a missing artifact returns None."""
        result = await mgr.load_artifact("no-task", "no-file.png")
        assert result is None

    async def test_list_artifacts_empty(self, mgr: MemoryManager) -> None:
        """list_artifacts returns empty list for non-existent task."""
        names = await mgr.list_artifacts("no-such-task")
        assert names == []

    async def test_list_artifacts_multiple(self, mgr: MemoryManager) -> None:
        """list_artifacts returns sorted file names."""
        await mgr.save_artifact("t1", "b.png", b"b")
        await mgr.save_artifact("t1", "a.html", b"a")
        await mgr.save_artifact("t1", "c.json", b"c")
        names = await mgr.list_artifacts("t1")
        assert names == ["a.html", "b.png", "c.json"]

    async def test_overwrite_artifact(self, mgr: MemoryManager) -> None:
        """Saving the same artifact name overwrites the file."""
        await mgr.save_artifact("t1", "file.bin", b"old")
        await mgr.save_artifact("t1", "file.bin", b"new")
        loaded = await mgr.load_artifact("t1", "file.bin")
        assert loaded == b"new"

    async def test_separate_task_artifacts(self, mgr: MemoryManager) -> None:
        """Artifacts from different tasks are isolated."""
        await mgr.save_artifact("task-a", "file.bin", b"data-a")
        await mgr.save_artifact("task-b", "file.bin", b"data-b")
        assert await mgr.load_artifact("task-a", "file.bin") == b"data-a"
        assert await mgr.load_artifact("task-b", "file.bin") == b"data-b"


# ── Test: TTL-based Cleanup ─────────────────────────


class TestTTLCleanup:
    """Tests for artifact TTL expiration."""

    async def test_delete_expired_removes_old_files(
        self, mgr: MemoryManager, tmp_path: Path
    ) -> None:
        """delete_expired removes files older than max_age_hours."""
        path = await mgr.save_artifact("t-old", "old.png", b"old data")

        # Backdate the file's modification time to 48 hours ago
        old_time = time.time() - (48 * 3600)
        os.utime(path, (old_time, old_time))

        deleted = await mgr.delete_expired(max_age_hours=24)
        assert deleted == 1
        assert await mgr.load_artifact("t-old", "old.png") is None

    async def test_delete_expired_keeps_fresh_files(
        self, mgr: MemoryManager,
    ) -> None:
        """delete_expired does NOT remove files within the TTL window."""
        await mgr.save_artifact("t-fresh", "fresh.png", b"fresh data")

        deleted = await mgr.delete_expired(max_age_hours=24)
        assert deleted == 0
        assert await mgr.load_artifact("t-fresh", "fresh.png") == b"fresh data"

    async def test_delete_expired_mixed(self, mgr: MemoryManager) -> None:
        """delete_expired correctly handles a mix of old and fresh files."""
        path_old = await mgr.save_artifact("t-mix", "old.png", b"old")
        await mgr.save_artifact("t-mix", "fresh.png", b"fresh")

        old_time = time.time() - (48 * 3600)
        os.utime(path_old, (old_time, old_time))

        deleted = await mgr.delete_expired(max_age_hours=24)
        assert deleted == 1
        assert await mgr.load_artifact("t-mix", "old.png") is None
        assert await mgr.load_artifact("t-mix", "fresh.png") == b"fresh"

    async def test_delete_expired_cleans_empty_dirs(
        self, mgr: MemoryManager,
    ) -> None:
        """Empty task directories are removed after all artifacts expire."""
        path = await mgr.save_artifact("t-clean", "only.png", b"data")
        old_time = time.time() - (48 * 3600)
        os.utime(path, (old_time, old_time))

        await mgr.delete_expired(max_age_hours=24)
        assert not (mgr._artifacts_dir / "t-clean").exists()

    async def test_delete_expired_no_artifacts(self, mgr: MemoryManager) -> None:
        """delete_expired returns 0 when there are no artifacts at all."""
        deleted = await mgr.delete_expired(max_age_hours=1)
        assert deleted == 0


# ── Test: Factory ────────────────────────────────────


class TestFactory:
    """Tests for the ``create_memory_manager`` factory function."""

    async def test_factory_creates_directories(self, tmp_path: Path) -> None:
        """Factory creates episodes/ and artifacts/ subdirectories."""
        _ = await create_memory_manager(str(tmp_path / "fresh"))
        assert (tmp_path / "fresh" / "episodes").is_dir()
        assert (tmp_path / "fresh" / "artifacts").is_dir()

    async def test_factory_initialises_db(self, tmp_path: Path) -> None:
        """Factory creates and initialises the SQLite database."""
        mgr = await create_memory_manager(str(tmp_path / "db-test"))
        assert (tmp_path / "db-test" / "policy.db").exists()
        # Verify we can immediately query (schema is ready)
        result = await mgr.query_policy("test", "test")
        assert result is None


# ── Test: Protocol Compliance ────────────────────────


class TestProtocolCompliance:
    """Verify MemoryManager satisfies the IMemoryManager protocol."""

    def test_is_instance_of_protocol(self, mgr: MemoryManager) -> None:
        """MemoryManager is a structural subtype of IMemoryManager."""
        # Protocol structural check: all required methods exist
        assert hasattr(mgr, "get_working")
        assert hasattr(mgr, "set_working")
        assert hasattr(mgr, "save_episode")
        assert hasattr(mgr, "load_episode")
        assert hasattr(mgr, "query_policy")
        assert hasattr(mgr, "save_policy")

    def test_callable_signatures(self, mgr: MemoryManager) -> None:
        """All IMemoryManager methods are callable."""
        assert callable(mgr.get_working)
        assert callable(mgr.set_working)
        assert callable(mgr.save_episode)
        assert callable(mgr.load_episode)
        assert callable(mgr.query_policy)
        assert callable(mgr.save_policy)

    def test_runtime_protocol_check(self, tmp_path: Path) -> None:
        """isinstance check with runtime_checkable Protocol (if decorated).

        Since IMemoryManager uses Protocol without @runtime_checkable,
        we verify structural conformance by checking method signatures.
        """
        mgr = MemoryManager(data_dir=tmp_path)

        # Verify return types of synchronous methods
        assert mgr.get_working("x") is None
        mgr.set_working("x", 42)
        assert mgr.get_working("x") == 42


# ── Test: Edge Cases ────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_data_dir_created_on_init(self, tmp_path: Path) -> None:
        """MemoryManager creates data_dir and subdirectories if missing."""
        deep = tmp_path / "deep" / "nested" / "data"
        _ = MemoryManager(data_dir=deep)
        assert deep.exists()
        assert (deep / "episodes").exists()
        assert (deep / "artifacts").exists()

    async def test_empty_episode_data(self, mgr: MemoryManager) -> None:
        """An empty dict is valid episode data."""
        await mgr.save_episode("empty", {})
        loaded = await mgr.load_episode("empty")
        assert loaded == {}

    async def test_large_artifact(self, mgr: MemoryManager) -> None:
        """Large binary artifacts are handled correctly."""
        big = b"\x00" * (1024 * 1024)  # 1 MiB
        await mgr.save_artifact("big-task", "big.bin", big)
        loaded = await mgr.load_artifact("big-task", "big.bin")
        assert loaded == big
        assert len(loaded) == 1024 * 1024  # type: ignore[arg-type]

    async def test_policy_with_empty_arguments(self, mgr: MemoryManager) -> None:
        """Policy with empty arguments list is stored and retrieved correctly."""
        rule = RuleDefinition(
            rule_id="no_args",
            category="popup",
            intent_pattern="close popup",
            selector="#close",
            method="click",
            arguments=[],
            site_pattern="*",
        )
        await mgr.save_policy(rule, success_count=1)
        match = await mgr.query_policy("close popup", "*")
        assert match is not None
        assert match.arguments == []

    async def test_concurrent_episode_writes(self, mgr: MemoryManager) -> None:
        """Multiple sequential episode writes to different tasks succeed."""
        import asyncio

        tasks = [
            mgr.save_episode(f"task-{i}", {"index": i})
            for i in range(10)
        ]
        await asyncio.gather(*tasks)

        episodes = await mgr.list_episodes()
        assert len(episodes) == 10

    async def test_save_artifact_returns_correct_path(
        self, mgr: MemoryManager, tmp_path: Path
    ) -> None:
        """save_artifact returns the full path to the written file."""
        path = await mgr.save_artifact("t-path", "test.bin", b"data")
        expected = tmp_path / "artifacts" / "t-path" / "test.bin"
        assert path == expected

    def test_clear_working_then_set(self, mgr: MemoryManager) -> None:
        """After clear_working, new values can still be set."""
        mgr.set_working("a", 1)
        mgr.clear_working()
        mgr.set_working("b", 2)
        assert mgr.get_working("a") is None
        assert mgr.get_working("b") == 2
