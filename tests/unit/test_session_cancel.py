"""Tests for SessionManager.cancel_turn()."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.session_manager import LiveSession, SessionManager, SessionNotFoundError


@pytest.fixture
def _mock_dependencies():
    """Create minimal mocks for SessionManager dependencies."""
    pool = AsyncMock()
    session_db = AsyncMock()
    notifier = AsyncMock()
    notifier.publish = AsyncMock()
    cache = AsyncMock()
    return pool, session_db, notifier, cache


@pytest.fixture
def manager(_mock_dependencies):
    pool, session_db, notifier, cache = _mock_dependencies
    return SessionManager(
        pool=pool, session_db=session_db, notifier=notifier, cache=cache,
    )


@pytest.fixture
def live_session():
    """Create a minimal LiveSession with mocks."""
    return LiveSession(
        session_id="sess-1",
        executor=MagicMock(),
        orchestrator=MagicMock(),
        handoff_manager=MagicMock(),
    )


def test_cancel_running_turn(manager: SessionManager, live_session: LiveSession) -> None:
    """cancel_turn should cancel a running task and return True."""
    # Create a mock task that is not done
    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.done.return_value = False
    mock_task.cancel.return_value = True
    live_session.running_task = mock_task

    manager._sessions["sess-1"] = live_session

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(manager.cancel_turn("sess-1"))
    finally:
        loop.close()

    assert result is True
    mock_task.cancel.assert_called_once()


def test_cancel_no_active_turn(manager: SessionManager, live_session: LiveSession) -> None:
    """cancel_turn should return False when no task is running."""
    live_session.running_task = None
    manager._sessions["sess-1"] = live_session

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(manager.cancel_turn("sess-1"))
    finally:
        loop.close()

    assert result is False


def test_cancel_already_done_task(manager: SessionManager, live_session: LiveSession) -> None:
    """cancel_turn should return False when the task is already done."""
    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.done.return_value = True
    live_session.running_task = mock_task

    manager._sessions["sess-1"] = live_session

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(manager.cancel_turn("sess-1"))
    finally:
        loop.close()

    assert result is False
    mock_task.cancel.assert_not_called()


def test_cancel_session_not_found(manager: SessionManager) -> None:
    """cancel_turn should raise SessionNotFoundError for unknown sessions."""
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(SessionNotFoundError):
            loop.run_until_complete(manager.cancel_turn("nonexistent"))
    finally:
        loop.close()
