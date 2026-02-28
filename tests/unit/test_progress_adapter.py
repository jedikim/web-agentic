"""Tests for NotifierProgressCallback adapter."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.api.progress_adapter import NotifierProgressCallback
from src.core.types import ProgressEvent, ProgressInfo
from src.evolution.notifier import Notifier


@pytest.fixture
def notifier() -> AsyncMock:
    mock = AsyncMock(spec=Notifier)
    mock.publish = AsyncMock()
    return mock


@pytest.fixture
def adapter(notifier: AsyncMock) -> NotifierProgressCallback:
    return NotifierProgressCallback(notifier, session_id="sess-123")


def test_on_progress_publishes_sse(
    adapter: NotifierProgressCallback,
    notifier: AsyncMock,
) -> None:
    """on_progress should schedule a notifier.publish call."""
    info = ProgressInfo(
        event=ProgressEvent.STEP_STARTED,
        step_id="s1",
        step_index=0,
        total_steps=3,
        method="L",
        attempt=1,
        message="Click search button",
    )

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_call_on_progress(adapter, info, loop))
    finally:
        loop.close()

    notifier.publish.assert_called_once()
    call_args = notifier.publish.call_args
    assert call_args[0][0] == "session_progress"
    data = call_args[0][1]
    assert data["session_id"] == "sess-123"
    assert data["event"] == "step_started"
    assert data["step_id"] == "s1"
    assert data["step_index"] == 0
    assert data["total_steps"] == 3
    assert data["method"] == "L"
    assert data["attempt"] == 1
    assert data["message"] == "Click search button"


@pytest.mark.parametrize("event", list(ProgressEvent))
def test_all_event_types_mapped(
    adapter: NotifierProgressCallback,
    notifier: AsyncMock,
    event: ProgressEvent,
) -> None:
    """Every ProgressEvent value should be forwarded to notifier."""
    info = ProgressInfo(event=event, message="test")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_call_on_progress(adapter, info, loop))
    finally:
        loop.close()

    notifier.publish.assert_called_once()
    data = notifier.publish.call_args[0][1]
    assert data["event"] == event.value


async def _call_on_progress(
    adapter: NotifierProgressCallback,
    info: ProgressInfo,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Helper to call on_progress and await the scheduled future."""
    adapter.on_progress(info)
    # Give the scheduled ensure_future a chance to execute
    await asyncio.sleep(0.01)
