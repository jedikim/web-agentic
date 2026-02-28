"""Unit tests for WebAgent SDK facade."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.llm_orchestrator import RunResult
from src.web_agent import WebAgent


@pytest.fixture
def mock_executor() -> AsyncMock:
    executor = AsyncMock()
    executor.goto = AsyncMock()
    executor.screenshot = AsyncMock(return_value=b"\x89PNG")
    executor.close = AsyncMock()
    return executor


@pytest.fixture
def mock_run_result() -> RunResult:
    return RunResult(success=True, total_cost_usd=0.01)


def _patch_deps():
    """Return a dict of patches for all WebAgent external dependencies."""
    mock_executor = AsyncMock()
    mock_executor.goto = AsyncMock()
    mock_executor.screenshot = AsyncMock(return_value=b"\x89PNG")
    mock_executor.close = AsyncMock()

    mock_cache = MagicMock()
    mock_cache.init = AsyncMock()
    mock_cache._db = MagicMock()
    mock_cache._db.close = AsyncMock()

    mock_orchestrator = AsyncMock()
    mock_orchestrator.run = AsyncMock(
        return_value=RunResult(success=True, total_cost_usd=0.01)
    )

    # V3 pipeline disabled for legacy tests
    from src.core.config import EngineConfig, V3PipelineConfig
    mock_config = EngineConfig(v3_pipeline=V3PipelineConfig(enabled=False))

    return {
        "executor": mock_executor,
        "cache": mock_cache,
        "orchestrator": mock_orchestrator,
        "config": mock_config,
    }


@pytest.mark.asyncio
async def test_lifecycle() -> None:
    """start -> goto -> run -> close works end-to-end."""
    mocks = _patch_deps()

    with (
        patch("src.web_agent.create_executor", return_value=mocks["executor"]),
        patch("src.web_agent.SelectorCache", return_value=mocks["cache"]),
        patch("src.web_agent.create_llm_planner"),
        patch("src.web_agent.LLMFirstOrchestrator", return_value=mocks["orchestrator"]),
        patch("src.web_agent.load_config", return_value=mocks["config"]),
    ):
        agent = WebAgent(headless=True)
        await agent.start()

        await agent.goto("https://example.com")
        mocks["executor"].goto.assert_awaited_once_with("https://example.com")

        result = await agent.run("Click the link")
        assert result.success is True

        await agent.close()
        mocks["executor"].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_context_manager() -> None:
    """async with WebAgent() as agent works."""
    mocks = _patch_deps()

    with (
        patch("src.web_agent.create_executor", return_value=mocks["executor"]),
        patch("src.web_agent.SelectorCache", return_value=mocks["cache"]),
        patch("src.web_agent.create_llm_planner"),
        patch("src.web_agent.LLMFirstOrchestrator", return_value=mocks["orchestrator"]),
        patch("src.web_agent.load_config", return_value=mocks["config"]),
    ):
        async with WebAgent(headless=True) as agent:
            result = await agent.run("Do something")
            assert result.success is True

        # close was called via __aexit__
        mocks["executor"].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cost_tracking() -> None:
    """Multiple runs accumulate total cost."""
    mocks = _patch_deps()
    call_count = 0

    async def _run_side_effect(intent: str) -> RunResult:
        nonlocal call_count
        call_count += 1
        return RunResult(success=True, total_cost_usd=0.02)

    mocks["orchestrator"].run = AsyncMock(side_effect=_run_side_effect)

    with (
        patch("src.web_agent.create_executor", return_value=mocks["executor"]),
        patch("src.web_agent.SelectorCache", return_value=mocks["cache"]),
        patch("src.web_agent.create_llm_planner"),
        patch("src.web_agent.LLMFirstOrchestrator", return_value=mocks["orchestrator"]),
        patch("src.web_agent.load_config", return_value=mocks["config"]),
    ):
        async with WebAgent(headless=True, max_total_cost=0.10) as agent:
            await agent.run("Step 1")
            assert agent.total_cost == pytest.approx(0.02)

            await agent.run("Step 2")
            assert agent.total_cost == pytest.approx(0.04)

            await agent.run("Step 3")
            assert agent.total_cost == pytest.approx(0.06)


@pytest.mark.asyncio
async def test_error_before_start() -> None:
    """run() raises RuntimeError before start() is called."""
    agent = WebAgent()

    with pytest.raises(RuntimeError, match="not started"):
        await agent.run("Do something")

    with pytest.raises(RuntimeError, match="not started"):
        await agent.goto("https://example.com")

    with pytest.raises(RuntimeError, match="not started"):
        await agent.screenshot()


@pytest.mark.asyncio
async def test_from_executor(mock_executor: AsyncMock) -> None:
    """from_executor classmethod creates agent with external executor."""
    mocks = _patch_deps()

    with (
        patch("src.web_agent.SelectorCache", return_value=mocks["cache"]),
        patch("src.web_agent.create_llm_planner"),
        patch("src.web_agent.LLMFirstOrchestrator", return_value=mocks["orchestrator"]),
        patch("src.web_agent.load_config", return_value=mocks["config"]),
    ):
        agent = await WebAgent.from_executor(mock_executor, headless=False)

        assert agent._started is True
        assert agent._owns_executor is False

        result = await agent.run("Click button")
        assert result.success is True

        await agent.close()
        # Should NOT close the executor we don't own
        mock_executor.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_cost_limit_exceeded() -> None:
    """run() raises RuntimeError when total cost exceeds max_total_cost."""
    mocks = _patch_deps()
    mocks["orchestrator"].run = AsyncMock(
        return_value=RunResult(success=True, total_cost_usd=0.06)
    )

    with (
        patch("src.web_agent.create_executor", return_value=mocks["executor"]),
        patch("src.web_agent.SelectorCache", return_value=mocks["cache"]),
        patch("src.web_agent.create_llm_planner"),
        patch("src.web_agent.LLMFirstOrchestrator", return_value=mocks["orchestrator"]),
        patch("src.web_agent.load_config", return_value=mocks["config"]),
    ):
        async with WebAgent(headless=True, max_total_cost=0.10) as agent:
            await agent.run("Step 1")  # cost = 0.06
            await agent.run("Step 2")  # cost = 0.12, exceeds limit

            with pytest.raises(RuntimeError, match="exceeds"):
                await agent.run("Step 3")  # should fail


@pytest.mark.asyncio
async def test_screenshot() -> None:
    """screenshot() delegates to executor."""
    mocks = _patch_deps()

    with (
        patch("src.web_agent.create_executor", return_value=mocks["executor"]),
        patch("src.web_agent.SelectorCache", return_value=mocks["cache"]),
        patch("src.web_agent.create_llm_planner"),
        patch("src.web_agent.LLMFirstOrchestrator", return_value=mocks["orchestrator"]),
        patch("src.web_agent.load_config", return_value=mocks["config"]),
    ):
        async with WebAgent() as agent:
            data = await agent.screenshot()
            assert data == b"\x89PNG"
            mocks["executor"].screenshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_double_start_is_idempotent() -> None:
    """Calling start() twice does not re-create resources."""
    mocks = _patch_deps()

    with (
        patch("src.web_agent.create_executor", return_value=mocks["executor"]) as mock_create,
        patch("src.web_agent.SelectorCache", return_value=mocks["cache"]),
        patch("src.web_agent.create_llm_planner"),
        patch("src.web_agent.LLMFirstOrchestrator", return_value=mocks["orchestrator"]),
        patch("src.web_agent.load_config", return_value=mocks["config"]),
    ):
        agent = WebAgent()
        await agent.start()
        await agent.start()  # should be no-op
        assert mock_create.call_count == 1
        await agent.close()
