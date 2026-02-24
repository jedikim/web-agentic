"""Tests for the chat automation service."""
import asyncio

import pytest

from src.api.chat_automation import (
    ChatAutomationService,
    RunStatus,
)


@pytest.mark.asyncio
async def test_start_run_returns_run_id():
    svc = ChatAutomationService()
    run_id = await svc.start_run("session-1", "click login")
    assert isinstance(run_id, str)
    assert len(run_id) > 0


@pytest.mark.asyncio
async def test_start_run_sets_running():
    svc = ChatAutomationService()
    run_id = await svc.start_run("session-1", "click login")
    status = await svc.get_status(run_id)
    assert status["status"] in ("running", "completed")


@pytest.mark.asyncio
async def test_pause_sets_paused():
    svc = ChatAutomationService()
    run_id = await svc.start_run("session-1", "click login")
    state = svc._runs[run_id]
    state.status = RunStatus.RUNNING
    await svc.pause(run_id)
    status = await svc.get_status(run_id)
    assert status["status"] == "paused"


@pytest.mark.asyncio
async def test_resume_sets_running():
    svc = ChatAutomationService()
    run_id = await svc.start_run("session-1", "click login")
    state = svc._runs[run_id]
    state.status = RunStatus.RUNNING
    await svc.pause(run_id)
    await svc.resume(run_id)
    status = await svc.get_status(run_id)
    assert status["status"] == "running"


@pytest.mark.asyncio
async def test_cancel_sets_canceled():
    svc = ChatAutomationService()
    run_id = await svc.start_run("session-1", "click login")
    state = svc._runs[run_id]
    state.status = RunStatus.RUNNING
    await svc.cancel(run_id)
    status = await svc.get_status(run_id)
    assert status["status"] == "canceled"


@pytest.mark.asyncio
async def test_submit_captcha_resolves_future():
    svc = ChatAutomationService()
    run_id = await svc.start_run("session-1", "click login")
    state = svc._runs[run_id]
    state.status = RunStatus.WAITING_CAPTCHA
    loop = asyncio.get_event_loop()
    state.captcha_future = loop.create_future()
    await svc.submit_captcha(run_id, "abc123")
    assert state.captcha_future.result() == "abc123"


@pytest.mark.asyncio
async def test_attach_image_returns_path(tmp_path):
    svc = ChatAutomationService(image_dir=str(tmp_path))
    run_id = await svc.start_run("session-1", "click login")
    path = await svc.attach_image(run_id, b"PNG_DATA", "test.png")
    assert "test.png" in path
    assert (tmp_path / f"{run_id}_test.png").exists()


@pytest.mark.asyncio
async def test_cancel_already_canceled_raises():
    svc = ChatAutomationService()
    run_id = await svc.start_run("session-1", "click login")
    state = svc._runs[run_id]
    state.status = RunStatus.CANCELED
    with pytest.raises(RuntimeError, match="Cannot cancel"):
        await svc.cancel(run_id)


@pytest.mark.asyncio
async def test_pause_canceled_raises():
    svc = ChatAutomationService()
    run_id = await svc.start_run("session-1", "click login")
    state = svc._runs[run_id]
    state.status = RunStatus.CANCELED
    with pytest.raises(RuntimeError, match="Cannot pause"):
        await svc.pause(run_id)


@pytest.mark.asyncio
async def test_concurrent_runs_prevented():
    svc = ChatAutomationService()
    run_id = await svc.start_run("session-1", "click login")
    state = svc._runs[run_id]
    state.status = RunStatus.RUNNING
    with pytest.raises(RuntimeError, match="already has active"):
        await svc.start_run("session-1", "another task")


@pytest.mark.asyncio
async def test_get_status_unknown_run():
    svc = ChatAutomationService()
    with pytest.raises(KeyError, match="Unknown run_id"):
        await svc.get_status("nonexistent")


@pytest.mark.asyncio
async def test_run_status_enum_values():
    assert RunStatus.IDLE.value == "idle"
    assert RunStatus.RUNNING.value == "running"
    assert RunStatus.PAUSED.value == "paused"
    assert RunStatus.CANCELED.value == "canceled"
