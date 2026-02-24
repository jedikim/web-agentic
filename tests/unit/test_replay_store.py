"""Tests for src.learning.replay_store — execution history storage."""
from __future__ import annotations

import os

import pytest
import pytest_asyncio

from src.learning.replay_store import AdaptiveConfig, ReplayStore


@pytest_asyncio.fixture
async def store(tmp_path: object) -> ReplayStore:
    """Create a ReplayStore backed by a temporary SQLite file."""
    db_path = os.path.join(str(tmp_path), "test_replay.db")
    s = ReplayStore(db_path=db_path)
    await s.init()
    return s


class TestAdaptiveConfig:
    def test_defaults(self) -> None:
        cfg = AdaptiveConfig()
        assert cfg.min_successes == 3
        assert cfg.enabled is True

    def test_custom_values(self) -> None:
        cfg = AdaptiveConfig(min_successes=5, enabled=False)
        assert cfg.min_successes == 5
        assert cfg.enabled is False

    def test_frozen(self) -> None:
        cfg = AdaptiveConfig()
        with pytest.raises(AttributeError):
            cfg.min_successes = 10  # type: ignore[misc]


class TestReplayStoreInit:
    @pytest.mark.asyncio
    async def test_init_creates_table(self, tmp_path: object) -> None:
        """init() should create the execution_traces table."""
        import aiosqlite

        db_path = os.path.join(str(tmp_path), "init_test.db")
        store = ReplayStore(db_path=db_path)
        await store.init()

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='execution_traces'"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "execution_traces"

    @pytest.mark.asyncio
    async def test_init_idempotent(self, tmp_path: object) -> None:
        """Calling init() twice should not raise."""
        db_path = os.path.join(str(tmp_path), "idempotent.db")
        store = ReplayStore(db_path=db_path)
        await store.init()
        await store.init()  # Should not raise


class TestReplayStoreRecord:
    @pytest.mark.asyncio
    async def test_record_returns_id(self, store: ReplayStore) -> None:
        trace_id = await store.record(
            site="example.com",
            intent="click login",
            steps=[{"step_id": "s1", "action": "click"}],
            cost=0.01,
            success=True,
        )
        assert trace_id > 0

    @pytest.mark.asyncio
    async def test_record_increments_id(self, store: ReplayStore) -> None:
        id1 = await store.record("a.com", "intent1", [], 0.0, True)
        id2 = await store.record("a.com", "intent2", [], 0.0, True)
        assert id2 > id1

    @pytest.mark.asyncio
    async def test_record_and_find_similar(self, store: ReplayStore) -> None:
        steps = [{"step_id": "s1", "action": "click", "target": "#btn"}]
        for _ in range(3):
            await store.record("ex.com", "click button", steps, 0.01, True)

        result = await store.find_similar("ex.com", "click button", min_successes=3)
        assert result is not None
        assert result == steps


class TestReplayStoreFindSimilar:
    @pytest.mark.asyncio
    async def test_find_similar_insufficient_successes(self, store: ReplayStore) -> None:
        """find_similar should return None when fewer than min_successes."""
        steps = [{"step_id": "s1"}]
        await store.record("a.com", "click", steps, 0.01, True)
        await store.record("a.com", "click", steps, 0.01, True)

        result = await store.find_similar("a.com", "click", min_successes=3)
        assert result is None

    @pytest.mark.asyncio
    async def test_find_similar_sufficient_successes(self, store: ReplayStore) -> None:
        """find_similar should return steps when enough successes exist."""
        steps = [{"step_id": "s1", "intent": "do thing"}]
        for _ in range(4):
            await store.record("b.com", "do thing", steps, 0.01, True)

        result = await store.find_similar("b.com", "do thing", min_successes=3)
        assert result is not None
        assert result == steps

    @pytest.mark.asyncio
    async def test_find_similar_ignores_failures(self, store: ReplayStore) -> None:
        """Only successful traces count toward min_successes."""
        steps = [{"step_id": "s1"}]
        await store.record("c.com", "search", steps, 0.01, True)
        await store.record("c.com", "search", steps, 0.01, True)
        await store.record("c.com", "search", steps, 0.01, False)  # failure
        await store.record("c.com", "search", steps, 0.01, False)  # failure

        result = await store.find_similar("c.com", "search", min_successes=3)
        assert result is None

    @pytest.mark.asyncio
    async def test_find_similar_returns_most_recent(self, store: ReplayStore) -> None:
        """find_similar should return steps from the most recent successful trace."""
        old_steps = [{"step_id": "s_old"}]
        new_steps = [{"step_id": "s_new"}]

        for _ in range(3):
            await store.record("d.com", "login", old_steps, 0.01, True)
        await store.record("d.com", "login", new_steps, 0.005, True)

        result = await store.find_similar("d.com", "login", min_successes=3)
        assert result is not None
        assert result == new_steps

    @pytest.mark.asyncio
    async def test_find_similar_no_data(self, store: ReplayStore) -> None:
        """find_similar should return None when no data exists."""
        result = await store.find_similar("none.com", "nothing", min_successes=1)
        assert result is None


class TestReplayStoreSuccessRate:
    @pytest.mark.asyncio
    async def test_success_rate_calculation(self, store: ReplayStore) -> None:
        steps = [{"step_id": "s1"}]
        await store.record("e.com", "task", steps, 0.01, True)
        await store.record("e.com", "task", steps, 0.01, True)
        await store.record("e.com", "task", steps, 0.01, False)

        successes, total = await store.get_success_rate("e.com", "task")
        assert successes == 2
        assert total == 3

    @pytest.mark.asyncio
    async def test_success_rate_no_data(self, store: ReplayStore) -> None:
        successes, total = await store.get_success_rate("none.com", "nothing")
        assert successes == 0
        assert total == 0

    @pytest.mark.asyncio
    async def test_success_rate_all_failures(self, store: ReplayStore) -> None:
        steps = [{"step_id": "s1"}]
        for _ in range(3):
            await store.record("f.com", "fail", steps, 0.01, False)

        successes, total = await store.get_success_rate("f.com", "fail")
        assert successes == 0
        assert total == 3


class TestReplayStoreClose:
    @pytest.mark.asyncio
    async def test_close_is_noop(self, store: ReplayStore) -> None:
        """close() should not raise."""
        await store.close()
