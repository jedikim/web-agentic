"""Scenario Pack Builder — generates baseline + exception scenarios for evolution cycles.

Given an evolution trigger type and optional failure hint, builds a ScenarioPack
containing a baseline regression scenario and a set of exception scenarios covering
UI drift, regressions, timeouts, CAPTCHAs, modals, auth issues, and selector healing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

EvolutionTrigger = Literal["exception", "bug"]


@dataclass(frozen=True)
class ScenarioItem:
    """A single scenario within a pack."""

    id: str
    title: str
    objective: str
    min_steps: int
    checkpoints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScenarioPack:
    """A baseline scenario paired with a list of exception scenarios."""

    baseline: ScenarioItem
    exceptions: list[ScenarioItem] = field(default_factory=list)


# ── Trigger-Specific Exceptions ────────────────────────


def _trigger_specific_exceptions(trigger: EvolutionTrigger) -> list[ScenarioItem]:
    """Return exception scenarios specific to the evolution trigger type."""
    if trigger == "exception":
        return [
            ScenarioItem(
                id="ui-drift-detection",
                title="UI Drift Detection",
                objective="Verify automation adapts when page layout changes",
                min_steps=6,
                checkpoints=[
                    "Load target page",
                    "Detect layout version",
                    "Attempt original selector path",
                    "Detect selector failure",
                    "Recover via LLM re-selection",
                    "Verify action completed",
                ],
            ),
        ]
    elif trigger == "bug":
        return [
            ScenarioItem(
                id="bug-regression-check",
                title="Bug Regression Check",
                objective="Ensure previously fixed bug does not reappear",
                min_steps=6,
                checkpoints=[
                    "Load affected page",
                    "Reproduce original bug steps",
                    "Verify bug no longer triggers",
                    "Run related assertions",
                    "Check error logs clean",
                    "Confirm expected state",
                ],
            ),
        ]
    return []


# ── Base Exceptions ────────────────────────────────────


def _base_exceptions() -> list[ScenarioItem]:
    """Return the standard set of exception scenarios included in every pack."""
    return [
        ScenarioItem(
            id="timeout-retry",
            title="Timeout Retry",
            objective="Verify graceful retry on operation timeout",
            min_steps=5,
            checkpoints=[
                "Initiate slow operation",
                "Detect timeout",
                "Execute retry with backoff",
                "Verify operation completes",
                "Assert no data corruption",
            ],
        ),
        ScenarioItem(
            id="captcha-escalation",
            title="CAPTCHA Escalation",
            objective="Verify CAPTCHA detected and escalated to human handoff",
            min_steps=7,
            checkpoints=[
                "Navigate to protected page",
                "Detect CAPTCHA challenge",
                "Attempt auto-classification",
                "Escalate to human handoff",
                "Wait for resolution",
                "Resume automation after solve",
                "Verify page state post-CAPTCHA",
            ],
        ),
        ScenarioItem(
            id="modal-interruption",
            title="Modal Interruption",
            objective="Verify unexpected modal/popup is dismissed correctly",
            min_steps=5,
            checkpoints=[
                "Trigger page action",
                "Detect unexpected modal",
                "Classify modal intent",
                "Dismiss or accept modal",
                "Resume original workflow",
            ],
        ),
    ]


# ── Hint-Driven Exceptions ────────────────────────────


def _hint_driven_exceptions(hint: str | None) -> list[ScenarioItem]:
    """Return additional exception scenarios based on the failure hint text."""
    if not hint:
        return []

    hint_lower = hint.lower()
    results: list[ScenarioItem] = []

    if "403" in hint_lower or "forbidden" in hint_lower:
        results.append(
            ScenarioItem(
                id="auth-rotation",
                title="Auth Rotation",
                objective="Verify credentials are rotated on auth failure",
                min_steps=6,
                checkpoints=[
                    "Attempt authenticated request",
                    "Detect auth failure (403/forbidden)",
                    "Rotate credentials",
                    "Retry with new credentials",
                    "Verify access restored",
                    "Log rotation event",
                ],
            ),
        )

    if "selector" in hint_lower or "not found" in hint_lower:
        results.append(
            ScenarioItem(
                id="selector-healing",
                title="Selector Healing",
                objective="Verify selector self-heals when element structure changes",
                min_steps=6,
                checkpoints=[
                    "Load page with changed DOM",
                    "Attempt cached selector",
                    "Detect selector miss",
                    "Invoke LLM re-selection",
                    "Verify new selector works",
                    "Update selector cache",
                ],
            ),
        )

    return results


# ── Public API ─────────────────────────────────────────


def build_scenario_pack(
    workflow_id: str,
    trigger: EvolutionTrigger,
    failure_hint: str | None = None,
) -> ScenarioPack:
    """Build a complete scenario pack for an evolution cycle.

    Args:
        workflow_id: Identifier for the evolution workflow.
        trigger: The type of trigger that initiated evolution.
        failure_hint: Optional free-text hint describing the failure.

    Returns:
        A ScenarioPack with a baseline scenario and relevant exception scenarios.
    """
    baseline = ScenarioItem(
        id="baseline-regression-check",
        title=f"Baseline Regression — {workflow_id}",
        objective="Run standard regression checks against the current automation target",
        min_steps=5,
        checkpoints=[
            "Load target page",
            "Execute automation steps",
            "Capture checkpoint screenshot",
            "Verify expected state",
            "Persist run metrics",
        ],
    )

    exceptions = (
        _trigger_specific_exceptions(trigger)
        + _base_exceptions()
        + _hint_driven_exceptions(failure_hint)
    )

    return ScenarioPack(baseline=baseline, exceptions=exceptions)
