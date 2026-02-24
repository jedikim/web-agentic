"""E2E tests for the Evolution API — full pipeline flow.

Spins up a real FastAPI server (in-process via httpx AsyncClient),
exercises the full lifecycle: trigger → status checks → approve/reject,
scenario results, version management.

All external dependencies (LLM, browser, git) are mocked.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI

from src.api.dependencies import set_db, set_notifier
from src.api.routes import evolution, progress, scenarios, versions
from src.evolution.code_generator import CodeChange, GenerationResult, EvolutionUsage
from src.evolution.db import EvolutionDB
from src.evolution.notifier import Notifier
from src.evolution.sandbox import SandboxTestResult


# ── Fixtures ─────────────────────────────────────────


def _create_app() -> FastAPI:
    app = FastAPI()
    app.include_router(evolution.router)
    app.include_router(scenarios.router)
    app.include_router(versions.router)
    app.include_router(progress.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


_app = _create_app()


@pytest.fixture
async def db() -> AsyncIterator[EvolutionDB]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    evo_db = EvolutionDB(db_path=path)
    await evo_db.init()
    set_db(evo_db)
    yield evo_db
    await evo_db.close()
    os.unlink(path)


@pytest.fixture
def notifier() -> Notifier:
    n = Notifier()
    set_notifier(n)
    return n


@pytest.fixture
async def client(
    db: EvolutionDB, notifier: Notifier,
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── E2E: Full Evolution Lifecycle ────────────────────


async def test_full_evolution_lifecycle(
    db: EvolutionDB, client: httpx.AsyncClient, notifier: Notifier,
) -> None:
    """E2E: trigger → analyze → generate → test → approve → merge.

    This tests the complete happy path of the evolution system.
    """
    # Step 1: Seed failure patterns so analysis finds something
    await db.upsert_failure_pattern(
        pattern_key="e2e_timeout_1",
        pattern_type="timeout",
        scenario_name="e2e_test",
        phase_name="navigation",
        error_message="TimeoutError: page load timed out",
    )
    await db.upsert_failure_pattern(
        pattern_key="e2e_timeout_1",  # duplicate to bump count
        pattern_type="timeout",
        scenario_name="e2e_test",
        phase_name="navigation",
    )

    # Step 2: Setup mocks for the pipeline
    mock_changes = [CodeChange(
        file_path="src/core/executor.py",
        change_type="modify",
        new_content="# improved timeout handling\nimport asyncio\n",
        description="Increased timeout and added retry logic",
    )]
    mock_gen_result = GenerationResult(
        changes=mock_changes,
        summary="Fixed timeout issue in executor",
        usage=EvolutionUsage(),
    )
    mock_test_result = SandboxTestResult(
        lint_passed=True,
        unit_tests_passed=True,
        overall_passed=True,
        unit_tests_total=700,
        unit_tests_failed=0,
    )

    with patch("src.evolution.code_generator.EvolutionCodeGenerator.generate_fixes",
               new_callable=AsyncMock, return_value=mock_gen_result), \
         patch("src.evolution.code_generator.EvolutionCodeGenerator.get_relevant_files",
               return_value={}), \
         patch("src.evolution.sandbox.Sandbox.get_current_commit",
               new_callable=AsyncMock, return_value="abc123"), \
         patch("src.evolution.sandbox.Sandbox.create_branch",
               new_callable=AsyncMock, return_value=True), \
         patch("src.evolution.sandbox.Sandbox.apply_changes",
               new_callable=AsyncMock, return_value=["src/core/executor.py"]), \
         patch("src.evolution.sandbox.Sandbox.commit_changes",
               new_callable=AsyncMock, return_value="def456"), \
         patch("src.evolution.sandbox.Sandbox.run_full_test",
               new_callable=AsyncMock, return_value=mock_test_result), \
         patch("src.evolution.sandbox.Sandbox.get_diff",
               new_callable=AsyncMock, return_value="diff output"), \
         patch("src.evolution.sandbox.Sandbox.cleanup",
               new_callable=AsyncMock), \
         patch("src.evolution.sandbox.Sandbox.delete_branch",
               new_callable=AsyncMock), \
         patch("src.evolution.sandbox.Sandbox._run",
               new_callable=AsyncMock, return_value=(0, "abc123\n", "")):

        # Step 3: Trigger evolution
        resp = await client.post("/api/evolution/trigger", json={"reason": "e2e_test"})
        assert resp.status_code == 200
        run_id = resp.json()["data"]["run_id"]

        # Step 4: Wait for pipeline to complete (it runs as background task)
        for _ in range(50):
            await asyncio.sleep(0.1)
            run = await db.get_evolution_run(run_id)
            if run and run["status"] in ("awaiting_approval", "failed"):
                break

        # Step 5: Verify it reached awaiting_approval
        resp = await client.get(f"/api/evolution/{run_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["status"] == "awaiting_approval", f"Got status: {detail['status']}, error: {detail.get('error_message')}"
        assert detail["branch_name"] == f"evolution/{run_id}"

        # Step 6: Check changes were recorded
        assert len(detail["changes"]) == 1
        assert detail["changes"][0]["file_path"] == "src/core/executor.py"

        # Step 7: Approve — mock the merge
        with patch("src.evolution.version_manager.VersionManager.approve_and_merge",
                    new_callable=AsyncMock, return_value="0.1.1"):
            resp = await client.post(f"/api/evolution/{run_id}/approve", json={})

        assert resp.status_code == 200
        assert resp.json()["status"] == "merged"
        assert resp.json()["data"]["version"] == "0.1.1"


async def test_evolution_lifecycle_reject(
    db: EvolutionDB, client: httpx.AsyncClient, notifier: Notifier,
) -> None:
    """E2E: trigger → arrive at awaiting_approval → reject."""
    # Seed failure pattern
    await db.upsert_failure_pattern(
        pattern_key="rej_test_1",
        pattern_type="selector_not_found",
        scenario_name="reject_test",
        phase_name="click",
        error_message="Element not found",
    )

    mock_changes = [CodeChange(
        file_path="src/ai/llm_planner.py",
        change_type="modify",
        new_content="# fix",
        description="Attempted fix",
    )]
    mock_gen_result = GenerationResult(
        changes=mock_changes, summary="Fix", usage=EvolutionUsage(),
    )
    mock_test_result = SandboxTestResult(
        lint_passed=True, unit_tests_passed=True, overall_passed=True,
    )

    with patch("src.evolution.code_generator.EvolutionCodeGenerator.generate_fixes",
               new_callable=AsyncMock, return_value=mock_gen_result), \
         patch("src.evolution.code_generator.EvolutionCodeGenerator.get_relevant_files",
               return_value={}), \
         patch("src.evolution.sandbox.Sandbox.get_current_commit",
               new_callable=AsyncMock, return_value="abc"), \
         patch("src.evolution.sandbox.Sandbox.create_branch",
               new_callable=AsyncMock, return_value=True), \
         patch("src.evolution.sandbox.Sandbox.apply_changes",
               new_callable=AsyncMock, return_value=["f.py"]), \
         patch("src.evolution.sandbox.Sandbox.commit_changes",
               new_callable=AsyncMock, return_value="xyz"), \
         patch("src.evolution.sandbox.Sandbox.run_full_test",
               new_callable=AsyncMock, return_value=mock_test_result), \
         patch("src.evolution.sandbox.Sandbox.get_diff",
               new_callable=AsyncMock, return_value="diff"), \
         patch("src.evolution.sandbox.Sandbox.cleanup",
               new_callable=AsyncMock), \
         patch("src.evolution.sandbox.Sandbox.delete_branch",
               new_callable=AsyncMock):

        resp = await client.post("/api/evolution/trigger", json={"reason": "reject_e2e"})
        run_id = resp.json()["data"]["run_id"]

        for _ in range(50):
            await asyncio.sleep(0.1)
            run = await db.get_evolution_run(run_id)
            if run and run["status"] in ("awaiting_approval", "failed"):
                break

        assert run is not None
        assert run["status"] == "awaiting_approval"

        # Reject
        resp = await client.post(f"/api/evolution/{run_id}/reject", json={})
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

        # Verify DB
        updated = await db.get_evolution_run(run_id)
        assert updated is not None
        assert updated["status"] == "rejected"


# ── E2E: Scenario Results + Trends ───────────────────


async def test_scenario_results_e2e(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    """E2E: seed results → query results → check trends."""
    # Seed multiple scenario results
    for name in ["alpha", "beta"]:
        for i in range(3):
            await db.save_scenario_result(
                scenario_name=name,
                overall_success=i != 1,  # fail on index 1
                total_steps_ok=5 if i != 1 else 2,
                total_steps_all=6,
                total_cost_usd=0.05 * (i + 1),
                total_tokens=1000 * (i + 1),
                wall_time_s=10.0 * (i + 1),
                phase_details=[
                    {"phase_name": "search", "success": i != 1, "steps_ok": 3, "steps_all": 3},
                ],
                version="0.1.0",
            )

    # Query all results
    resp = await client.get("/api/scenarios/results")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 6

    # Filter by scenario
    resp = await client.get("/api/scenarios/results?scenario_name=alpha")
    assert resp.status_code == 200
    assert len(resp.json()) == 3

    # Trends
    resp = await client.get("/api/scenarios/trends")
    assert resp.status_code == 200
    trends = resp.json()
    assert len(trends) == 2
    for t in trends:
        assert t["total_runs"] == 3
        assert t["success_rate"] == pytest.approx(66.67, abs=1)


# ── E2E: Version Lifecycle ───────────────────────────


async def test_version_lifecycle_e2e(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    """E2E: create versions → list → detail → current."""
    # Default version
    resp = await client.get("/api/versions/current")
    assert resp.json()["version"] == "0.1.0"

    # Create versions
    await db.create_version_record(
        version="0.1.1",
        changelog="Fixed timeout bug",
        previous_version="0.1.0",
        git_tag="v0.1.1",
        git_commit="abc123",
    )
    await db.create_version_record(
        version="0.1.2",
        changelog="Improved selector caching",
        previous_version="0.1.1",
        git_tag="v0.1.2",
        git_commit="def456",
    )

    # Current should be latest
    resp = await client.get("/api/versions/current")
    assert resp.json()["version"] == "0.1.2"

    # List should show both, newest first
    resp = await client.get("/api/versions/")
    records = resp.json()
    assert len(records) == 2
    assert records[0]["version"] == "0.1.2"
    assert records[1]["version"] == "0.1.1"

    # Detail
    resp = await client.get("/api/versions/0.1.1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["changelog"] == "Fixed timeout bug"
    assert data["git_tag"] == "v0.1.1"


# ── E2E: SSE Event Delivery ─────────────────────────


async def test_sse_notifier_pubsub(
    db: EvolutionDB, client: httpx.AsyncClient, notifier: Notifier,
) -> None:
    """E2E: Notifier pub/sub delivers events to subscribers.

    Note: SSE HTTP streaming was verified in the live server test.
    Here we test the Notifier directly for reliable E2E coverage.
    """
    received: list[dict] = []  # type: ignore[type-arg]

    async def consumer() -> None:
        async for evt in notifier.subscribe():
            received.append({"event": evt.event, "data": evt.data})
            if len(received) >= 3:
                break

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)

    # Publish 3 different event types
    await notifier.publish("evolution_status", {"run_id": "t1", "status": "analyzing"})
    await notifier.publish("scenario_progress", {"scenario": "alpha", "status": "running"})
    await notifier.publish("version_created", {"version": "0.1.1"})

    await asyncio.wait_for(task, timeout=2.0)

    assert len(received) == 3
    assert received[0]["event"] == "evolution_status"
    assert received[0]["data"]["status"] == "analyzing"
    assert received[1]["event"] == "scenario_progress"
    assert received[1]["data"]["scenario"] == "alpha"
    assert received[2]["event"] == "version_created"
    assert received[2]["data"]["version"] == "0.1.1"

    # SSE HTTP streaming verified in live server test (scripts/start_server.py)


# ── E2E: Failure Pattern → Evolution Trigger ─────────


async def test_failure_analysis_feeds_evolution(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    """E2E: save failed scenario → analyze → verify patterns exist."""
    # Save a failed scenario result with phase details
    await db.save_scenario_result(
        scenario_name="e2e_analysis",
        overall_success=False,
        total_steps_ok=2,
        total_steps_all=5,
        phase_details=[
            {"phase_name": "search", "success": True},
            {"phase_name": "click_result", "success": False,
             "error": "SelectorNotFound: could not find element"},
            {"phase_name": "extract", "success": False, "timed_out": True},
        ],
        error_summary="click_result: 1 step(s) failed; extract: timed out",
    )

    # Run analyzer
    from src.evolution.analyzer import FailureAnalyzer
    analyzer = FailureAnalyzer(db=db)
    patterns = await analyzer.analyze_latest_results()

    # Should detect at least 2 patterns (selector_not_found + timeout)
    assert len(patterns) >= 2
    types = {p["pattern_type"] for p in patterns}
    assert "selector_not_found" in types
    assert "timeout" in types

    # Patterns should be visible via DB
    all_patterns = await db.list_failure_patterns(unresolved_only=True)
    assert len(all_patterns) >= 2


# ── E2E: Multi-evolution Tracking ────────────────────


async def test_multiple_evolutions_tracked(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    """E2E: Create multiple evolution runs and track independently."""
    # Create 3 runs with different statuses
    run1 = await db.create_evolution_run(trigger_reason="auto_batch_1")
    run2 = await db.create_evolution_run(trigger_reason="auto_batch_2")
    run3 = await db.create_evolution_run(trigger_reason="manual")

    await db.update_evolution_run(run1["id"], status="merged")
    await db.update_evolution_run(run2["id"], status="failed", error_message="test fail")

    # List all
    resp = await client.get("/api/evolution/")
    assert len(resp.json()) == 3

    # Filter by status
    resp = await client.get("/api/evolution/?status=pending")
    pending = resp.json()
    assert len(pending) == 1
    assert pending[0]["id"] == run3["id"]

    resp = await client.get("/api/evolution/?status=merged")
    assert len(resp.json()) == 1

    resp = await client.get("/api/evolution/?status=failed")
    failed = resp.json()
    assert len(failed) == 1
    assert failed[0]["error_message"] == "test fail"
