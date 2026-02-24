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

            # Migration: add keywords_json column if missing
            cursor = await db.execute(
                "PRAGMA table_info(execution_traces)"
            )
            columns = {row[1] for row in await cursor.fetchall()}
            if "keywords_json" not in columns:
                await db.execute(
                    "ALTER TABLE execution_traces ADD COLUMN keywords_json TEXT DEFAULT '[]'"
                )
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

    async def record_with_keywords(
        self,
        site: str,
        intent: str,
        steps: list[object],
        cost: float,
        success: bool,
        keywords: list[str] | None = None,
    ) -> int:
        """Record an execution trace with extracted keywords.

        Args:
            site: Hostname of the target site.
            intent: Natural language intent string.
            steps: List of step data (will be JSON-serialized).
            cost: Total cost in USD.
            success: Whether the execution succeeded.
            keywords: Extracted keywords for fuzzy matching.

        Returns:
            The trace ID.
        """
        kw_json = json.dumps(sorted(keywords)) if keywords else "[]"
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "INSERT INTO execution_traces "
                "(site, intent, steps_json, cost, success, keywords_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (site, intent, json.dumps(steps, default=str), cost, int(success), kw_json),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def find_similar_fuzzy(
        self,
        site: str,
        keywords: list[str],
        min_successes: int = 2,
        similarity_threshold: float = 0.5,
    ) -> tuple[list[object], str, float] | None:
        """Find cached steps using keyword-based fuzzy matching.

        Searches successful traces for the given site and computes
        Jaccard similarity between keyword sets.

        Args:
            site: Hostname of the target site.
            keywords: Current intent keywords.
            min_successes: Minimum successful traces for a candidate.
            similarity_threshold: Minimum Jaccard similarity.

        Returns:
            Tuple of (steps, original_intent, similarity) or None.
        """
        kw_set = frozenset(keywords)
        if not kw_set:
            return None

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT intent, steps_json, keywords_json FROM execution_traces "
                "WHERE site = ? AND success = 1 "
                "ORDER BY id DESC",
                (site,),
            )
            rows = await cursor.fetchall()

        # Group by intent, find best fuzzy match
        best_sim = 0.0
        best_steps: list[object] | None = None
        best_intent = ""

        intent_counts: dict[str, int] = {}
        intent_data: dict[str, tuple[list[object], frozenset[str]]] = {}

        for intent_str, steps_json, kw_json in rows:
            intent_counts[intent_str] = intent_counts.get(intent_str, 0) + 1
            if intent_str not in intent_data:
                try:
                    cached_kw = frozenset(json.loads(kw_json)) if kw_json else frozenset()
                except (json.JSONDecodeError, TypeError):
                    cached_kw = frozenset()
                intent_data[intent_str] = (json.loads(steps_json), cached_kw)

        for intent_str, (steps, cached_kw) in intent_data.items():
            if intent_counts.get(intent_str, 0) < min_successes:
                continue
            if not cached_kw:
                continue
            # Jaccard similarity
            intersection = kw_set & cached_kw
            union = kw_set | cached_kw
            sim = len(intersection) / len(union) if union else 0.0
            if sim > best_sim:
                best_sim = sim
                best_steps = steps
                best_intent = intent_str

        if best_sim < similarity_threshold or best_steps is None:
            return None

        return (best_steps, best_intent, best_sim)

    async def close(self) -> None:
        """No-op for connection-per-call pattern."""
