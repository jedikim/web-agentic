"""Unit tests for the Evolution pipeline state machine."""
from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.evolution.code_generator import CodeChange, GenerationResult, EvolutionUsage
from src.evolution.db import EvolutionDB
from src.evolution.notifier import Notifier
from src.evolution.pipeline import EvolutionPipeline
from src.evolution.sandbox import SandboxTestResult


@pytest.fixture
async def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    evo_db = EvolutionDB(db_path=path)
    await evo_db.init()
    yield evo_db
    await evo_db.close()
    os.unlink(path)


@pytest.fixture
def notifier():
    n = Notifier()
    n.publish = AsyncMock()  # type: ignore[method-assign]
    return n


@pytest.fixture
def pipeline(db: EvolutionDB, notifier: Notifier):
    return EvolutionPipeline(db=db, notifier=notifier)


# ── State Transitions ────────────────────────────────


async def test_transition_updates_status(
    db: EvolutionDB, pipeline: EvolutionPipeline,
) -> None:
    run = await db.create_evolution_run(trigger_reason="test")
    await pipeline._transition(run["id"], "analyzing")
    updated = await db.get_evolution_run(run["id"])
    assert updated is not None
    assert updated["status"] == "analyzing"


async def test_transition_publishes_event(
    db: EvolutionDB, pipeline: EvolutionPipeline, notifier: Notifier,
) -> None:
    run = await db.create_evolution_run(trigger_reason="test")
    await pipeline._transition(run["id"], "generating")
    notifier.publish.assert_called()  # type: ignore[union-attr]
    call_args = notifier.publish.call_args  # type: ignore[union-attr]
    assert call_args[0][0] == "evolution_status"
    assert call_args[0][1]["status"] == "generating"


async def test_transition_sets_completed_at_on_final_states(
    db: EvolutionDB, pipeline: EvolutionPipeline,
) -> None:
    run = await db.create_evolution_run(trigger_reason="test")
    await pipeline._transition(run["id"], "failed", error_message="oops")
    updated = await db.get_evolution_run(run["id"])
    assert updated is not None
    assert updated["completed_at"] is not None
    assert updated["error_message"] == "oops"


# ── Pipeline: No Patterns ────────────────────────────


async def test_execute_no_patterns(
    db: EvolutionDB, pipeline: EvolutionPipeline,
) -> None:
    """Pipeline should fail gracefully when no patterns exist."""
    run = await db.create_evolution_run(trigger_reason="test")

    # Mock analyzer to return empty
    with patch.object(pipeline._analyzer, "get_top_patterns", new_callable=AsyncMock) as mock_top, \
         patch.object(pipeline._analyzer, "analyze_run_log", new_callable=AsyncMock) as mock_log:
        mock_top.return_value = []
        mock_log.return_value = []
        await pipeline.execute(run["id"])

    updated = await db.get_evolution_run(run["id"])
    assert updated is not None
    assert updated["status"] == "failed"
    assert "No failure patterns" in (updated["error_message"] or "")


# ── Pipeline: No Code Generated ──────────────────────


async def test_execute_no_code_changes(
    db: EvolutionDB, pipeline: EvolutionPipeline,
) -> None:
    """Pipeline fails when LLM generates no changes."""
    run = await db.create_evolution_run(trigger_reason="test")

    mock_patterns = [{"pattern_type": "timeout", "scenario_name": "x", "phase_name": "y"}]

    with patch.object(pipeline._analyzer, "get_top_patterns", new_callable=AsyncMock) as mock_top, \
         patch.object(pipeline._generator, "generate_fixes", new_callable=AsyncMock) as mock_gen, \
         patch.object(pipeline._generator, "get_relevant_files") as mock_files:
        mock_top.return_value = mock_patterns
        mock_files.return_value = {}
        mock_gen.return_value = GenerationResult(
            changes=[], summary="No changes", usage=EvolutionUsage(),
        )
        await pipeline.execute(run["id"])

    updated = await db.get_evolution_run(run["id"])
    assert updated is not None
    assert updated["status"] == "failed"
    assert "no code changes" in (updated["error_message"] or "").lower()


