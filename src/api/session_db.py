"""Session DB — schema and CRUD operations for browser automation sessions.

Uses aiosqlite following the same pattern as ``src/evolution/db.py``.
Stores sessions and their turns in a separate ``sessions.db`` file.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

# ── Defaults ─────────────────────────────────────────

DEFAULT_DB_PATH = "data/sessions.db"

# ── SQL Schema ───────────────────────────────────────

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'active',
    initial_url    TEXT,
    current_url    TEXT,
    total_cost_usd REAL NOT NULL DEFAULT 0.0,
    total_tokens   INTEGER NOT NULL DEFAULT 0,
    turn_count     INTEGER NOT NULL DEFAULT 0,
    context        TEXT NOT NULL DEFAULT '{}',
    headless       INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    last_activity  TEXT NOT NULL,
    closed_at      TEXT
);

CREATE TABLE IF NOT EXISTS session_turns (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(id),
    turn_num     INTEGER NOT NULL,
    intent       TEXT NOT NULL,
    success      INTEGER NOT NULL DEFAULT 0,
    cost_usd     REAL NOT NULL DEFAULT 0.0,
    tokens_used  INTEGER NOT NULL DEFAULT 0,
    steps_total  INTEGER NOT NULL DEFAULT 0,
    steps_ok     INTEGER NOT NULL DEFAULT 0,
    error_msg    TEXT,
    screenshots  TEXT NOT NULL DEFAULT '[]',
    step_details TEXT NOT NULL DEFAULT '[]',
    started_at   TEXT NOT NULL,
    completed_at TEXT
);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class SessionDB:
    """Async wrapper around the sessions SQLite database."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Create tables if needed and open the connection."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_CREATE_TABLES_SQL)
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        """Return the active database connection."""
        assert self._db is not None, "Call init() first"
        return self._db

    # ── Sessions ─────────────────────────────────────

    async def create_session(
        self,
        *,
        headless: bool = True,
        initial_url: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new session record.

        Args:
            headless: Whether the browser runs headless.
            initial_url: Optional starting URL.
            context: Optional JSON metadata.

        Returns:
            The created session as a dict.
        """
        session_id = _new_id()
        now = _now_iso()
        await self.db.execute(
            """INSERT INTO sessions
               (id, status, initial_url, current_url, headless, context,
                created_at, last_activity)
               VALUES (?, 'active', ?, ?, ?, ?, ?, ?)""",
            (session_id, initial_url, initial_url, int(headless),
             json.dumps(context or {}), now, now),
        )
        await self.db.commit()
        return await self.get_session(session_id)  # type: ignore[return-value]

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get a session by ID.

        Args:
            session_id: The session ID.

        Returns:
            Session dict or None if not found.
        """
        cursor = await self.db.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["context"] = json.loads(d["context"])
        d["headless"] = bool(d["headless"])
        return d

    async def list_sessions(
        self, status: str | None = None, limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List sessions, optionally filtered by status.

        Args:
            status: Filter by session status (active, idle, closed, expired).
            limit: Maximum number of results.

        Returns:
            List of session dicts.
        """
        if status:
            cursor = await self.db.execute(
                "SELECT * FROM sessions WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = [dict(r) for r in await cursor.fetchall()]
        for r in rows:
            r["context"] = json.loads(r["context"])
            r["headless"] = bool(r["headless"])
        return rows

    async def update_session(
        self, session_id: str, **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Update session fields.

        Args:
            session_id: The session ID.
            **kwargs: Fields to update (status, current_url, total_cost_usd,
                      total_tokens, turn_count, context).

        Returns:
            Updated session dict or None if not found.
        """
        allowed = {
            "status", "current_url", "total_cost_usd", "total_tokens",
            "turn_count", "context", "closed_at",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return await self.get_session(session_id)
        # Serialize context to JSON if provided
        if "context" in updates and isinstance(updates["context"], dict):
            updates["context"] = json.dumps(updates["context"])
        updates["last_activity"] = _now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [session_id]
        await self.db.execute(
            f"UPDATE sessions SET {set_clause} WHERE id = ?",  # noqa: S608
            values,
        )
        await self.db.commit()
        return await self.get_session(session_id)

    async def close_session(self, session_id: str) -> dict[str, Any] | None:
        """Mark a session as closed.

        Args:
            session_id: The session ID.

        Returns:
            Updated session dict or None if not found.
        """
        session = await self.get_session(session_id)
        if session is None:
            return None
        now = _now_iso()
        await self.db.execute(
            "UPDATE sessions SET status = 'closed', closed_at = ?, last_activity = ? WHERE id = ?",
            (now, now, session_id),
        )
        await self.db.commit()
        return await self.get_session(session_id)

    # ── Session Turns ────────────────────────────────

    async def create_turn(
        self, session_id: str, intent: str,
    ) -> dict[str, Any]:
        """Create a new turn for a session.

        Args:
            session_id: The owning session ID.
            intent: The user intent for this turn.

        Returns:
            The created turn as a dict.
        """
        # Get current turn count
        cursor = await self.db.execute(
            "SELECT turn_count FROM sessions WHERE id = ?", (session_id,),
        )
        row = await cursor.fetchone()
        turn_num = (row["turn_count"] + 1) if row else 1

        turn_id = _new_id()
        now = _now_iso()
        await self.db.execute(
            """INSERT INTO session_turns
               (id, session_id, turn_num, intent, started_at)
               VALUES (?, ?, ?, ?, ?)""",
            (turn_id, session_id, turn_num, intent, now),
        )
        # Update session turn count and activity
        await self.db.execute(
            "UPDATE sessions SET turn_count = ?, last_activity = ? WHERE id = ?",
            (turn_num, now, session_id),
        )
        await self.db.commit()
        return {
            "id": turn_id,
            "session_id": session_id,
            "turn_num": turn_num,
            "intent": intent,
            "success": False,
            "cost_usd": 0.0,
            "tokens_used": 0,
            "steps_total": 0,
            "steps_ok": 0,
            "error_msg": None,
            "screenshots": [],
            "step_details": [],
            "started_at": now,
            "completed_at": None,
        }

    async def complete_turn(
        self,
        turn_id: str,
        *,
        success: bool,
        cost_usd: float = 0.0,
        tokens_used: int = 0,
        steps_total: int = 0,
        steps_ok: int = 0,
        error_msg: str | None = None,
        screenshots: list[str] | None = None,
        step_details: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Complete a turn with results.

        Args:
            turn_id: The turn ID to complete.
            success: Whether the turn succeeded.
            cost_usd: Cost in USD.
            tokens_used: Tokens consumed.
            steps_total: Total steps attempted.
            steps_ok: Steps that succeeded.
            error_msg: Error message if failed.
            screenshots: List of screenshot file paths.
            step_details: List of step result dicts.

        Returns:
            Updated turn dict or None if not found.
        """
        now = _now_iso()
        await self.db.execute(
            """UPDATE session_turns SET
               success = ?, cost_usd = ?, tokens_used = ?,
               steps_total = ?, steps_ok = ?, error_msg = ?,
               screenshots = ?, step_details = ?, completed_at = ?
               WHERE id = ?""",
            (int(success), cost_usd, tokens_used, steps_total, steps_ok,
             error_msg, json.dumps(screenshots or []),
             json.dumps(step_details or []), now, turn_id),
        )
        await self.db.commit()

        cursor = await self.db.execute(
            "SELECT * FROM session_turns WHERE id = ?", (turn_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["success"] = bool(d["success"])
        d["screenshots"] = json.loads(d["screenshots"])
        d["step_details"] = json.loads(d["step_details"])
        return d

    async def get_session_turns(
        self, session_id: str,
    ) -> list[dict[str, Any]]:
        """Get all turns for a session.

        Args:
            session_id: The session ID.

        Returns:
            List of turn dicts ordered by turn_num.
        """
        cursor = await self.db.execute(
            "SELECT * FROM session_turns WHERE session_id = ? ORDER BY turn_num",
            (session_id,),
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        for r in rows:
            r["success"] = bool(r["success"])
            r["screenshots"] = json.loads(r["screenshots"])
            r["step_details"] = json.loads(r["step_details"])
        return rows

    # ── Expiry ───────────────────────────────────────

    async def expire_idle_sessions(
        self, idle_minutes: int = 30,
    ) -> list[str]:
        """Expire sessions idle for longer than the threshold.

        Args:
            idle_minutes: Minutes of inactivity before expiry.

        Returns:
            List of expired session IDs.
        """
        cutoff = (
            datetime.now(UTC) - timedelta(minutes=idle_minutes)
        ).isoformat(timespec="seconds")
        now = _now_iso()

        cursor = await self.db.execute(
            """SELECT id FROM sessions
               WHERE status = 'active' AND last_activity < ?""",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        expired_ids = [row["id"] for row in rows]

        if expired_ids:
            placeholders = ",".join("?" for _ in expired_ids)
            await self.db.execute(
                f"""UPDATE sessions SET status = 'expired', closed_at = ?
                    WHERE id IN ({placeholders})""",  # noqa: S608
                [now, *expired_ids],
            )
            await self.db.commit()

        return expired_ids
