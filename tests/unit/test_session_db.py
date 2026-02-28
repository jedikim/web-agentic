"""Tests for SessionDB — session and turn CRUD operations."""
from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from src.api.session_db import SessionDB


@pytest_asyncio.fixture
async def db() -> SessionDB:
    """Create a SessionDB using a temporary file."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "test_sessions.db")
        sdb = SessionDB(db_path=db_path)
        await sdb.init()
        yield sdb
        await sdb.close()


@pytest.mark.asyncio
async def test_create_and_get_session(db: SessionDB) -> None:
    """Creating a session should return it with correct defaults."""
    session = await db.create_session(
        headless=True,
        initial_url="https://example.com",
        context={"source": "test"},
    )
    assert session["status"] == "active"
    assert session["initial_url"] == "https://example.com"
    assert session["current_url"] == "https://example.com"
    assert session["headless"] is True
    assert session["total_cost_usd"] == 0.0
    assert session["total_tokens"] == 0
    assert session["turn_count"] == 0
    assert session["context"] == {"source": "test"}
    assert session["closed_at"] is None

    # get_session should return the same data
    fetched = await db.get_session(session["id"])
    assert fetched is not None
    assert fetched["id"] == session["id"]
    assert fetched["context"] == {"source": "test"}

    # Non-existent session returns None
    assert await db.get_session("nonexistent") is None


@pytest.mark.asyncio
async def test_list_sessions_with_filter(db: SessionDB) -> None:
    """list_sessions should filter by status when provided."""
    s1 = await db.create_session(headless=True)
    s2 = await db.create_session(headless=False)
    await db.close_session(s2["id"])

    all_sessions = await db.list_sessions()
    assert len(all_sessions) == 2

    active = await db.list_sessions(status="active")
    assert len(active) == 1
    assert active[0]["id"] == s1["id"]

    closed = await db.list_sessions(status="closed")
    assert len(closed) == 1
    assert closed[0]["id"] == s2["id"]


@pytest.mark.asyncio
async def test_close_session(db: SessionDB) -> None:
    """close_session should set status to closed and record closed_at."""
    session = await db.create_session(headless=True)
    closed = await db.close_session(session["id"])
    assert closed is not None
    assert closed["status"] == "closed"
    assert closed["closed_at"] is not None

    # Closing non-existent session returns None
    assert await db.close_session("nonexistent") is None


@pytest.mark.asyncio
async def test_create_and_complete_turn(db: SessionDB) -> None:
    """Create and complete a turn, verifying all fields."""
    session = await db.create_session(headless=True)
    turn = await db.create_turn(session["id"], "Search for Python")

    assert turn["session_id"] == session["id"]
    assert turn["turn_num"] == 1
    assert turn["intent"] == "Search for Python"
    assert turn["success"] is False
    assert turn["screenshots"] == []
    assert turn["step_details"] == []

    completed = await db.complete_turn(
        turn["id"],
        success=True,
        cost_usd=0.01,
        tokens_used=500,
        steps_total=3,
        steps_ok=3,
        screenshots=["screenshot1.png"],
        step_details=[{"step": "step_1", "ok": True}],
    )
    assert completed is not None
    assert completed["success"] is True
    assert completed["cost_usd"] == 0.01
    assert completed["tokens_used"] == 500
    assert completed["steps_total"] == 3
    assert completed["steps_ok"] == 3
    assert completed["screenshots"] == ["screenshot1.png"]
    assert completed["step_details"] == [{"step": "step_1", "ok": True}]
    assert completed["completed_at"] is not None

    # Completing non-existent turn returns None
    assert await db.complete_turn("nonexistent", success=False) is None


@pytest.mark.asyncio
async def test_get_session_turns(db: SessionDB) -> None:
    """get_session_turns should return all turns ordered by turn_num."""
    session = await db.create_session(headless=True)
    _ = await db.create_turn(session["id"], "Step 1")
    _ = await db.create_turn(session["id"], "Step 2")
    _ = await db.create_turn(session["id"], "Step 3")

    turns = await db.get_session_turns(session["id"])
    assert len(turns) == 3
    assert turns[0]["turn_num"] == 1
    assert turns[1]["turn_num"] == 2
    assert turns[2]["turn_num"] == 3

    # Session turn_count should be updated
    updated = await db.get_session(session["id"])
    assert updated is not None
    assert updated["turn_count"] == 3


@pytest.mark.asyncio
async def test_expire_idle_sessions(db: SessionDB) -> None:
    """expire_idle_sessions should expire sessions idle past threshold."""
    session = await db.create_session(headless=True)

    # Manually set last_activity to 60 minutes ago
    old_time = (
        datetime.now(UTC) - timedelta(minutes=60)
    ).isoformat(timespec="seconds")
    await db.db.execute(
        "UPDATE sessions SET last_activity = ? WHERE id = ?",
        (old_time, session["id"]),
    )
    await db.db.commit()

    expired = await db.expire_idle_sessions(idle_minutes=30)
    assert session["id"] in expired

    updated = await db.get_session(session["id"])
    assert updated is not None
    assert updated["status"] == "expired"

    # A recently active session should not expire
    active = await db.create_session(headless=True)
    expired2 = await db.expire_idle_sessions(idle_minutes=30)
    assert active["id"] not in expired2


@pytest.mark.asyncio
async def test_update_session(db: SessionDB) -> None:
    """update_session should update allowed fields."""
    session = await db.create_session(
        headless=True, context={"initial": True},
    )
    updated = await db.update_session(
        session["id"],
        current_url="https://example.com/page2",
        total_cost_usd=0.05,
        total_tokens=1000,
        turn_count=5,
        context={"updated": True},
    )
    assert updated is not None
    assert updated["current_url"] == "https://example.com/page2"
    assert updated["total_cost_usd"] == 0.05
    assert updated["total_tokens"] == 1000
    assert updated["turn_count"] == 5
    assert updated["context"] == {"updated": True}

    # Updating non-allowed fields should be ignored
    updated2 = await db.update_session(session["id"], id="hacked")
    assert updated2 is not None
    assert updated2["id"] == session["id"]

    # Updating with no kwargs should return the session unchanged
    unchanged = await db.update_session(session["id"])
    assert unchanged is not None
    assert unchanged["id"] == session["id"]
