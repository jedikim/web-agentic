"""Unit tests for the Evolution DB module."""
from __future__ import annotations

import os
import tempfile

import pytest

from src.evolution.db import EvolutionDB


@pytest.fixture
async def db():
    """Create a temporary DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    evo_db = EvolutionDB(db_path=path)
    await evo_db.init()
    yield evo_db
    await evo_db.close()
    os.unlink(path)


# ── Evolution Runs ───────────────────────────────────


async def test_create_evolution_run(db: EvolutionDB) -> None:
    run = await db.create_evolution_run(
        trigger_reason="manual",
        trigger_data={"scenario_filter": "test"},
    )
    assert run["id"]
    assert run["status"] == "pending"
    assert run["trigger_reason"] == "manual"


async def test_get_evolution_run(db: EvolutionDB) -> None:
    run = await db.create_evolution_run(trigger_reason="auto")
    fetched = await db.get_evolution_run(run["id"])
    assert fetched is not None
    assert fetched["id"] == run["id"]


async def test_get_evolution_run_not_found(db: EvolutionDB) -> None:
    result = await db.get_evolution_run("nonexistent")
    assert result is None


async def test_list_evolution_runs(db: EvolutionDB) -> None:
    await db.create_evolution_run(trigger_reason="a")
    await db.create_evolution_run(trigger_reason="b")
    runs = await db.list_evolution_runs()
    assert len(runs) == 2


async def test_list_evolution_runs_by_status(db: EvolutionDB) -> None:
    run = await db.create_evolution_run(trigger_reason="x")
    await db.update_evolution_run(run["id"], status="analyzing")
    pending = await db.list_evolution_runs(status="pending")
    analyzing = await db.list_evolution_runs(status="analyzing")
    assert len(pending) == 0
    assert len(analyzing) == 1


async def test_update_evolution_run(db: EvolutionDB) -> None:
    run = await db.create_evolution_run(trigger_reason="test")
    updated = await db.update_evolution_run(
        run["id"],
        status="analyzing",
        branch_name="evolution/abc",
        analysis_summary="Found 2 patterns",
    )
    assert updated is not None
    assert updated["status"] == "analyzing"
    assert updated["branch_name"] == "evolution/abc"


async def test_update_ignores_unknown_fields(db: EvolutionDB) -> None:
    run = await db.create_evolution_run(trigger_reason="test")
    updated = await db.update_evolution_run(run["id"], unknown_field="bad")
    assert updated is not None
    assert updated["status"] == "pending"  # unchanged


# ── Evolution Changes ────────────────────────────────


async def test_add_and_get_changes(db: EvolutionDB) -> None:
    run = await db.create_evolution_run(trigger_reason="test")
    await db.add_evolution_change(
        evolution_run_id=run["id"],
        file_path="src/core/executor.py",
        change_type="modify",
        description="Fixed timeout handling",
        new_content="# new content",
    )
    await db.add_evolution_change(
        evolution_run_id=run["id"],
        file_path="src/ai/llm_planner.py",
        change_type="modify",
        description="Improved parsing",
    )
    changes = await db.get_evolution_changes(run["id"])
    assert len(changes) == 2
    assert changes[0]["file_path"] == "src/core/executor.py"


# ── Version Records ──────────────────────────────────


async def test_create_version_record(db: EvolutionDB) -> None:
    rec = await db.create_version_record(
        version="0.1.1",
        changelog="Fixed bugs",
        previous_version="0.1.0",
        git_tag="v0.1.1",
    )
    assert rec["version"] == "0.1.1"
    assert rec["changelog"] == "Fixed bugs"


async def test_get_version_record(db: EvolutionDB) -> None:
    await db.create_version_record(version="0.2.0", changelog="New feature")
    rec = await db.get_version_record("0.2.0")
    assert rec is not None
    assert rec["version"] == "0.2.0"


async def test_get_latest_version_default(db: EvolutionDB) -> None:
    version = await db.get_latest_version()
    assert version == "0.1.0"


async def test_get_latest_version(db: EvolutionDB) -> None:
    await db.create_version_record(version="0.1.1", changelog="a")
    await db.create_version_record(version="0.1.2", changelog="b")
    version = await db.get_latest_version()
    assert version == "0.1.2"


async def test_list_version_records(db: EvolutionDB) -> None:
    await db.create_version_record(version="0.1.1", changelog="a")
    await db.create_version_record(version="0.1.2", changelog="b")
    records = await db.list_version_records()
    assert len(records) == 2
    # Most recent first
    assert records[0]["version"] == "0.1.2"


# ── Scenario Results ─────────────────────────────────


async def test_save_and_list_scenario_results(db: EvolutionDB) -> None:
    await db.save_scenario_result(
        scenario_name="family_outing",
        overall_success=True,
        total_steps_ok=5,
        total_steps_all=6,
        total_cost_usd=0.15,
        total_tokens=5000,
        wall_time_s=30.5,
        phase_details=[{"phase_name": "search", "success": True}],
    )
    results = await db.list_scenario_results()
    assert len(results) == 1
    assert results[0]["scenario_name"] == "family_outing"
    assert results[0]["overall_success"] is True
    assert results[0]["phase_details"][0]["phase_name"] == "search"


async def test_list_scenario_results_filtered(db: EvolutionDB) -> None:
    await db.save_scenario_result(scenario_name="a", overall_success=True)
    await db.save_scenario_result(scenario_name="b", overall_success=False)
    a_results = await db.list_scenario_results(scenario_name="a")
    assert len(a_results) == 1
    assert a_results[0]["scenario_name"] == "a"


async def test_get_scenario_trends(db: EvolutionDB) -> None:
    for i in range(5):
        await db.save_scenario_result(
            scenario_name="test",
            overall_success=i % 2 == 0,
            total_cost_usd=0.1,
            wall_time_s=10.0,
        )
    trends = await db.get_scenario_trends()
    assert len(trends) == 1
    assert trends[0]["scenario_name"] == "test"
    assert trends[0]["total_runs"] == 5
    assert trends[0]["successes"] == 3  # indices 0, 2, 4


# ── Failure Patterns ─────────────────────────────────


async def test_upsert_failure_pattern(db: EvolutionDB) -> None:
    p = await db.upsert_failure_pattern(
        pattern_key="test_key",
        pattern_type="timeout",
        scenario_name="test",
        phase_name="search",
        error_message="Timed out",
    )
    assert p["occurrence_count"] == 1

    # Upsert again — should increment
    p2 = await db.upsert_failure_pattern(
        pattern_key="test_key",
        pattern_type="timeout",
        scenario_name="test",
        phase_name="search",
    )
    assert p2["occurrence_count"] == 2


async def test_list_failure_patterns_unresolved(db: EvolutionDB) -> None:
    await db.upsert_failure_pattern(
        pattern_key="key1", pattern_type="timeout",
        scenario_name="a", phase_name="p1",
    )
    await db.upsert_failure_pattern(
        pattern_key="key2", pattern_type="selector_not_found",
        scenario_name="b", phase_name="p2",
    )
    patterns = await db.list_failure_patterns(unresolved_only=True)
    assert len(patterns) == 2


async def test_resolve_failure_patterns(db: EvolutionDB) -> None:
    await db.upsert_failure_pattern(
        pattern_key="key1", pattern_type="timeout",
        scenario_name="a", phase_name="p1",
    )
    resolved = await db.resolve_failure_patterns(["key1"], "0.1.1")
    assert resolved == 1

    patterns = await db.list_failure_patterns(unresolved_only=True)
    assert len(patterns) == 0


async def test_resolve_empty_list(db: EvolutionDB) -> None:
    resolved = await db.resolve_failure_patterns([], "0.1.1")
    assert resolved == 0
