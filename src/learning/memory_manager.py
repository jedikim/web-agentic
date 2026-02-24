"""4-layer Memory Manager for the adaptive web automation engine.

Implements the ``IMemoryManager`` protocol with four tiers:

- **Working Memory** — ephemeral ``dict`` scoped to a single step.
- **Episode Memory** — per-task JSON files in ``data/episodes/``.
- **Policy Memory** — persistent SQLite table in ``data/policy.db``.
- **Artifact Memory** — binary files in ``data/artifacts/`` with TTL cleanup.

Usage::

    mgr = await create_memory_manager("data")
    mgr.set_working("current_url", "https://example.com")
    await mgr.save_episode("task-1", {"status": "running"})
    await mgr.save_policy(rule, success_count=5)
    await mgr.save_artifact("task-1", "screenshot.png", raw_bytes)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import aiosqlite

from src.core.types import RuleDefinition, RuleMatch


# ── SQL constants ────────────────────────────────────

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS policies (
    intent      TEXT    NOT NULL,
    site        TEXT    NOT NULL,
    rule_id     TEXT    NOT NULL,
    selector    TEXT    NOT NULL,
    method      TEXT    NOT NULL,
    arguments   TEXT    NOT NULL DEFAULT '[]',
    success_count INTEGER NOT NULL DEFAULT 0,
    last_used   TEXT    NOT NULL,
    PRIMARY KEY (intent, site)
)
"""

_UPSERT_SQL = """\
INSERT INTO policies (intent, site, rule_id, selector, method, arguments, success_count, last_used)
VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
ON CONFLICT (intent, site) DO UPDATE SET
    rule_id       = excluded.rule_id,
    selector      = excluded.selector,
    method        = excluded.method,
    arguments     = excluded.arguments,
    success_count = excluded.success_count,
    last_used     = excluded.last_used
"""

_QUERY_SQL = """\
SELECT rule_id, selector, method, arguments, success_count
FROM policies
WHERE intent = ? AND site = ?
ORDER BY success_count DESC
LIMIT 1
"""

_DELETE_SQL = "DELETE FROM policies WHERE intent = ? AND site = ?"


# ── MemoryManager ────────────────────────────────────

