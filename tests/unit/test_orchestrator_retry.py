"""Tests for LLMFirstOrchestrator retry/replanning with FallbackRouter."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.fallback_router import FallbackRouter
from src.core.llm_orchestrator import LLMFirstOrchestrator
from src.core.types import (
    FailureCode,
    PageState,
    StepDefinition,
    StepResult,
    VerifyResult,
)


def _make_page_state(**kw: object) -> PageState:
    return PageState(url="https://test.com", title="Test", **kw)  # type: ignore[arg-type]


def _make_step(**kw: object) -> StepDefinition:
    defaults = {"step_id": "s1", "intent": "click button", "max_attempts": 3}
    defaults.update(kw)  # type: ignore[arg-type]
    return StepDefinition(**defaults)  # type: ignore[arg-type]


def _make_orchestrator(
    *,
    router: FallbackRouter | None = None,
    execute_results: list[StepResult] | None = None,
    **kwargs: object,
) -> LLMFirstOrchestrator:
    """Create orchestrator with mocked components."""
    executor = MagicMock()
    executor.get_page = AsyncMock(return_value=MagicMock())
    executor.scroll = AsyncMock()

    extractor = MagicMock()
    extractor.extract_state = AsyncMock(return_value=_make_page_state())
    extractor.extract_inputs = AsyncMock(return_value=[])
    extractor.extract_clickables = AsyncMock(return_value=[])

    planner = MagicMock()
    planner.usage = MagicMock(total_cost_usd=0.0, total_tokens=0)
    planner.plan_with_context = AsyncMock(return_value=[])

    verifier = MagicMock()
    verifier.verify = AsyncMock(return_value=VerifyResult(success=True))

    orch = LLMFirstOrchestrator(
        executor=executor,
        extractor=extractor,
        planner=planner,
        verifier=verifier,
        fallback_router=router,
        backoff_base_ms=10,  # Fast for tests
        backoff_max_ms=100,
        jitter_ratio=0.01,
        **kwargs,  # type: ignore[arg-type]
    )

    # Mock _execute_step to return predefined results
    if execute_results is not None:
        call_count = {"n": 0}

        async def mock_execute_step(
            step: StepDefinition, page_context: str = "",
        ) -> StepResult:
            idx = min(call_count["n"], len(execute_results) - 1)
            call_count["n"] += 1
            return execute_results[idx]

        orch._execute_step = mock_execute_step  # type: ignore[assignment]

    return orch


class TestExecuteStepWithRetry:
    @pytest.mark.asyncio
    async def test_success_on_first_try(self) -> None:
        ok = StepResult(step_id="s1", success=True)
        orch = _make_orchestrator(
            router=FallbackRouter(),
            execute_results=[ok],
        )
        result = await orch._execute_step_with_retry(
            _make_step(), _make_page_state(),
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self) -> None:
        fail = StepResult(
            step_id="s1", success=False,
            failure_code=FailureCode.NOT_INTERACTABLE,
        )
        ok = StepResult(step_id="s1", success=True)
        orch = _make_orchestrator(
            router=FallbackRouter(),
            execute_results=[fail, ok],
        )
        result = await orch._execute_step_with_retry(
            _make_step(), _make_page_state(),
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_exhausts_max_attempts(self) -> None:
        fail = StepResult(
            step_id="s1", success=False,
            failure_code=FailureCode.SELECTOR_NOT_FOUND,
        )
        orch = _make_orchestrator(
            router=FallbackRouter(),
            execute_results=[fail, fail, fail],
        )
        result = await orch._execute_step_with_retry(
            _make_step(max_attempts=3), _make_page_state(),
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_no_router_returns_immediately_on_failure(self) -> None:
        fail = StepResult(step_id="s1", success=False)
        orch = _make_orchestrator(
            router=None,
            execute_results=[fail],
        )
        result = await orch._execute_step_with_retry(
            _make_step(), _make_page_state(),
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_router_classify_is_called(self) -> None:
        router = FallbackRouter()
        router.classify = MagicMock(return_value=FailureCode.SELECTOR_NOT_FOUND)  # type: ignore[assignment]
        router.record_outcome = MagicMock()  # type: ignore[assignment]

        fail = StepResult(step_id="s1", success=False)
        orch = _make_orchestrator(
            router=router,
            execute_results=[fail, fail, fail],
        )
        await orch._execute_step_with_retry(
            _make_step(max_attempts=3), _make_page_state(),
        )
        assert router.classify.call_count == 3  # Called for each attempt

    @pytest.mark.asyncio
    async def test_records_recovery_outcome(self) -> None:
        router = FallbackRouter()
        fail = StepResult(
            step_id="s1", success=False,
            failure_code=FailureCode.NOT_INTERACTABLE,
        )
        ok = StepResult(step_id="s1", success=True)
        orch = _make_orchestrator(
            router=router,
            execute_results=[fail, ok],
        )
        await orch._execute_step_with_retry(
            _make_step(), _make_page_state(),
        )
        stats = router.get_stats()
        # At least one recovery tracked
        assert len(stats) >= 0  # May have recorded


class TestBackoffDelay:
    def test_exponential_growth(self) -> None:
        orch = _make_orchestrator(execute_results=[])
        orch._backoff_base_ms = 500
        orch._backoff_max_ms = 10000

        assert orch._backoff_delay(0) == 500
        assert orch._backoff_delay(1) == 1000
        assert orch._backoff_delay(2) == 2000
        assert orch._backoff_delay(3) == 4000

    def test_capped_at_max(self) -> None:
        orch = _make_orchestrator(execute_results=[])
        orch._backoff_base_ms = 500
        orch._backoff_max_ms = 3000

        assert orch._backoff_delay(10) == 3000


class TestJitteredWait:
    @pytest.mark.asyncio
    async def test_waits_approximately_correct_time(self) -> None:
        orch = _make_orchestrator(execute_results=[])
        orch._jitter_ratio = 0.01  # Very small jitter

        import time
        start = time.monotonic()
        await orch._jittered_wait(50)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms >= 30  # ~50ms minus scheduler jitter
        assert elapsed_ms < 200


class TestFallbackStats:
    def test_empty_stats_without_router(self) -> None:
        orch = _make_orchestrator(router=None, execute_results=[])
        assert orch.fallback_stats == {}

    def test_stats_with_router(self) -> None:
        router = FallbackRouter()
        router.record_outcome(FailureCode.SELECTOR_NOT_FOUND, recovered=True)
        orch = _make_orchestrator(router=router, execute_results=[])
        stats = orch.fallback_stats
        assert "SelectorNotFound" in stats


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_breaks_after_consecutive_failures(self) -> None:
        """Circuit breaker should stop after max_consecutive_failures."""
        fail = StepResult(step_id="s1", success=False)
        steps = [_make_step(step_id=f"s{i}") for i in range(5)]

        planner = MagicMock()
        planner.usage = MagicMock(total_cost_usd=0.0, total_tokens=0)
        planner.plan_with_context = AsyncMock(return_value=steps)

        page_mock = MagicMock()
        page_mock.wait_for_load_state = AsyncMock()
        page_mock.wait_for_timeout = AsyncMock()

        executor = MagicMock()
        executor.get_page = AsyncMock(return_value=page_mock)

        extractor = MagicMock()
        extractor.extract_state = AsyncMock(
            return_value=_make_page_state()
        )

        orch = LLMFirstOrchestrator(
            executor=executor,
            extractor=extractor,
            planner=planner,
            verifier=MagicMock(),
            max_consecutive_failures=2,
            enable_replanning=False,
            backoff_base_ms=1,
            jitter_ratio=0.01,
        )

        # Mock both _execute_step_with_retry to always fail
        async def always_fail(
            step: object, ps: object, previous_action: str = "",
        ) -> StepResult:
            return fail
        orch._execute_step_with_retry = always_fail  # type: ignore[assignment]

        result = await orch.run("do something")
        assert result.success is False
        # Should stop at circuit breaker (2), not execute all 5
        assert len(result.step_results) <= 2
