"""Selector Recovery Pipeline — automatic selector repair on SelectorNotFound failures.

When a step fails because a selector no longer matches the DOM, this pipeline:

1. Runs the step via ``run_fn``.
2. If it passes on the first attempt, returns immediately.
3. On ``SelectorNotFound`` failure:
   a. Optionally calls ``build_candidates_fn`` to gather DOM candidates.
   b. Optionally calls ``suggest_patch_fn`` to propose a new selector (counts as
      an LLM call).
   c. Retries ``run_fn`` with the patched context.
4. Repeats up to ``max_attempts`` total attempts.

Design principles:
  - All callables are injected — no hard dependency on LLM or DOM modules.
  - Pure async function, no mutable state.
  - Frozen dataclasses for all inputs/outputs.

See docs/ARCHITECTURE.md for the escalation flow context.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)


# ── Data Types ──────────────────────────────────────


@dataclass(frozen=True)
class SelectorRecoveryRunResult:
    """Result returned by the ``run_fn`` callback.

    Attributes:
        status: ``"pass"`` if the step succeeded, ``"fail"`` otherwise.
        failure_code: Machine-readable failure classification (e.g.
            ``"SelectorNotFound"``).  ``None`` when *status* is ``"pass"``.
        candidates: Optional list of DOM candidate elements that the
            build-candidates step may have identified.
        proposed_patch: Optional selector patch dict suggested by the LLM
            or heuristic layer.
    """

    status: Literal["pass", "fail"]
    failure_code: str | None = None
    candidates: list[Any] | None = None
    proposed_patch: dict[str, Any] | None = None


@dataclass(frozen=True)
class SelectorRecoveryOutput:
    """Final output of the recovery pipeline.

    Attributes:
        status: ``"pass"`` if the step eventually succeeded, ``"fail"`` otherwise.
        attempts: Total number of ``run_fn`` invocations.
        llm_calls: Number of LLM-based patch suggestions made.
        recovered: ``True`` if the step failed initially but succeeded after
            recovery.
    """

    status: Literal["pass", "fail"]
    attempts: int
    llm_calls: int
    recovered: bool


# ── Pipeline ────────────────────────────────────────


async def execute_with_selector_recovery(
    run_fn: Callable[[], Awaitable[SelectorRecoveryRunResult]],
    build_candidates_fn: Callable[[], Awaitable[list[Any]]] | None = None,
    suggest_patch_fn: Callable[[list[Any] | None], Awaitable[dict[str, Any] | None]] | None = None,
    max_attempts: int = 2,
) -> SelectorRecoveryOutput:
    """Execute a step with automatic selector recovery on failure.

    Args:
        run_fn: Async callable that executes the step and returns a
            ``SelectorRecoveryRunResult``.  Called once initially and once
            per recovery attempt.
        build_candidates_fn: Optional async callable that returns a list of
            DOM candidate elements for context enrichment.
        suggest_patch_fn: Optional async callable that receives the current
            candidates (or ``None``) and returns a proposed selector patch
            dict.  Each invocation counts as one LLM call.
        max_attempts: Maximum total number of ``run_fn`` invocations
            (including the initial attempt).  Must be >= 1.

    Returns:
        A ``SelectorRecoveryOutput`` summarizing the outcome.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    attempts = 0
    llm_calls = 0

    # ── Initial attempt ──────────────────────────────
    result = await run_fn()
    attempts += 1

    if result.status == "pass":
        logger.debug("Selector recovery: passed on first attempt")
        return SelectorRecoveryOutput(
            status="pass",
            attempts=attempts,
            llm_calls=llm_calls,
            recovered=False,
        )

    # ── Recovery loop ────────────────────────────────
    while attempts < max_attempts:
        # Only recover from SelectorNotFound failures.
        if result.failure_code != "SelectorNotFound":
            logger.debug(
                "Selector recovery: non-recoverable failure code %r, giving up",
                result.failure_code,
            )
            return SelectorRecoveryOutput(
                status="fail",
                attempts=attempts,
                llm_calls=llm_calls,
                recovered=False,
            )

        # Build candidate context if available.
        candidates: list[Any] | None = None
        if build_candidates_fn is not None:
            candidates = await build_candidates_fn()
            logger.debug(
                "Selector recovery: built %d candidates",
                len(candidates) if candidates else 0,
            )

        # Suggest a patch (counts as an LLM call).
        if suggest_patch_fn is None:
            logger.debug("Selector recovery: no suggest_patch_fn, giving up")
            return SelectorRecoveryOutput(
                status="fail",
                attempts=attempts,
                llm_calls=llm_calls,
                recovered=False,
            )

        proposed_patch = await suggest_patch_fn(candidates)
        llm_calls += 1

        if proposed_patch is None:
            logger.debug("Selector recovery: suggest_patch_fn returned None, giving up")
            return SelectorRecoveryOutput(
                status="fail",
                attempts=attempts,
                llm_calls=llm_calls,
                recovered=False,
            )

        # Retry with the (externally applied) patch.
        result = await run_fn()
        attempts += 1

        if result.status == "pass":
            logger.info(
                "Selector recovery: succeeded after %d attempts (%d LLM calls)",
                attempts,
                llm_calls,
            )
            return SelectorRecoveryOutput(
                status="pass",
                attempts=attempts,
                llm_calls=llm_calls,
                recovered=True,
            )

    # Exhausted all attempts.
    logger.warning(
        "Selector recovery: exhausted %d attempts (%d LLM calls)",
        attempts,
        llm_calls,
    )
    return SelectorRecoveryOutput(
        status="fail",
        attempts=attempts,
        llm_calls=llm_calls,
        recovered=False,
    )
