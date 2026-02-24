"""Pattern Database — tracks successful action patterns for rule promotion.

Stores patterns in SQLite via aiosqlite.  Each pattern is identified by
the hash of (intent, site, selector) and tracks success/failure counts.

Patterns that exceed configurable thresholds become candidates for
promotion to deterministic rules in the Rule Engine (see ``rule_promoter.py``).

Usage::

    db = PatternDB("data/patterns.db")
    await db.init_db()
    pattern = await db.record_success("인기순 정렬", "shopping.naver.com", "#sort-popular", "click")
    promotable = await db.get_promotable(min_success=3, min_ratio=0.8)
    await db.close()
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class Pattern:
    """A recorded action pattern with success/failure statistics.

    Attributes:
        pattern_id: Unique identifier (hash of intent + site + selector).
        intent: Natural-language intent string.
        site: Hostname or glob pattern.
        selector: CSS selector used.
        method: Interaction method (click, type, etc.).
        success_count: Number of successful executions.
        fail_count: Number of failed executions.
        last_used: ISO-8601 timestamp of last usage.
        created: ISO-8601 timestamp of creation.
        metadata: Arbitrary additional data.
    """

    pattern_id: str
    intent: str
    site: str
    selector: str
    method: str
    success_count: int = 0
    fail_count: int = 0
    last_used: str = ""
    created: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _generate_pattern_id(intent: str, site: str, selector: str) -> str:
    """Generate a deterministic pattern_id from (intent, site, selector).

    Args:
        intent: Natural-language intent.
        site: Hostname or glob.
        selector: CSS selector.

    Returns:
        A hex digest string.
    """
    raw = f"{intent}|{site}|{selector}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ── SQL constants ────────────────────────────────────

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS patterns (
    pattern_id    TEXT PRIMARY KEY,
    intent        TEXT NOT NULL,
    site          TEXT NOT NULL,
    selector      TEXT NOT NULL,
    method        TEXT NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count    INTEGER NOT NULL DEFAULT 0,
    last_used     TEXT NOT NULL,
    created       TEXT NOT NULL,
    metadata      TEXT NOT NULL DEFAULT '{}'
)
"""

_UPSERT_SUCCESS_SQL = """\
INSERT INTO patterns (pattern_id, intent, site, selector, method, success_count, fail_count, last_used, created, metadata)
VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?, '{}')
ON CONFLICT (pattern_id) DO UPDATE SET
    success_count = success_count + 1,
    last_used     = excluded.last_used
"""

_UPSERT_FAILURE_SQL = """\
INSERT INTO patterns (pattern_id, intent, site, selector, method, success_count, fail_count, last_used, created, metadata)
VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?, '{}')
ON CONFLICT (pattern_id) DO UPDATE SET
    fail_count = fail_count + 1,
    last_used  = excluded.last_used
"""

_GET_PATTERN_SQL = """\
SELECT pattern_id, intent, site, selector, method, success_count, fail_count, last_used, created, metadata
FROM patterns
WHERE intent = ? AND site = ?
ORDER BY success_count DESC
LIMIT 1
"""

_GET_PROMOTABLE_SQL = """\
SELECT pattern_id, intent, site, selector, method, success_count, fail_count, last_used, created, metadata
FROM patterns
WHERE success_count >= ?
  AND CAST(success_count AS REAL) / MAX(CAST(success_count + fail_count AS REAL), 1) >= ?
"""

_LIST_ALL_SQL = """\
SELECT pattern_id, intent, site, selector, method, success_count, fail_count, last_used, created, metadata
FROM patterns
ORDER BY success_count DESC
"""

_LIST_BY_SITE_SQL = """\
SELECT pattern_id, intent, site, selector, method, success_count, fail_count, last_used, created, metadata
FROM patterns
WHERE site = ?
ORDER BY success_count DESC
"""

_DELETE_SQL = "DELETE FROM patterns WHERE pattern_id = ?"

_GET_BY_ID_SQL = """\
SELECT pattern_id, intent, site, selector, method, success_count, fail_count, last_used, created, metadata
FROM patterns
WHERE pattern_id = ?
"""


def _row_to_pattern(row: tuple) -> Pattern:
    """Convert a database row tuple into a Pattern dataclass.

    Args:
        row: Tuple of (pattern_id, intent, site, selector, method,
             success_count, fail_count, last_used, created, metadata).

    Returns:
        A ``Pattern`` instance.
    """
    return Pattern(
        pattern_id=row[0],
        intent=row[1],
        site=row[2],
        selector=row[3],
        method=row[4],
        success_count=row[5],
        fail_count=row[6],
        last_used=row[7],
        created=row[8],
        metadata=json.loads(row[9]) if row[9] else {},
    )


