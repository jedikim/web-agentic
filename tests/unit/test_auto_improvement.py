"""Unit tests for the Auto-Improvement Orchestrator."""
from __future__ import annotations

from unittest.mock import AsyncMock

from src.evolution.auto_improvement import (
    AutoImprovementOrchestrator,
    RunFailure,
    infer_trigger_from_failures,
)

# ── infer_trigger_from_failures ──────────────────────


async def test_infer_trigger_selector_not_found() -> None:
    failures = [RunFailure(code="SelectorNotFound", message="element not found")]
    assert infer_trigger_from_failures(failures) == "exception"


async def test_infer_trigger_visual_ambiguity() -> None:
    failures = [RunFailure(code="VisualAmbiguity", message="multiple matches")]
    assert infer_trigger_from_failures(failures) == "exception"


async def test_infer_trigger_auth_blocked() -> None:
    failures = [RunFailure(code="AuthBlocked", message="login required")]
    assert infer_trigger_from_failures(failures) == "exception"


async def test_infer_trigger_unknown_code_is_bug() -> None:
    failures = [RunFailure(code="TimeoutError", message="timed out")]
    assert infer_trigger_from_failures(failures) == "bug"


async def test_infer_trigger_mixed_defaults_to_exception() -> None:
    """If any failure is an exception code, the trigger should be 'exception'."""
    failures = [
        RunFailure(code="TimeoutError"),
        RunFailure(code="SelectorNotFound"),
    ]
    assert infer_trigger_from_failures(failures) == "exception"


# ── handle_outcome — gate checks ────────────────────


async def test_disabled_returns_not_triggered() -> None:
    orch = AutoImprovementOrchestrator(enabled=False)
    result = await orch.handle_outcome(
        workflow_id="w1", status="fail", failures=[],
    )
    assert result.triggered is False
    assert result.reason == "disabled"


async def test_status_not_in_trigger_list() -> None:
    orch = AutoImprovementOrchestrator(enabled=True)
    result = await orch.handle_outcome(
        workflow_id="w1", status="success", failures=[],
    )
    assert result.triggered is False
    assert "not in trigger statuses" in (result.reason or "")


async def test_fail_status_triggers() -> None:
    orch = AutoImprovementOrchestrator(enabled=True)
    result = await orch.handle_outcome(
        workflow_id="w1",
        status="fail",
        failures=[RunFailure(code="SelectorNotFound")],
    )
    assert result.triggered is True
    assert result.trigger == "exception"


# ── Dry-run mode (no service) ───────────────────────


async def test_no_service_dry_run() -> None:
    orch = AutoImprovementOrchestrator(evolution_service=None, enabled=True)
    result = await orch.handle_outcome(
        workflow_id="w1",
        status="fail",
        failures=[RunFailure(code="TimeoutError")],
    )
    assert result.triggered is True
    assert result.trigger == "bug"
    assert result.job_id is None
    assert "dry-run" in (result.reason or "")


# ── With evolution service ──────────────────────────


async def test_service_trigger_evolution_called() -> None:
    service = AsyncMock()
    service.trigger_evolution = AsyncMock(return_value="job-42")

    orch = AutoImprovementOrchestrator(evolution_service=service, enabled=True)
    result = await orch.handle_outcome(
        workflow_id="w1",
        status="fail",
        failures=[RunFailure(code="SelectorNotFound", message="not found")],
        run_artifact="/tmp/run.json",
    )

    assert result.triggered is True
    assert result.job_id == "job-42"
    assert result.trigger == "exception"
    service.trigger_evolution.assert_awaited_once_with(
        "w1",
        "exception",
        failures=[{"code": "SelectorNotFound", "message": "not found"}],
        run_artifact="/tmp/run.json",
    )


async def test_auto_approve_flag() -> None:
    service = AsyncMock()
    service.trigger_evolution = AsyncMock(return_value="job-99")
    service.approve_job = AsyncMock()

    orch = AutoImprovementOrchestrator(
        evolution_service=service, enabled=True, auto_approve=True,
    )
    result = await orch.handle_outcome(
        workflow_id="w1",
        status="fail",
        failures=[RunFailure(code="SelectorNotFound")],
    )

    assert result.triggered is True
    assert result.auto_approved is True
    assert result.job_id == "job-99"
    service.approve_job.assert_awaited_once_with("job-99")


async def test_auto_approve_false_does_not_approve() -> None:
    service = AsyncMock()
    service.trigger_evolution = AsyncMock(return_value="job-50")
    service.approve_job = AsyncMock()

    orch = AutoImprovementOrchestrator(
        evolution_service=service, enabled=True, auto_approve=False,
    )
    result = await orch.handle_outcome(
        workflow_id="w1",
        status="fail",
        failures=[RunFailure(code="SelectorNotFound")],
    )

    assert result.triggered is True
    assert result.auto_approved is False
    service.approve_job.assert_not_awaited()


# ── Custom trigger statuses ─────────────────────────


async def test_custom_trigger_statuses() -> None:
    orch = AutoImprovementOrchestrator(
        enabled=True, trigger_statuses=["fail", "partial"],
    )

    # "partial" is in the custom list → should trigger
    result = await orch.handle_outcome(
        workflow_id="w1",
        status="partial",
        failures=[RunFailure(code="TimeoutError")],
    )
    assert result.triggered is True
    assert result.trigger == "bug"

    # "success" is NOT in the custom list → should not trigger
    result2 = await orch.handle_outcome(
        workflow_id="w2",
        status="success",
        failures=[],
    )
    assert result2.triggered is False