# ── Pipeline: Successful Run to AWAITING_APPROVAL ────


async def test_execute_success_to_awaiting(
    db: EvolutionDB, pipeline: EvolutionPipeline,
) -> None:
    """Pipeline runs through analysis → generation → testing → awaiting_approval."""
    run = await db.create_evolution_run(trigger_reason="test")

    mock_patterns = [{"pattern_type": "timeout", "scenario_name": "x", "phase_name": "y"}]
    mock_changes = [CodeChange(
        file_path="src/core/executor.py",
        change_type="modify",
        new_content="# fixed",
        description="Fixed timeout",
    )]
    mock_gen_result = GenerationResult(
        changes=mock_changes, summary="Fixed timeout", usage=EvolutionUsage(),
    )
    mock_test_result = SandboxTestResult(
        lint_passed=True, unit_tests_passed=True, overall_passed=True,
        unit_tests_total=100, unit_tests_failed=0,
    )

    with patch.object(pipeline._analyzer, "get_top_patterns", new_callable=AsyncMock) as mock_top, \
         patch.object(pipeline._generator, "generate_fixes", new_callable=AsyncMock) as mock_gen, \
         patch.object(pipeline._generator, "get_relevant_files") as mock_files, \
         patch.object(pipeline._sandbox, "get_current_commit", new_callable=AsyncMock) as mock_commit, \
         patch.object(pipeline._sandbox, "create_branch", new_callable=AsyncMock) as mock_branch, \
         patch.object(pipeline._sandbox, "apply_changes", new_callable=AsyncMock) as mock_apply, \
         patch.object(pipeline._sandbox, "commit_changes", new_callable=AsyncMock) as mock_cc, \
         patch.object(pipeline._sandbox, "run_full_test", new_callable=AsyncMock) as mock_test, \
         patch.object(pipeline._sandbox, "get_diff", new_callable=AsyncMock) as mock_diff, \
         patch.object(pipeline._sandbox, "cleanup", new_callable=AsyncMock):
        mock_top.return_value = mock_patterns
        mock_files.return_value = {}
        mock_gen.return_value = mock_gen_result
        mock_commit.return_value = "abc123"
        mock_branch.return_value = True
        mock_apply.return_value = ["src/core/executor.py"]
        mock_cc.return_value = "def456"
        mock_test.return_value = mock_test_result
        mock_diff.return_value = "diff content"

        await pipeline.execute(run["id"])

    updated = await db.get_evolution_run(run["id"])
    assert updated is not None
    assert updated["status"] == "awaiting_approval"
    assert updated["branch_name"] == f"evolution/{run['id']}"

    # Changes should be in DB
    changes = await db.get_evolution_changes(run["id"])
    assert len(changes) == 1


# ── Pipeline: Test Failure → Retry ───────────────────


