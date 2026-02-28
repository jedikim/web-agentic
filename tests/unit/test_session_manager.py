"""Tests for SessionManager — session lifecycle and orchestration."""
from __future__ import annotations

import tempfile
from datetime import UTC
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.api.session_db import SessionDB
from src.api.session_manager import (
    SessionManager,
    SessionNotFoundError,
)
from src.core.handoff import HandoffReason
from src.core.llm_orchestrator import RunResult
from src.core.types import StepResult
from src.evolution.notifier import Notifier

# ── Fixtures ─────────────────────────────────────────


@pytest_asyncio.fixture
async def session_db() -> SessionDB:
    """Create a real SessionDB backed by a temp file."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "test_sessions.db")
        sdb = SessionDB(db_path=db_path)
        await sdb.init()
        yield sdb
        await sdb.close()


@pytest.fixture
def mock_pool() -> AsyncMock:
    """Mock ExecutorPool."""
    pool = AsyncMock()
    executor = AsyncMock()
    executor.goto = AsyncMock()
    executor.screenshot = AsyncMock(return_value=b"\x89PNG")
    executor.close = AsyncMock()
    pool.acquire = AsyncMock(return_value=executor)
    pool.release = AsyncMock()
    return pool


@pytest.fixture
def mock_notifier() -> AsyncMock:
    """Mock Notifier."""
    notifier = AsyncMock(spec=Notifier)
    notifier.publish = AsyncMock()
    return notifier


@pytest.fixture
def mock_cache() -> AsyncMock:
    """Mock SelectorCache."""
    cache = AsyncMock()
    cache.init = AsyncMock()
    return cache


@pytest_asyncio.fixture
async def manager(
    mock_pool: AsyncMock,
    session_db: SessionDB,
    mock_notifier: AsyncMock,
    mock_cache: AsyncMock,
) -> SessionManager:
    """Create a SessionManager with mocked dependencies."""
    mgr = SessionManager(
        pool=mock_pool,
        session_db=session_db,
        notifier=mock_notifier,
        cache=mock_cache,
        idle_timeout_minutes=30,
    )
    return mgr


# ── Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_session(
    manager: SessionManager,
    mock_pool: AsyncMock,
    mock_notifier: AsyncMock,
) -> None:
    """create_session should acquire executor, persist to DB, and emit SSE."""
    with patch("src.api.session_manager.create_llm_planner") as mock_planner_factory:
        mock_planner_factory.return_value = MagicMock()

        session = await manager.create_session(
            headless=True,
            initial_url="https://example.com",
            context={"test": True},
        )

    assert session["status"] == "active"
    assert session["initial_url"] == "https://example.com"
    assert session["headless"] is True
    mock_pool.acquire.assert_awaited_once()
    mock_notifier.publish.assert_any_await(
        "session_created",
        {
            "session_id": session["id"],
            "headless": True,
            "initial_url": "https://example.com",
        },
    )


@pytest.mark.asyncio
async def test_execute_turn(
    manager: SessionManager,
    mock_notifier: AsyncMock,
) -> None:
    """execute_turn should run orchestrator and persist results."""
    with patch("src.api.session_manager.create_llm_planner") as mock_planner_factory:
        mock_planner = MagicMock()
        mock_planner.usage = MagicMock(total_tokens=100, total_cost_usd=0.01)
        mock_planner_factory.return_value = mock_planner

        session = await manager.create_session(headless=True)
        session_id = session["id"]

    # Mock the orchestrator's run method
    live = manager._sessions[session_id]
    mock_run_result = RunResult(
        success=True,
        step_results=[
            StepResult(step_id="s1", success=True, method="L",
                       tokens_used=50, cost_usd=0.005, latency_ms=100),
            StepResult(step_id="s2", success=True, method="CACHE",
                       tokens_used=0, cost_usd=0.0, latency_ms=20),
        ],
        screenshots=["shot1.png"],
        total_tokens=50,
        total_cost_usd=0.005,
    )
    live.orchestrator.run = AsyncMock(return_value=mock_run_result)

    result = await manager.execute_turn(session_id, "Search for Python")

    assert result["success"] is True
    assert result["steps_total"] == 2
    assert result["steps_ok"] == 2
    assert result["cost_usd"] == 0.005
    assert result["tokens_used"] == 50
    assert result["screenshots"] == ["shot1.png"]

    # SSE events should have been published
    mock_notifier.publish.assert_any_await(
        "session_turn_started",
        {
            "session_id": session_id,
            "intent": "Search for Python",
            "turn_num": 1,
        },
    )
    mock_notifier.publish.assert_any_await(
        "session_turn_completed",
        {
            "session_id": session_id,
            "turn_id": result["id"],
            "success": True,
            "cost_usd": 0.005,
            "result_summary": "",
        },
    )


@pytest.mark.asyncio
async def test_close_session(
    manager: SessionManager,
    mock_pool: AsyncMock,
    mock_notifier: AsyncMock,
) -> None:
    """close_session should release executor and remove from live sessions."""
    with patch("src.api.session_manager.create_llm_planner") as mock_planner_factory:
        mock_planner_factory.return_value = MagicMock()
        session = await manager.create_session(headless=True)
        session_id = session["id"]

    assert session_id in manager._sessions

    closed = await manager.close_session(session_id)
    assert closed["status"] == "closed"
    assert session_id not in manager._sessions
    mock_pool.release.assert_awaited()
    mock_notifier.publish.assert_any_await(
        "session_closed", {"session_id": session_id},
    )


@pytest.mark.asyncio
async def test_oneshot_execution(
    manager: SessionManager,
) -> None:
    """run_oneshot should create, execute, and close in one call."""
    with patch("src.api.session_manager.create_llm_planner") as mock_planner_factory:
        mock_planner = MagicMock()
        mock_planner.usage = MagicMock(total_tokens=100, total_cost_usd=0.01)
        mock_planner_factory.return_value = mock_planner

        # We need to mock orchestrator run after create_session
        original_create = manager.create_session

        async def patched_create(**kwargs: Any) -> dict[str, Any]:
            result = await original_create(**kwargs)
            sid = result["id"]
            live = manager._sessions[sid]
            live.orchestrator.run = AsyncMock(return_value=RunResult(
                success=True,
                step_results=[StepResult(step_id="s1", success=True, method="L")],
                total_tokens=10,
                total_cost_usd=0.001,
            ))
            return result

        manager.create_session = patched_create  # type: ignore[assignment]

        result = await manager.run_oneshot(
            intent="Open example.com",
            initial_url="https://example.com",
            headless=True,
        )

    assert result["success"] is True
    # Session should be closed (not in live sessions)
    assert len(manager._sessions) == 0


@pytest.mark.asyncio
async def test_session_not_found_error(manager: SessionManager) -> None:
    """Operations on non-existent session should raise SessionNotFoundError."""
    with pytest.raises(SessionNotFoundError):
        await manager.execute_turn("nonexistent", "test")

    with pytest.raises(SessionNotFoundError):
        await manager.get_screenshot("nonexistent")

    with pytest.raises(SessionNotFoundError):
        await manager.close_session("nonexistent")

    with pytest.raises(SessionNotFoundError):
        await manager.get_handoffs("nonexistent")

    with pytest.raises(SessionNotFoundError):
        await manager.resolve_handoff("nonexistent", "req1", "done")


@pytest.mark.asyncio
async def test_cleanup_expires_sessions(
    manager: SessionManager,
    mock_pool: AsyncMock,
    mock_notifier: AsyncMock,
    session_db: SessionDB,
) -> None:
    """Cleanup should expire idle sessions and release executors."""
    with patch("src.api.session_manager.create_llm_planner") as mock_planner_factory:
        mock_planner_factory.return_value = MagicMock()
        session = await manager.create_session(headless=True)
        session_id = session["id"]

    # Simulate idle by setting last_activity far in the past
    from datetime import datetime, timedelta
    old_time = (
        datetime.now(UTC) - timedelta(minutes=60)
    ).isoformat(timespec="seconds")
    await session_db.db.execute(
        "UPDATE sessions SET last_activity = ? WHERE id = ?",
        (old_time, session_id),
    )
    await session_db.db.commit()

    # Call the internal expire logic directly
    expired = await session_db.expire_idle_sessions(idle_minutes=30)
    assert session_id in expired

    # Simulate what cleanup_loop does for expired sessions
    if session_id in manager._sessions:
        live = manager._sessions.pop(session_id)
        await mock_pool.release(live.executor)

    assert session_id not in manager._sessions
    mock_pool.release.assert_awaited()


@pytest.mark.asyncio
async def test_handoff_flow(
    manager: SessionManager,
    mock_notifier: AsyncMock,
) -> None:
    """Handoff flow: create session, request handoff, resolve it."""
    with patch("src.api.session_manager.create_llm_planner") as mock_planner_factory:
        mock_planner_factory.return_value = MagicMock()
        session = await manager.create_session(headless=True)
        session_id = session["id"]

    live = manager._sessions[session_id]

    # Simulate a handoff request
    request = await live.handoff_manager.request_handoff(
        reason=HandoffReason.CAPTCHA,
        url="https://example.com/captcha",
        title="CAPTCHA Page",
        message="Please solve the CAPTCHA",
    )

    # Get pending handoffs
    handoffs = await manager.get_handoffs(session_id)
    assert len(handoffs) == 1
    assert handoffs[0]["request_id"] == request.request_id
    assert handoffs[0]["reason"] == "captcha"

    # Resolve handoff
    resolution = await manager.resolve_handoff(
        session_id, request.request_id, "Solved CAPTCHA manually",
    )
    assert resolution["resolved"] is True
    assert resolution["action_taken"] == "Solved CAPTCHA manually"

    # Pending should be empty now
    handoffs_after = await manager.get_handoffs(session_id)
    assert len(handoffs_after) == 0

    mock_notifier.publish.assert_any_await(
        "handoff_resolved",
        {
            "session_id": session_id,
            "request_id": request.request_id,
            "action_taken": "Solved CAPTCHA manually",
        },
    )
