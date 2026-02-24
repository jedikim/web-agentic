"""Auto-Improvement Orchestrator — bridges run outcomes to the evolution pipeline.

When a workflow run fails, this orchestrator decides whether to trigger an
evolution cycle and, optionally, auto-approve the resulting fix.

Usage:
    orchestrator = AutoImprovementOrchestrator(
        evolution_service=pipeline,  # or None for dry-run
        enabled=True,
        trigger_statuses=["fail"],
        auto_approve=False,
    )
    result = await orchestrator.handle_outcome(
        workflow_id="run-123",
        status="fail",
        failures=[RunFailure(code="SelectorNotFound", message="...")],
    )
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ── Types ────────────────────────────────────────────

EvolutionTrigger = Literal["exception", "bug"]

_EXCEPTION_CODES = frozenset({"SelectorNotFound", "VisualAmbiguity", "AuthBlocked"})


@dataclass(frozen=True)
class RunFailure:
    """A single failure record from a workflow run."""

    code: str
    message: str | None = None


@dataclass(frozen=True)
class AutoImprovementResult:
    """Outcome of :meth:`AutoImprovementOrchestrator.handle_outcome`."""

    triggered: bool
    reason: str | None = None
    job_id: str | None = None
    trigger: EvolutionTrigger | None = None
    auto_approved: bool = False


# ── Evolution service protocol ───────────────────────


@runtime_checkable
class EvolutionServiceProtocol(Protocol):
    """Minimal interface the orchestrator expects from an evolution service."""

    async def trigger_evolution(
        self,
        workflow_id: str,
        trigger: str,
        *,
        failures: list[dict[str, Any]],
        run_artifact: str | None = None,
    ) -> str:
        """Create an evolution job and return the job id."""
        ...  # pragma: no cover

    async def approve_job(self, job_id: str) -> None:
        """Auto-approve an evolution job."""
        ...  # pragma: no cover


# ── Pure helper ──────────────────────────────────────


def infer_trigger_from_failures(failures: list[RunFailure]) -> EvolutionTrigger:
    """Classify a list of failures into an evolution trigger type.

    If any failure code belongs to a known exception set
    (``SelectorNotFound``, ``VisualAmbiguity``, ``AuthBlocked``) the trigger
    is ``"exception"``.  Otherwise it falls back to ``"bug"``.
    """
    codes = {f.code for f in failures}
    if codes & _EXCEPTION_CODES:
        return "exception"
    return "bug"


# ── Orchestrator ─────────────────────────────────────


class AutoImprovementOrchestrator:
    """Decides whether a run outcome should trigger an evolution cycle.

    Args:
        evolution_service: Backend that actually creates evolution jobs.
            When *None* the orchestrator operates in **dry-run** mode —
            it still computes the decision but does not create jobs.
        enabled: Global on/off switch.
        trigger_statuses: Which run statuses should trigger evolution
            (default ``["fail"]``).
        auto_approve: When *True*, automatically approve jobs that reach
            ``awaiting_approval``.
    """

    def __init__(
        self,
        evolution_service: Any | None = None,
        *,
        enabled: bool = True,
        trigger_statuses: list[str] | None = None,
        auto_approve: bool = False,
    ) -> None:
        self._service = evolution_service
        self._enabled = enabled
        self._trigger_statuses: list[str] = (
            trigger_statuses if trigger_statuses is not None else ["fail"]
        )
        self._auto_approve = auto_approve

    # ── Properties ───────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def trigger_statuses(self) -> list[str]:
        return list(self._trigger_statuses)

    @property
    def auto_approve(self) -> bool:
        return self._auto_approve

    # ── Main entry point ─────────────────────────────

    async def handle_outcome(
        self,
        workflow_id: str,
        status: str,
        failures: list[RunFailure],
        run_artifact: str | None = None,
    ) -> AutoImprovementResult:
        """Evaluate a run outcome and optionally trigger an evolution cycle.

        Args:
            workflow_id: Unique identifier of the workflow run.
            status: Final status of the run (e.g. ``"fail"``, ``"success"``).
            failures: List of failure records from the run.
            run_artifact: Optional path/URL to a run log or artifact.

        Returns:
            An :class:`AutoImprovementResult` describing the decision.
        """
        # Gate 1: global switch
        if not self._enabled:
            return AutoImprovementResult(triggered=False, reason="disabled")

        # Gate 2: status filter
        if status not in self._trigger_statuses:
            return AutoImprovementResult(
                triggered=False,
                reason=f"status {status!r} not in trigger statuses",
            )

        # Classify failures
        trigger = infer_trigger_from_failures(failures)
        logger.info(
            "Auto-improvement triggered for %s: trigger=%s, failures=%d",
            workflow_id,
            trigger,
            len(failures),
        )

        # Dry-run mode: no service available
        if self._service is None:
            return AutoImprovementResult(
                triggered=True,
                trigger=trigger,
                reason="dry-run (no evolution service)",
            )

        # Delegate to evolution service
        job_id: str | None = None
        if hasattr(self._service, "trigger_evolution"):
            failure_dicts = [
                {"code": f.code, "message": f.message} for f in failures
            ]
            job_id = await self._service.trigger_evolution(
                workflow_id,
                trigger,
                failures=failure_dicts,
                run_artifact=run_artifact,
            )

        auto_approved = False
        if self._auto_approve and job_id is not None and hasattr(self._service, "approve_job"):
            await self._service.approve_job(job_id)
            auto_approved = True
            logger.info("Auto-approved evolution job %s", job_id)

        return AutoImprovementResult(
            triggered=True,
            trigger=trigger,
            job_id=job_id,
            auto_approved=auto_approved,
        )