class PatternDB:
    """SQLite-backed pattern database for tracking action success/failure.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path | str = "data/patterns.db") -> None:
        self._db_path = Path(db_path)
        self._initialised = False

    async def init_db(self) -> None:
        """Create the patterns table if it does not exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE_SQL)
            await db.commit()
        self._initialised = True
        logger.debug("Pattern DB initialised at %s", self._db_path)

    async def _ensure_init(self) -> None:
        """Initialise the database if not yet done."""
        if not self._initialised:
            await self.init_db()

    async def record_success(
        self, intent: str, site: str, selector: str, method: str
    ) -> Pattern:
        """Record a successful action, creating or updating the pattern.

        Args:
            intent: Natural-language intent.
            site: Hostname or glob.
            selector: CSS selector used.
            method: Interaction method (click, type, etc.).

        Returns:
            The updated ``Pattern``.
        """
        await self._ensure_init()
        pattern_id = _generate_pattern_id(intent, site, selector)
        now = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                _UPSERT_SUCCESS_SQL,
                (pattern_id, intent, site, selector, method, now, now),
            )
            await db.commit()

            cursor = await db.execute(_GET_BY_ID_SQL, (pattern_id,))
            row = await cursor.fetchone()

        assert row is not None
        return _row_to_pattern(row)

    async def record_failure(
        self, intent: str, site: str, selector: str, method: str
    ) -> Pattern:
        """Record a failed action, creating or updating the pattern.

        Args:
            intent: Natural-language intent.
            site: Hostname or glob.
            selector: CSS selector used.
            method: Interaction method (click, type, etc.).

        Returns:
            The updated ``Pattern``.
        """
        await self._ensure_init()
        pattern_id = _generate_pattern_id(intent, site, selector)
        now = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                _UPSERT_FAILURE_SQL,
                (pattern_id, intent, site, selector, method, now, now),
            )
            await db.commit()

            cursor = await db.execute(_GET_BY_ID_SQL, (pattern_id,))
            row = await cursor.fetchone()

        assert row is not None
        return _row_to_pattern(row)

    async def get_pattern(self, intent: str, site: str) -> Pattern | None:
        """Look up the best pattern for a given intent and site.

        Args:
            intent: Natural-language intent.
            site: Hostname or glob.

        Returns:
            The best matching ``Pattern``, or ``None`` if not found.
        """
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(_GET_PATTERN_SQL, (intent, site))
            row = await cursor.fetchone()

        if row is None:
            return None
        return _row_to_pattern(row)

    async def get_promotable(
        self, min_success: int = 3, min_ratio: float = 0.8
    ) -> list[Pattern]:
        """Return patterns that meet promotion thresholds.

        Args:
            min_success: Minimum number of successes required.
            min_ratio: Minimum success ratio (success / total).

        Returns:
            List of promotable ``Pattern`` instances.
        """
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                _GET_PROMOTABLE_SQL, (min_success, min_ratio)
            )
            rows = await cursor.fetchall()

        return [_row_to_pattern(row) for row in rows]

    async def list_patterns(self, site: str | None = None) -> list[Pattern]:
        """List all stored patterns, optionally filtered by site.

        Args:
            site: If provided, only return patterns for this site.

        Returns:
            List of ``Pattern`` instances sorted by success_count descending.
        """
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            if site is not None:
                cursor = await db.execute(_LIST_BY_SITE_SQL, (site,))
            else:
                cursor = await db.execute(_LIST_ALL_SQL)
            rows = await cursor.fetchall()

        return [_row_to_pattern(row) for row in rows]

    async def delete_pattern(self, pattern_id: str) -> bool:
        """Delete a pattern by its ID.

        Args:
            pattern_id: The pattern identifier to delete.

        Returns:
            ``True`` if a row was deleted, ``False`` otherwise.
        """
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(_DELETE_SQL, (pattern_id,))
            await db.commit()
            return cursor.rowcount > 0  # type: ignore[return-value]

    async def close(self) -> None:
        """Close the database (no-op for aiosqlite per-call connections).

        Provided for protocol compatibility and future connection pooling.
        """
        logger.debug("Pattern DB closed")
