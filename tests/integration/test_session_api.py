"""Integration tests for the Session API — httpx AsyncClient.

Mocks SessionManager at the dependency level so no real browser
or LLM keys are needed.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from src.api.dependencies import get_session_manager, set_session_manager
from src.api.routes import run, sessions
from src.api.session_manager import SessionManager, SessionNotFoundError


# ── Mock helpers ─────────────────────────────────────


def _make_session(
    session_id: str = "sess001",
    status: str = "active",
    headless: bool = True,
    initial_url: str | None = "https://example.com",
    current_url: str | None = "https://example.com",
    total_cost_usd: float = 0.0,
    total_tokens: int = 0,
    turn_count: int = 0,
    context: dict[str, Any] | None = None,
    created_at: str = "2025-01-01T00:00:00+00:00",
    last_activity: str = "2025-01-01T00:00:00+00:00",
    closed_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": session_id,
        "status": status,
        "headless": headless,
        "initial_url": initial_url,
        "current_url": current_url,
        "total_cost_usd": total_cost_usd,
        "total_tokens": total_tokens,
        "turn_count": turn_count,
        "context": context or {},
        "created_at": created_at,
        "last_activity": last_activity,
        "closed_at": closed_at,
    }


def _make_turn(
    turn_id: str = "turn001",
    session_id: str = "sess001",
    turn_num: int = 1,
    intent: str = "click login",
    success: bool = True,
    cost_usd: float = 0.01,
    tokens_used: int = 100,
    steps_total: int = 2,
    steps_ok: int = 2,
    error_msg: str | None = None,
    screenshots: list[str] | None = None,
    started_at: str = "2025-01-01T00:00:01+00:00",
    completed_at: str | None = "2025-01-01T00:00:02+00:00",
) -> dict[str, Any]:
    return {
        "id": turn_id,
        "session_id": session_id,
        "turn_num": turn_num,
        "intent": intent,
        "success": success,
        "cost_usd": cost_usd,
        "tokens_used": tokens_used,
        "steps_total": steps_total,
        "steps_ok": steps_ok,
        "error_msg": error_msg,
        "screenshots": screenshots or [],
        "step_details": [],
        "started_at": started_at,
        "completed_at": completed_at,
    }


def _build_mock_manager() -> MagicMock:
    """Build a mock SessionManager with sensible defaults."""
    mgr = MagicMock(spec=SessionManager)

    # Default session data
    session = _make_session()
    mgr.create_session = AsyncMock(return_value=session)
    mgr.close_session = AsyncMock(return_value={**session, "status": "closed"})
    mgr.execute_turn = AsyncMock(return_value=_make_turn())
    mgr.get_screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n fake png")
    mgr.get_handoffs = AsyncMock(return_value=[])
    mgr.resolve_handoff = AsyncMock(return_value={
        "request_id": "hoff001", "resolved": True, "action_taken": "solved",
    })
    mgr.run_oneshot = AsyncMock(return_value=_make_turn())

    # Mock the _db for list/get operations
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[session])
    mock_db.get_session = AsyncMock(return_value=session)
    mock_db.get_session_turns = AsyncMock(return_value=[_make_turn()])
    mgr._db = mock_db

    return mgr


# ── Test App ─────────────────────────────────────────


def _create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(sessions.router)
    app.include_router(run.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


_app = _create_test_app()


@pytest.fixture
def mock_session_mgr() -> MagicMock:
    mgr = _build_mock_manager()
    set_session_manager(mgr)  # type: ignore[arg-type]
    return mgr


@pytest.fixture
async def client(mock_session_mgr: MagicMock) -> AsyncIterator[httpx.AsyncClient]:
    # Override dependency at FastAPI level as well
    _app.dependency_overrides[get_session_manager] = lambda: mock_session_mgr
    transport = httpx.ASGITransport(app=_app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    _app.dependency_overrides.clear()


# ── Tests ────────────────────────────────────────────


async def test_create_session(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/sessions/", json={"headless": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "sess001"
    assert data["status"] == "active"


async def test_list_sessions(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    resp = await client.get("/api/sessions/")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == "sess001"


async def test_get_session_detail(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    resp = await client.get("/api/sessions/sess001")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == "sess001"
    assert "turns" in detail
    assert len(detail["turns"]) == 1
    assert detail["turns"][0]["id"] == "turn001"


async def test_execute_turn(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    resp = await client.post(
        "/api/sessions/sess001/turn",
        json={"intent": "click login"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["turn_id"] == "turn001"
    assert data["success"] is True
    assert data["session_id"] == "sess001"
    assert data["steps_total"] == 2
    assert data["steps_ok"] == 2


async def test_get_screenshot(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    resp = await client.get("/api/sessions/sess001/screenshot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG")


async def test_get_handoffs(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    resp = await client.get("/api/sessions/sess001/handoffs")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_handoffs_with_data(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    mock_session_mgr.get_handoffs.return_value = [
        {
            "request_id": "hoff001",
            "reason": "captcha",
            "url": "https://example.com/login",
            "title": "Login Page",
            "message": "CAPTCHA detected",
            "created_at": "2025-01-01T00:00:00+00:00",
        },
    ]
    resp = await client.get("/api/sessions/sess001/handoffs")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["request_id"] == "hoff001"
    assert items[0]["reason"] == "captcha"


async def test_resolve_handoff(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    resp = await client.post(
        "/api/sessions/sess001/handoffs/hoff001/resolve",
        json={"action_taken": "solved captcha"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "resolved"


async def test_close_session(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    resp = await client.delete("/api/sessions/sess001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "closed"
    assert data["data"]["session_id"] == "sess001"


async def test_oneshot_run(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    resp = await client.post(
        "/api/run",
        json={"intent": "search python", "url": "https://google.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["steps_total"] == 2


async def test_session_not_found(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    mock_session_mgr._db.get_session.return_value = None
    resp = await client.get("/api/sessions/nonexistent")
    assert resp.status_code == 404


async def test_execute_turn_session_not_found(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    mock_session_mgr.execute_turn.side_effect = SessionNotFoundError("not found")
    resp = await client.post(
        "/api/sessions/nonexistent/turn",
        json={"intent": "click login"},
    )
    assert resp.status_code == 404


async def test_screenshot_session_not_found(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    mock_session_mgr.get_screenshot.side_effect = SessionNotFoundError("not found")
    resp = await client.get("/api/sessions/nonexistent/screenshot")
    assert resp.status_code == 404


async def test_close_session_not_found(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    mock_session_mgr.close_session.side_effect = SessionNotFoundError("not found")
    resp = await client.delete("/api/sessions/nonexistent")
    assert resp.status_code == 404


async def test_create_session_with_url(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    resp = await client.post(
        "/api/sessions/",
        json={"url": "https://example.com", "headless": False},
    )
    assert resp.status_code == 200
    mock_session_mgr.create_session.assert_called_once_with(
        headless=False,
        initial_url="https://example.com",
        context={},
    )


async def test_list_sessions_with_status_filter(
    client: httpx.AsyncClient, mock_session_mgr: MagicMock,
) -> None:
    resp = await client.get("/api/sessions/?status=active&limit=10")
    assert resp.status_code == 200
    mock_session_mgr._db.list_sessions.assert_called_once_with(
        status="active", limit=10,
    )