class MemoryManager:
    """4-layer memory system satisfying ``IMemoryManager``.

    Args:
        data_dir: Root directory for persistent storage.  Subdirectories
            ``episodes/`` and ``artifacts/`` are created automatically.
    """

    def __init__(self, data_dir: Path | str = "data") -> None:
        self._data_dir = Path(data_dir)
        self._working: dict[str, Any] = {}

        # Persistent paths
        self._episodes_dir = self._data_dir / "episodes"
        self._artifacts_dir = self._data_dir / "artifacts"
        self._db_path = self._data_dir / "policy.db"

        # Ensure directories exist
        self._episodes_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

        self._db_initialised = False

    # ── Layer 1: Working Memory ──────────────────────

    def get_working(self, key: str) -> Any:
        """Return a value from working memory, or ``None`` if absent.

        Args:
            key: The lookup key.

        Returns:
            The stored value or ``None``.
        """
        return self._working.get(key)

    def set_working(self, key: str, value: Any) -> None:
        """Store a value in working memory.

        Args:
            key: The lookup key.
            value: The value to store.
        """
        self._working[key] = value

    def clear_working(self) -> None:
        """Clear all working memory (typically called between steps)."""
        self._working.clear()

    # ── Layer 2: Episode Memory ──────────────────────

    def _episode_path(self, task_id: str) -> Path:
        """Return the JSON file path for a given task."""
        return self._episodes_dir / f"{task_id}.json"

    async def save_episode(self, task_id: str, data: dict[str, Any]) -> None:
        """Persist episode data as a JSON file.

        Args:
            task_id: Unique task identifier.
            data: Arbitrary task metadata to persist.
        """
        path = self._episode_path(task_id)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    async def load_episode(self, task_id: str) -> dict[str, Any] | None:
        """Load episode data from disk.

        Args:
            task_id: Unique task identifier.

        Returns:
            The stored dict, or ``None`` if the episode does not exist.
        """
        path = self._episode_path(task_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]

    async def list_episodes(self) -> list[str]:
        """List all stored episode task IDs.

        Returns:
            Sorted list of task_id strings.
        """
        return sorted(
            p.stem for p in self._episodes_dir.glob("*.json")
        )

    async def delete_episode(self, task_id: str) -> bool:
        """Delete an episode file.

        Args:
            task_id: Unique task identifier.

        Returns:
            ``True`` if the file was deleted, ``False`` if it did not exist.
        """
        path = self._episode_path(task_id)
        if path.exists():
            path.unlink()
            return True
        return False

    # ── Layer 3: Policy Memory (SQLite) ──────────────

    async def _ensure_db(self) -> None:
        """Create the policies table if it does not yet exist."""
        if self._db_initialised:
            return
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE_SQL)
            await db.commit()
        self._db_initialised = True

    async def save_policy(self, rule: RuleDefinition, success_count: int) -> None:
        """Upsert a policy rule into SQLite.

        Args:
            rule: The rule definition to store.
            success_count: Number of times this rule has succeeded.
        """
        await self._ensure_db()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                _UPSERT_SQL,
                (
                    rule.intent_pattern,
                    rule.site_pattern,
                    rule.rule_id,
                    rule.selector,
                    rule.method,
                    json.dumps(rule.arguments),
                    success_count,
                ),
            )
            await db.commit()

    async def query_policy(self, intent: str, site: str) -> RuleMatch | None:
        """Query for the best matching policy.

        Performs an exact match on ``(intent, site)`` and returns the row
        with the highest ``success_count``.

        Args:
            intent: The user intent string.
            site: The site pattern to match.

        Returns:
            A ``RuleMatch`` or ``None`` if no match found.
        """
        await self._ensure_db()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(_QUERY_SQL, (intent, site))
            row = await cursor.fetchone()
            if row is None:
                return None
            rule_id, selector, method, arguments_json, success_count = row
            return RuleMatch(
                rule_id=rule_id,
                selector=selector,
                method=method,
                arguments=json.loads(arguments_json),
                confidence=min(1.0, success_count / 10.0),
            )

    async def delete_policy(self, intent: str, site: str) -> bool:
        """Delete a policy entry.

        Args:
            intent: The intent key.
            site: The site pattern key.

        Returns:
            ``True`` if a row was deleted, ``False`` otherwise.
        """
        await self._ensure_db()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(_DELETE_SQL, (intent, site))
            await db.commit()
            return cursor.rowcount > 0  # type: ignore[return-value]

    # ── Layer 4: Artifact Memory (filesystem) ────────

    def _artifact_dir(self, task_id: str) -> Path:
        """Return the artifacts subdirectory for a given task."""
        return self._artifacts_dir / task_id

    async def save_artifact(self, task_id: str, name: str, data: bytes) -> Path:
        """Store a binary artifact on disk.

        Args:
            task_id: Owning task identifier.
            name: File name (e.g. ``"screenshot.png"``).
            data: Raw binary content.

        Returns:
            The absolute ``Path`` where the artifact was saved.
        """
        directory = self._artifact_dir(task_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(data)
        return path

    async def load_artifact(self, task_id: str, name: str) -> bytes | None:
        """Load a binary artifact from disk.

        Args:
            task_id: Owning task identifier.
            name: File name.

        Returns:
            Raw bytes, or ``None`` if the artifact does not exist.
        """
        path = self._artifact_dir(task_id) / name
        if not path.exists():
            return None
        return path.read_bytes()

    async def list_artifacts(self, task_id: str) -> list[str]:
        """List all artifact names for a given task.

        Args:
            task_id: Owning task identifier.

        Returns:
            Sorted list of file names.
        """
        directory = self._artifact_dir(task_id)
        if not directory.exists():
            return []
        return sorted(p.name for p in directory.iterdir() if p.is_file())

    async def delete_expired(self, max_age_hours: int = 24) -> int:
        """Delete artifacts older than *max_age_hours*.

        Args:
            max_age_hours: Maximum allowed age in hours.

        Returns:
            Number of files deleted.
        """
        cutoff = time.time() - (max_age_hours * 3600)
        deleted = 0

        if not self._artifacts_dir.exists():
            return 0

        for task_dir in self._artifacts_dir.iterdir():
            if not task_dir.is_dir():
                continue
            for artifact in task_dir.iterdir():
                if artifact.is_file() and artifact.stat().st_mtime < cutoff:
                    artifact.unlink()
                    deleted += 1
            # Remove the task directory if it is now empty
            if task_dir.is_dir() and not any(task_dir.iterdir()):
                task_dir.rmdir()

        return deleted


# ── Factory ──────────────────────────────────────────

async def create_memory_manager(data_dir: str = "data") -> MemoryManager:
    """Create and initialise a ``MemoryManager``.

    This factory ensures the SQLite schema is ready before returning.

    Args:
        data_dir: Root directory for persistent storage.

    Returns:
        A fully initialised ``MemoryManager`` instance.
    """
    mgr = MemoryManager(data_dir=data_dir)
    await mgr._ensure_db()
    return mgr
