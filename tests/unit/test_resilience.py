"""Tests for src.core.resilience — ResilienceOrchestrator."""
from __future__ import annotations

import asyncio

import pytest

from src.core.resilience import (
    ResilienceOrchestrator,
    ScenarioOutcome,
    ScenarioTask,
)


@pytest.mark.asyncio
async def test_all_pass() -> None:
    """All tasks pass -> failed_count=0."""

    async def runner(task: ScenarioTask) -> ScenarioOutcome:
        return ScenarioOutcome(task.scenario_id, task.workflow_id, "pass")

    orch = ResilienceOrchestrator(max_concurrent=3)
    tasks = [ScenarioTask("s1", "w1"), ScenarioTask("s2", "w2")]
    report = await orch.run_all(tasks, runner)
    assert report.failed_count == 0
    assert len(report.results) == 2


@pytest.mark.asyncio
async def test_some_fail() -> None:
    """Some tasks fail -> correct count."""

    async def runner(task: ScenarioTask) -> ScenarioOutcome:
        if task.scenario_id == "s2":
            raise ValueError("boom")
        return ScenarioOutcome(task.scenario_id, task.workflow_id, "pass")

    orch = ResilienceOrchestrator()
    tasks = [ScenarioTask("s1", "w1"), ScenarioTask("s2", "w2")]
    report = await orch.run_all(tasks, runner)
    assert report.failed_count == 1


@pytest.mark.asyncio
async def test_recover_called_on_failure() -> None:
    """Recovery callback is invoked on failure."""
    recovered: list[str] = []

    async def runner(task: ScenarioTask) -> ScenarioOutcome:
        raise ValueError("fail")

    async def recover(task: ScenarioTask, exc: Exception) -> ScenarioOutcome | None:
        recovered.append(task.scenario_id)
        return ScenarioOutcome(task.scenario_id, task.workflow_id, "pass")

    orch = ResilienceOrchestrator()
    report = await orch.run_all([ScenarioTask("s1", "w1")], runner, recover)
    assert "s1" in recovered
    assert report.recovered_count == 1


@pytest.mark.asyncio
async def test_recover_success() -> None:
    """Successful recovery -> recovered=True."""

    async def runner(task: ScenarioTask) -> ScenarioOutcome:
        raise ValueError("fail")

    async def recover(task: ScenarioTask, exc: Exception) -> ScenarioOutcome | None:
        return ScenarioOutcome(task.scenario_id, task.workflow_id, "pass")

    orch = ResilienceOrchestrator()
    report = await orch.run_all([ScenarioTask("s1", "w1")], runner, recover)
    assert report.results[0].recovered is True
    assert report.results[0].recovery_ms is not None


@pytest.mark.asyncio
async def test_recover_failure() -> None:
    """Failed recovery -> status=fail."""

    async def runner(task: ScenarioTask) -> ScenarioOutcome:
        raise ValueError("fail")

    async def recover(task: ScenarioTask, exc: Exception) -> ScenarioOutcome | None:
        raise RuntimeError("recovery failed too")

    orch = ResilienceOrchestrator()
    report = await orch.run_all([ScenarioTask("s1", "w1")], runner, recover)
    assert report.results[0].status == "fail"
    assert report.results[0].recovered is False


@pytest.mark.asyncio
async def test_max_concurrent_limit() -> None:
    """Concurrency is limited by max_concurrent."""
    active: list[int] = []
    max_active = 0

    async def runner(task: ScenarioTask) -> ScenarioOutcome:
        nonlocal max_active
        active.append(1)
        current = len(active)
        if current > max_active:
            max_active = current
        await asyncio.sleep(0.05)
        active.pop()
        return ScenarioOutcome(task.scenario_id, task.workflow_id, "pass")

    orch = ResilienceOrchestrator(max_concurrent=2)
    tasks = [ScenarioTask(f"s{i}", f"w{i}") for i in range(5)]
    await orch.run_all(tasks, runner)
    assert max_active <= 2


@pytest.mark.asyncio
async def test_rollback_entries_logged() -> None:
    """Failed scenarios generate rollback entries."""

    async def runner(task: ScenarioTask) -> ScenarioOutcome:
        raise ValueError("boom")

    orch = ResilienceOrchestrator()
    report = await orch.run_all([ScenarioTask("s1", "w1")], runner)
    assert len(report.rollback_entries) == 1
    assert report.rollback_entries[0].change_id == "s1"


@pytest.mark.asyncio
async def test_empty_tasks() -> None:
    """Empty task list -> empty report."""

    async def runner(task: ScenarioTask) -> ScenarioOutcome:
        return ScenarioOutcome(task.scenario_id, task.workflow_id, "pass")

    orch = ResilienceOrchestrator()
    report = await orch.run_all([], runner)
    assert report.failed_count == 0
    assert len(report.results) == 0


@pytest.mark.asyncio
async def test_no_recover_callback() -> None:
    """No recover callback -> failure not recovered."""

    async def runner(task: ScenarioTask) -> ScenarioOutcome:
        raise ValueError("fail")

    orch = ResilienceOrchestrator()
    report = await orch.run_all([ScenarioTask("s1", "w1")], runner, recover=None)
    assert report.failed_count == 1
    assert report.recovered_count == 0


@pytest.mark.asyncio
async def test_mixed_pass_fail_recover() -> None:
    """Mix of pass, fail, and recovered scenarios."""

    async def runner(task: ScenarioTask) -> ScenarioOutcome:
        if task.scenario_id == "s2":
            raise ValueError("fail-s2")
        if task.scenario_id == "s3":
            raise ValueError("fail-s3")
        return ScenarioOutcome(task.scenario_id, task.workflow_id, "pass")

    async def recover(task: ScenarioTask, exc: Exception) -> ScenarioOutcome | None:
        if task.scenario_id == "s2":
            return ScenarioOutcome(task.scenario_id, task.workflow_id, "pass")
        return None  # s3 not recoverable

    orch = ResilienceOrchestrator()
    tasks = [ScenarioTask("s1", "w1"), ScenarioTask("s2", "w2"), ScenarioTask("s3", "w3")]
    report = await orch.run_all(tasks, runner, recover)
    assert report.recovered_count == 1
    # s3 should still be fail since recover returned None
