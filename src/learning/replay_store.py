"""Execution history store for adaptive replay caching.

Records execution traces (site, intent, steps, cost, success) and
provides lookup for repeated intents to skip LLM planning.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import aiosqlite


@dataclass(frozen=True)
class AdaptiveConfig:
    """Configuration for adaptive replay caching.

    Attributes:
        min_successes: Minimum successful traces before using cached steps.
        enabled: Whether adaptive caching is active.
    """

    min_successes: int = 3
    enabled: bool = True


class ReplayStore:
    """aiosqlite-based execution history store."""

    def __init__(self, db_path: str = "data/replay.db") -> None:
        self._db_path = db_path

    async def init(self) -> None:
        """Create execution_traces table if not exists."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS execution_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    cost REAL NOT NULL DEFAULT 0.0,
                    success INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_traces_site_intent
                ON execution_traces(site, intent)
            """)
            await db.commit()

    async def record(
        self,
        site: str,
        intent: str,
        steps: list[object],
        cost: float,
        success: bool,
    ) -> int:
        """Record an execution trace.

        Args:
            site: Hostname of the target site.
            intent: Natural language intent string.
            steps: List of step data (will be JSON-serialized).
            cost: Total cost in USD.
            success: Whether the execution succeeded.

        Returns:
            The trace ID.
        """
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "INSERT INTO execution_traces "
                "(site, intent, steps_json, cost, success) VALUES (?, ?, ?, ?, ?)",
                (site, intent, json.dumps(steps, default=str), cost, int(success)),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def find_similar(
        self,
        site: str,
        intent: str,
        min_successes: int = 3,
    ) -> list[object] | None:
        """Find cached steps for a similar successful execution.

        Returns steps from the most recent successful trace if at least
        ``min_successes`` successful traces exist. Returns ``None`` otherwise.

        Args:
            site: Hostname of the target site.
            intent: Natural language intent string.
            min_successes: Required successful trace count.

        Returns:
            Deserialized steps list, or ``None`` if not enough history.
        """
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM execution_traces "
                "WHERE site = ? AND intent = ? AND success = 1",
                (site, intent),
            )
            row = await cursor.fetchone()
            if not row or row[0] < min_successes:
                return None

            cursor = await db.execute(
                "SELECT steps_json FROM execution_traces "
                "WHERE site = ? AND intent = ? AND success = 1 "
                "ORDER BY id DESC LIMIT 1",
                (site, intent),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return json.loads(row[0])  # type: ignore[no-any-return]

    async def get_success_rate(self, site: str, intent: str) -> tuple[int, int]:
        """Get (success_count, total_count) for site+intent.

        Args:
            site: Hostname of the target site.
            intent: Natural language intent string.

        Returns:
            Tuple of (success_count, total_count).
        """
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT SUM(success), COUNT(*) FROM execution_traces "
                "WHERE site = ? AND intent = ?",
                (site, intent),
            )
            row = await cursor.fetchone()
            if not row or row[1] == 0:
                return (0, 0)
            return (row[0] or 0, row[1])

    async def close(self) -> None:
        """No-op for connection-per-call pattern."""