async def test_execute_test_failure_retries(
    db: EvolutionDB, pipeline: EvolutionPipeline,
) -> None:
    """Pipeline retries once on test failure, then fails."""
    run = await db.create_evolution_run(trigger_reason="test")

    mock_patterns = [{"pattern_type": "timeout", "scenario_name": "x", "phase_name": "y"}]
    mock_changes = [CodeChange(
        file_path="src/test.py", change_type="modify",
        new_content="# bad", description="Bad fix",
    )]
    mock_gen_result = GenerationResult(
        changes=mock_changes, summary="Attempted fix", usage=EvolutionUsage(),
    )
    mock_test_fail = SandboxTestResult(
        lint_passed=True, unit_tests_passed=False, overall_passed=False,
        unit_tests_total=100, unit_tests_failed=5,
    )

    call_count = 0

    async def mock_get_top(*args, **kwargs):
        return mock_patterns

    async def mock_gen(*args, **kwargs):
        return mock_gen_result

    async def mock_create_branch(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return True

    with patch.object(pipeline._analyzer, "get_top_patterns", side_effect=mock_get_top), \
         patch.object(pipeline._generator, "generate_fixes", side_effect=mock_gen), \
         patch.object(pipeline._generator, "get_relevant_files", return_value={}), \
         patch.object(pipeline._sandbox, "get_current_commit", new_callable=AsyncMock, return_value="abc"), \
         patch.object(pipeline._sandbox, "create_branch", side_effect=mock_create_branch), \
         patch.object(pipeline._sandbox, "apply_changes", new_callable=AsyncMock, return_value=["f.py"]), \
         patch.object(pipeline._sandbox, "commit_changes", new_callable=AsyncMock, return_value="xyz"), \
         patch.object(pipeline._sandbox, "run_full_test", new_callable=AsyncMock, return_value=mock_test_fail), \
         patch.object(pipeline._sandbox, "cleanup", new_callable=AsyncMock), \
         patch.object(pipeline._sandbox, "delete_branch", new_callable=AsyncMock):

        await pipeline.execute(run["id"])

    # Should have tried twice (original + 1 retry)
    assert call_count == 2

    updated = await db.get_evolution_run(run["id"])
    assert updated is not None
    assert updated["status"] == "failed"
    assert "failed after" in (updated["error_message"] or "").lower()


# ── Pipeline: Exception Handling ─────────────────────


async def test_execute_handles_exceptions(
    db: EvolutionDB, pipeline: EvolutionPipeline,
) -> None:
    """Pipeline catches exceptions and sets status to failed."""
    run = await db.create_evolution_run(trigger_reason="test")

    with patch.object(
        pipeline._analyzer, "get_top_patterns",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        await pipeline.execute(run["id"])

    updated = await db.get_evolution_run(run["id"])
    assert updated is not None
    assert updated["status"] == "failed"
    assert "boom" in (updated["error_message"] or "")


# ── Notifier ─────────────────────────────────────────


async def test_notifier_subscribe_and_publish() -> None:
    """Test notifier pub/sub works."""
    notifier = Notifier()

    received: list = []

    async def consumer():
        async for evt in notifier.subscribe():
            received.append(evt)
            if len(received) >= 2:
                break

    import asyncio
    task = asyncio.create_task(consumer())

    await asyncio.sleep(0.05)
    await notifier.publish("test_event", {"key": "value1"})
    await notifier.publish("test_event", {"key": "value2"})

    await asyncio.wait_for(task, timeout=2.0)

    assert len(received) == 2
    assert received[0].event == "test_event"
    assert received[0].data == {"key": "value1"}


# ── Analyzer ─────────────────────────────────────────


async def test_analyzer_classify_errors() -> None:
    from src.evolution.analyzer import _classify_error

    assert _classify_error("SelectorNotFound: element not found") == "selector_not_found"
    assert _classify_error("TimeoutError: operation timed out") == "timeout"
    assert _classify_error("json.decoder.JSONDecodeError") == "parse_error"
    assert _classify_error("BudgetExceeded: over limit") == "budget_exceeded"
    assert _classify_error("Something completely unknown") == "unknown"


async def test_analyzer_analyze_latest(db: EvolutionDB) -> None:
    from src.evolution.analyzer import FailureAnalyzer

    # Add a failed scenario result
    await db.save_scenario_result(
        scenario_name="test_scenario",
        overall_success=False,
        phase_details=[
            {"phase_name": "search", "success": False, "error": "TimeoutError: timed out"},
            {"phase_name": "navigate", "success": True},
        ],
        error_summary="search: 1 step(s) failed",
    )

    analyzer = FailureAnalyzer(db=db)
    patterns = await analyzer.analyze_latest_results()
    assert len(patterns) >= 1
    assert any(p.get("pattern_type") == "timeout" for p in patterns)
