"""Resilience Orchestrator — parallel scenario execution with recovery and rollback logging."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ScenarioTask:
    """A scenario to execute."""

    scenario_id: str
    workflow_id: str


@dataclass
class ScenarioOutcome:
    """Result of executing a single scenario."""

    scenario_id: str
    workflow_id: str
    status: str  # "pass" | "fail"
    recovered: bool = False
    reason: str | None = None
    recovery_ms: float | None = None


@dataclass
class RollbackEntry:
    """Record of a rollback action."""

    change_id: str
    reason: str
    timestamp: str


@dataclass
class ResilienceReport:
    """Aggregate report from running all scenarios."""

    results: list[ScenarioOutcome] = field(default_factory=list)
    failed_count: int = 0
    recovered_count: int = 0
    rollback_entries: list[RollbackEntry] = field(default_factory=list)


# Type aliases for runner/recover callables
ScenarioRunner = Callable[[ScenarioTask], Awaitable[ScenarioOutcome]]
RecoverFunc = Callable[[ScenarioTask, Exception], Awaitable[ScenarioOutcome | None]]


class ResilienceOrchestrator:
    """Orchestrates parallel scenario execution with recovery and rollback logging."""

    def __init__(self, max_concurrent: int = 3) -> None:
        self._max_concurrent = max_concurrent
        self._semaphore: asyncio.Semaphore | None = None

    async def run_all(
        self,
        tasks: list[ScenarioTask],
        runner: ScenarioRunner,
        recover: RecoverFunc | None = None,
    ) -> ResilienceReport:
        """Run all scenario tasks with concurrency control.

        Args:
            tasks: List of scenarios to execute.
            runner: Async callable that runs a single scenario.
            recover: Optional async callable for recovery on failure.

        Returns:
            ResilienceReport with results, counts, and rollback log.
        """
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

        async def run_one(task: ScenarioTask) -> ScenarioOutcome:
            assert self._semaphore is not None
            async with self._semaphore:
                try:
                    outcome = await runner(task)
                    return outcome
                except Exception as exc:
                    if recover is not None:
                        start = time.monotonic()
                        try:
                            recovered_outcome = await recover(task, exc)
                            elapsed_ms = (time.monotonic() - start) * 1000
                            if recovered_outcome is not None:
                                recovered_outcome.recovered = True
                                recovered_outcome.recovery_ms = elapsed_ms
                                return recovered_outcome
                        except Exception:
                            pass
                    return ScenarioOutcome(
                        scenario_id=task.scenario_id,
                        workflow_id=task.workflow_id,
                        status="fail",
                        reason=str(exc),
                    )

        results = await asyncio.gather(*[run_one(t) for t in tasks])

        failed = sum(1 for r in results if r.status == "fail")
        recovered = sum(1 for r in results if r.recovered)
        rollback_entries = []
        for r in results:
            if r.status == "fail":
                rollback_entries.append(
                    RollbackEntry(
                        change_id=r.scenario_id,
                        reason=r.reason or "Unknown failure",
                        timestamp=datetime.now(UTC).isoformat(),
                    )
                )

        return ResilienceReport(
            results=list(results),
            failed_count=failed,
            recovered_count=recovered,
            rollback_entries=rollback_entries,
        )
