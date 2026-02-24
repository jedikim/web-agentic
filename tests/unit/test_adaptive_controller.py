"""Tests for src.core.adaptive_controller — adaptive caching controller."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.adaptive_controller import AdaptiveController


def _make_mock_store(
    find_result: list[object] | None = None,
) -> MagicMock:
    """Create a mock ReplayStore."""
    store = MagicMock()
    store.find_similar = AsyncMock(return_value=find_result)
    store.record = AsyncMock(return_value=1)
    return store


class TestShouldUseCache:
    @pytest.mark.asyncio
    async def test_should_use_cache_with_history(self) -> None:
        """Returns True when cached steps exist."""
        store = _make_mock_store(find_result=[{"step_id": "s1"}])
        ctrl = AdaptiveController(store, min_successes=3)

        result = await ctrl.should_use_cache("example.com", "click login")
        assert result is True
        store.find_similar.assert_awaited_once_with("example.com", "click login", 3)

    @pytest.mark.asyncio
    async def test_should_use_cache_without_history(self) -> None:
        """Returns False when no cached steps exist."""
        store = _make_mock_store(find_result=None)
        ctrl = AdaptiveController(store, min_successes=3)

        result = await ctrl.should_use_cache("new-site.com", "do something")
        assert result is False


class TestGetCachedSteps:
    @pytest.mark.asyncio
    async def test_get_cached_steps_hit(self) -> None:
        """Returns cached steps when available."""
        steps = [{"step_id": "s1", "intent": "click"}]
        store = _make_mock_store(find_result=steps)
        ctrl = AdaptiveController(store, min_successes=3)

        result = await ctrl.get_cached_steps("example.com", "click login")
        assert result == steps

    @pytest.mark.asyncio
    async def test_get_cached_steps_miss(self) -> None:
        """Returns None when no cache available."""
        store = _make_mock_store(find_result=None)
        ctrl = AdaptiveController(store, min_successes=3)

        result = await ctrl.get_cached_steps("new-site.com", "do something")
        assert result is None


class TestRecordExecution:
    @pytest.mark.asyncio
    async def test_record_execution_calls_store(self) -> None:
        """record_execution delegates to ReplayStore.record."""
        store = _make_mock_store()
        ctrl = AdaptiveController(store, min_successes=3)

        await ctrl.record_execution(
            site="example.com",
            intent="click login",
            steps=[{"step_id": "s1"}],
            cost=0.01,
            success=True,
        )

        store.record.assert_awaited_once_with(
            "example.com", "click login", [{"step_id": "s1"}], 0.01, True,
        )


class TestMinSuccessesPassthrough:
    @pytest.mark.asyncio
    async def test_min_successes_passed_through(self) -> None:
        """Custom min_successes is forwarded to find_similar."""
        store = _make_mock_store(find_result=None)
        ctrl = AdaptiveController(store, min_successes=7)

        await ctrl.should_use_cache("x.com", "intent")
        store.find_similar.assert_awaited_once_with("x.com", "intent", 7)

    @pytest.mark.asyncio
    async def test_default_min_successes(self) -> None:
        """Default min_successes is 3."""
        store = _make_mock_store(find_result=None)
        ctrl = AdaptiveController(store)

        await ctrl.get_cached_steps("y.com", "intent")
        store.find_similar.assert_awaited_once_with("y.com", "intent", 3)
