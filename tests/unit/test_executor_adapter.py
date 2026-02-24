"""Unit tests for executor_adapter — MockExecutor and IExecutor re-export.

Tests verify:
  - Call recording for each method
  - Default return values
  - Override mechanism via create_mock_executor
  - IExecutor isinstance conformance
  - Re-export from executor_adapter module
"""
from __future__ import annotations

import pytest

from src.core.executor_adapter import IExecutor, MockExecutor, create_mock_executor
from src.core.types import ClickOptions


@pytest.mark.asyncio
async def test_mock_executor_records_goto() -> None:
    """goto() should record the URL in calls list."""
    mock = MockExecutor()
    await mock.goto("https://example.com")
    assert len(mock.calls) == 1
    name, args, _ = mock.calls[0]
    assert name == "goto"
    assert args == ("https://example.com",)


@pytest.mark.asyncio
async def test_mock_executor_records_click() -> None:
    """click() should record selector and options."""
    mock = MockExecutor()
    opts = ClickOptions(button="right")
    await mock.click("#btn", options=opts)
    assert len(mock.calls) == 1
    name, args, kwargs = mock.calls[0]
    assert name == "click"
    assert args == ("#btn",)
    assert kwargs["options"] is opts


@pytest.mark.asyncio
async def test_mock_executor_screenshot_returns_bytes() -> None:
    """screenshot() should return b'mock-png' by default."""
    mock = MockExecutor()
    data = await mock.screenshot()
    assert isinstance(data, bytes)
    assert data == b"mock-png"


@pytest.mark.asyncio
async def test_mock_executor_records_type_text() -> None:
    """type_text() should record selector and text."""
    mock = MockExecutor()
    await mock.type_text("input#search", "hello world")
    assert len(mock.calls) == 1
    name, args, _ = mock.calls[0]
    assert name == "type_text"
    assert args == ("input#search", "hello world")


@pytest.mark.asyncio
async def test_create_mock_executor_with_overrides() -> None:
    """create_mock_executor should allow overriding return values."""
    custom_png = b"\x89PNG_CUSTOM"
    mock = create_mock_executor(screenshot=custom_png)
    data = await mock.screenshot()
    assert data == custom_png


def test_mock_executor_is_iexecutor() -> None:
    """MockExecutor should satisfy isinstance check against IExecutor."""
    mock = MockExecutor()
    assert isinstance(mock, IExecutor)


def test_executor_adapter_re_exports_iexecutor() -> None:
    """IExecutor imported from executor_adapter should be the same as from types."""
    from src.core.types import IExecutor as OriginalIExecutor

    assert IExecutor is OriginalIExecutor


@pytest.mark.asyncio
async def test_mock_executor_get_page_state() -> None:
    """get_page_state() should return mock state dict by default."""
    mock = MockExecutor()
    state = await mock.get_page_state()
    assert isinstance(state, dict)
    assert "url" in state
    assert "title" in state
    assert state["url"] == "https://mock.example.com"
    assert len(mock.calls) == 1
    assert mock.calls[0][0] == "get_page_state"
