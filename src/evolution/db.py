"""Evolution DB — schema and CRUD operations for the self-evolving engine.

Uses aiosqlite following the same pattern as ``src/learning/pattern_db.py``.
Stores evolution runs, code changes, version records, scenario results,
and failure patterns in a separate ``evolution.db`` file.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

# ── Defaults ─────────────────────────────────────────

DEFAULT_DB_PATH = "data/evolution.db"

# ── SQL Schema ───────────────────────────────────────

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS evolution_runs (
    id              TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'pending',
    trigger_reason  TEXT NOT NULL,
    trigger_data    TEXT NOT NULL DEFAULT '{}',
    branch_name     TEXT,
    base_commit     TEXT,
    analysis_summary TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    completed_at    TEXT,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS evolution_changes (
    id                TEXT PRIMARY KEY,
    evolution_run_id  TEXT NOT NULL REFERENCES evolution_runs(id),
    file_path         TEXT NOT NULL,
    change_type       TEXT NOT NULL,
    diff_content      TEXT,
    new_content       TEXT,
    description       TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS version_records (
    id                TEXT PRIMARY KEY,
    version           TEXT NOT NULL UNIQUE,
    previous_version  TEXT,
    evolution_run_id  TEXT REFERENCES evolution_runs(id),
    changelog         TEXT NOT NULL,
    test_results      TEXT NOT NULL DEFAULT '{}',
    git_tag           TEXT,
    git_commit        TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenario_results (
    id              TEXT PRIMARY KEY,
    scenario_name   TEXT NOT NULL,
    version         TEXT,
    overall_success INTEGER NOT NULL,
    total_steps_ok  INTEGER NOT NULL DEFAULT 0,
    total_steps_all INTEGER NOT NULL DEFAULT 0,
    total_cost_usd  REAL NOT NULL DEFAULT 0.0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    wall_time_s     REAL NOT NULL DEFAULT 0.0,
    phase_details   TEXT NOT NULL DEFAULT '[]',
    error_summary   TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS failure_patterns (
    id               TEXT PRIMARY KEY,
    pattern_key      TEXT NOT NULL UNIQUE,
    pattern_type     TEXT NOT NULL,
    scenario_name    TEXT NOT NULL,
    phase_name       TEXT NOT NULL,
    failure_code     TEXT,
    error_message    TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    first_seen       TEXT NOT NULL,
    last_seen        TEXT NOT NULL,
    resolved_in_version TEXT
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class EvolutionDB:
    """Async wrapper around the evolution SQLite database."""

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
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Call init() first"
        return self._db

    # ── Evolution Runs ───────────────────────────────

    async def create_evolution_run(
        self,
        trigger_reason: str,
        trigger_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new evolution run record."""
        run_id = _new_id()
        now = _now_iso()
        await self.db.execute(
            """INSERT INTO evolution_runs
               (id, status, trigger_reason, trigger_data, created_at, updated_at)
               VALUES (?, 'pending', ?, ?, ?, ?)""",
            (run_id, trigger_reason, json.dumps(trigger_data or {}), now, now),
        )
        await self.db.commit()
        return await self.get_evolution_run(run_id)  # type: ignore[return-value]

    async def get_evolution_run(self, run_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT * FROM evolution_runs WHERE id = ?", (run_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_evolution_runs(
        self, limit: int = 50, status: str | None = None,
    ) -> list[dict[str, Any]]:
        if status:
            cursor = await self.db.execute(
                "SELECT * FROM evolution_runs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM evolution_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in await cursor.fetchall()]

    async def update_evolution_run(
        self, run_id: str, **kwargs: Any,
    ) -> dict[str, Any] | None:
        allowed = {
            "status", "branch_name", "base_commit", "analysis_summary",
            "completed_at", "error_message",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return await self.get_evolution_run(run_id)
        updates["updated_at"] = _now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [run_id]
        await self.db.execute(
            f"UPDATE evolution_runs SET {set_clause} WHERE id = ?",  # noqa: S608
            values,
        )
        await self.db.commit()
        return await self.get_evolution_run(run_id)

    # ── Evolution Changes ────────────────────────────

    async def add_evolution_change(
        self,
        evolution_run_id: str,
        file_path: str,
        change_type: str,
        description: str,
        diff_content: str | None = None,
        new_content: str | None = None,
    ) -> dict[str, Any]:
        change_id = _new_id()
        now = _now_iso()
        await self.db.execute(
            """INSERT INTO evolution_changes
               (id, evolution_run_id, file_path, change_type, diff_content,
                new_content, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (change_id, evolution_run_id, file_path, change_type,
             diff_content, new_content, description, now),
        )
        await self.db.commit()
        return {
            "id": change_id, "evolution_run_id": evolution_run_id,
            "file_path": file_path, "change_type": change_type,
            "diff_content": diff_content, "new_content": new_content,
            "description": description, "created_at": now,
        }

    async def get_evolution_changes(self, run_id: str) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM evolution_changes WHERE evolution_run_id = ? ORDER BY created_at",
            (run_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    # ── Version Records ──────────────────────────────

    async def create_version_record(
        self,
        version: str,
        changelog: str,
        previous_version: str | None = None,
        evolution_run_id: str | None = None,
        test_results: dict[str, Any] | None = None,
        git_tag: str | None = None,
        git_commit: str | None = None,
    ) -> dict[str, Any]:
        vid = _new_id()
        now = _now_iso()
        await self.db.execute(
            """INSERT INTO version_records
               (id, version, previous_version, evolution_run_id, changelog,
                test_results, git_tag, git_commit, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (vid, version, previous_version, evolution_run_id, changelog,
             json.dumps(test_results or {}), git_tag, git_commit, now),
        )
        await self.db.commit()
        return {
            "id": vid, "version": version, "previous_version": previous_version,
            "evolution_run_id": evolution_run_id, "changelog": changelog,
            "test_results": test_results or {}, "git_tag": git_tag,
            "git_commit": git_commit, "created_at": now,
        }

    async def get_version_record(self, version: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT * FROM version_records WHERE version = ?", (version,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["test_results"] = json.loads(d["test_results"])
        return d

    async def list_version_records(self, limit: int = 50) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM version_records ORDER BY rowid DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        for r in rows:
            r["test_results"] = json.loads(r["test_results"])
        return rows

    async def get_latest_version(self) -> str:
        """Return the latest version string, or '0.1.0' if none."""
        cursor = await self.db.execute(
            "SELECT version FROM version_records ORDER BY rowid DESC LIMIT 1",
        )
        row = await cursor.fetchone()
        return row["version"] if row else "0.1.0"

    # ── Scenario Results ─────────────────────────────

    async def save_scenario_result(
        self,
        scenario_name: str,
        overall_success: bool,
        total_steps_ok: int = 0,
        total_steps_all: int = 0,
        total_cost_usd: float = 0.0,
        total_tokens: int = 0,
        wall_time_s: float = 0.0,
        phase_details: list[dict[str, Any]] | None = None,
        error_summary: str | None = None,
        version: str | None = None,
    ) -> dict[str, Any]:
        rid = _new_id()
        now = _now_iso()
        await self.db.execute(
            """INSERT INTO scenario_results
               (id, scenario_name, version, overall_success, total_steps_ok,
                total_steps_all, total_cost_usd, total_tokens, wall_time_s,
                phase_details, error_summary, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rid, scenario_name, version, int(overall_success), total_steps_ok,
             total_steps_all, total_cost_usd, total_tokens, wall_time_s,
             json.dumps(phase_details or []), error_summary, now),
        )
        await self.db.commit()
        return {
            "id": rid, "scenario_name": scenario_name, "version": version,
            "overall_success": overall_success, "total_steps_ok": total_steps_ok,
            "total_steps_all": total_steps_all, "total_cost_usd": total_cost_usd,
            "total_tokens": total_tokens, "wall_time_s": wall_time_s,
            "phase_details": phase_details or [], "error_summary": error_summary,
            "created_at": now,
        }

    async def list_scenario_results(
        self, scenario_name: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        if scenario_name:
            cursor = await self.db.execute(
                """SELECT * FROM scenario_results
                   WHERE scenario_name = ? ORDER BY created_at DESC LIMIT ?""",
                (scenario_name, limit),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM scenario_results ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = [dict(r) for r in await cursor.fetchall()]
        for r in rows:
            r["phase_details"] = json.loads(r["phase_details"])
            r["overall_success"] = bool(r["overall_success"])
        return rows

    async def get_scenario_trends(self) -> list[dict[str, Any]]:
        """Aggregate success rate per scenario (last 10 runs each)."""
        cursor = await self.db.execute(
            """SELECT scenario_name,
                      COUNT(*) as total_runs,
                      SUM(overall_success) as successes,
                      AVG(total_cost_usd) as avg_cost,
                      AVG(wall_time_s) as avg_time
               FROM (
                   SELECT *, ROW_NUMBER() OVER (
                       PARTITION BY scenario_name ORDER BY created_at DESC
                   ) as rn FROM scenario_results
               ) WHERE rn <= 10
               GROUP BY scenario_name
               ORDER BY scenario_name""",
        )
        return [dict(r) for r in await cursor.fetchall()]

    # ── Failure Patterns ─────────────────────────────

    async def upsert_failure_pattern(
        self,
        pattern_key: str,
        pattern_type: str,
        scenario_name: str,
        phase_name: str,
        failure_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        now = _now_iso()
        pid = _new_id()
        await self.db.execute(
            """INSERT INTO failure_patterns
               (id, pattern_key, pattern_type, scenario_name, phase_name,
                failure_code, error_message, occurrence_count, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
               ON CONFLICT(pattern_key) DO UPDATE SET
                   occurrence_count = occurrence_count + 1,
                   last_seen = excluded.last_seen,
                   error_message = COALESCE(excluded.error_message, error_message)""",
            (pid, pattern_key, pattern_type, scenario_name, phase_name,
             failure_code, error_message, now, now),
        )
        await self.db.commit()
        cursor = await self.db.execute(
            "SELECT * FROM failure_patterns WHERE pattern_key = ?", (pattern_key,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}

    async def list_failure_patterns(
        self, unresolved_only: bool = True, min_occurrences: int = 1,
    ) -> list[dict[str, Any]]:
        if unresolved_only:
            cursor = await self.db.execute(
                """SELECT * FROM failure_patterns
                   WHERE resolved_in_version IS NULL
                     AND occurrence_count >= ?
                   ORDER BY occurrence_count DESC""",
                (min_occurrences,),
            )
        else:
            cursor = await self.db.execute(
                """SELECT * FROM failure_patterns
                   WHERE occurrence_count >= ?
                   ORDER BY occurrence_count DESC""",
                (min_occurrences,),
            )
        return [dict(r) for r in await cursor.fetchall()]

    async def resolve_failure_patterns(
        self, pattern_keys: list[str], version: str,
    ) -> int:
        """Mark patterns as resolved in a given version. Returns count updated."""
        if not pattern_keys:
            return 0
        placeholders = ",".join("?" for _ in pattern_keys)
        cursor = await self.db.execute(
            f"""UPDATE failure_patterns SET resolved_in_version = ?
                WHERE pattern_key IN ({placeholders})""",  # noqa: S608
            [version, *pattern_keys],
        )
        await self.db.commit()
        return cursor.rowcount
