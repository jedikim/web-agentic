"""Decision Port + Human Loop — structured human-in-the-loop decision interface.

Provides a protocol-based ``DecisionPort`` abstraction and a ``run_human_loop``
driver function that orchestrates an iterative run-decide-revise cycle.

The loop calls ``run_fn`` repeatedly.  When the run signals ``need_user``, the
loop consults ``decision_port`` to obtain a human (or automated) decision:

* **go** — continue to the next iteration.
* **not_go** / **unknown** — abort and return ``blocked``.
* **revise** — optionally invoke ``revise_fn``, then re-run.

The loop terminates early on ``pass`` or ``fail`` from ``run_fn``, or when
``max_turns`` is exhausted (returns ``blocked``).

Token cost: 0 (pure coordination, no LLM calls).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ── Type Aliases ────────────────────────────────────────

DecisionType = Literal["go", "not_go", "revise", "unknown"]

# ── Data Classes ────────────────────────────────────────


@dataclass(frozen=True)
class Decision:
    """A human or automated decision in response to a ``need_user`` signal.

    Attributes:
        decision_type: The decision outcome.
        reason: Human-readable explanation for the decision.
        revision_hint: Optional hint for the revise step (e.g. what to change).
    """

    decision_type: DecisionType
    reason: str
    revision_hint: str | None = None


@dataclass(frozen=True)
class RunResult:
    """Result of a single run iteration inside the human loop.

    Attributes:
        status: ``pass`` if the task succeeded, ``fail`` if it failed
            irrecoverably, or ``need_user`` if human input is required.
        reason: Optional explanation of the status.
        screenshot_path: Optional path to a screenshot for context.
        question: Optional question to present to the human when
            ``status == "need_user"``.
    """

    status: Literal["pass", "fail", "need_user"]
    reason: str | None = None
    screenshot_path: str | None = None
    question: str | None = None


@dataclass(frozen=True)
class HumanLoopResult:
    """Final result of a ``run_human_loop`` invocation.

    Attributes:
        status: ``pass`` if the task eventually succeeded, ``fail`` if
            it failed irrecoverably, or ``blocked`` if it could not proceed
            (human said no, unknown decision, or max turns exceeded).
        turns: Total number of ``run_fn`` invocations.
        revisions: Number of ``revise`` decisions executed.
        decisions: Ordered list of all decisions collected.
    """

    status: Literal["pass", "fail", "blocked"]
    turns: int
    revisions: int
    decisions: list[Decision] = field(default_factory=list)


# ── Protocol ────────────────────────────────────────────


@runtime_checkable
class DecisionPort(Protocol):
    """Protocol for requesting a decision from a human or automated oracle.

    Implementers must provide an async ``request_decision`` method that
    accepts a context dict and returns a ``Decision``.
    """

    async def request_decision(self, context: dict[str, Any]) -> Decision:
        """Request a decision given the current context.

        Args:
            context: Arbitrary key-value pairs describing the situation
                (e.g. ``question``, ``screenshot_path``, ``reason``).

        Returns:
            A ``Decision`` indicating what to do next.
        """
        ...  # pragma: no cover


# ── Human Loop Driver ───────────────────────────────────


async def run_human_loop(
    run_fn: Callable[[], Awaitable[RunResult]],
    decision_port: DecisionPort,
    revise_fn: Callable[[], Awaitable[None]] | None = None,
    max_turns: int = 8,
) -> HumanLoopResult:
    """Drive an iterative run-decide-revise cycle with human oversight.

    The loop repeatedly calls *run_fn*.  When the result status is
    ``need_user``, the *decision_port* is consulted.  Depending on the
    decision:

    * ``go``      — continue to the next iteration.
    * ``not_go``  — return ``blocked`` immediately.
    * ``unknown`` — return ``blocked`` immediately.
    * ``revise``  — call *revise_fn* (if provided), increment revision
      counter, and continue.

    The loop exits early on ``pass`` or ``fail`` from *run_fn*, or when
    *max_turns* iterations are exhausted (returns ``blocked``).

    Args:
        run_fn: Async callable that performs one iteration of work.
        decision_port: The decision oracle to consult on ``need_user``.
        revise_fn: Optional async callable invoked on ``revise`` decisions.
        max_turns: Maximum number of ``run_fn`` invocations (default 8).

    Returns:
        A ``HumanLoopResult`` summarising the outcome.
    """
    turns = 0
    revisions = 0
    decisions: list[Decision] = []

    while turns < max_turns:
        turns += 1
        result = await run_fn()

        if result.status == "pass":
            logger.info("Human loop: pass on turn %d", turns)
            return HumanLoopResult(
                status="pass",
                turns=turns,
                revisions=revisions,
                decisions=decisions,
            )

        if result.status == "fail":
            logger.info("Human loop: fail on turn %d", turns)
            return HumanLoopResult(
                status="fail",
                turns=turns,
                revisions=revisions,
                decisions=decisions,
            )

        # status == "need_user"
        context: dict[str, Any] = {}
        if result.reason is not None:
            context["reason"] = result.reason
        if result.screenshot_path is not None:
            context["screenshot_path"] = result.screenshot_path
        if result.question is not None:
            context["question"] = result.question

        decision = await decision_port.request_decision(context)
        decisions.append(decision)

        if decision.decision_type in ("not_go", "unknown"):
            logger.info(
                "Human loop: blocked by %s on turn %d",
                decision.decision_type,
                turns,
            )
            return HumanLoopResult(
                status="blocked",
                turns=turns,
                revisions=revisions,
                decisions=decisions,
            )

        if decision.decision_type == "revise":
            if revise_fn is not None:
                await revise_fn()
            revisions += 1
            logger.info("Human loop: revision %d on turn %d", revisions, turns)
            continue

        # decision_type == "go" — continue to next iteration.
        logger.debug("Human loop: go on turn %d", turns)

    # Max turns exceeded.
    logger.warning("Human loop: max turns (%d) exceeded", max_turns)
    return HumanLoopResult(
        status="blocked",
        turns=turns,
        revisions=revisions,
        decisions=decisions,
    )
