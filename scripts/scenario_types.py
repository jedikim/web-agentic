"""Multi-phase scenario type definitions and YAML loader.

A scenario consists of multiple phases, each representing a single
``orch.run()`` call.  Phases execute sequentially while sharing a
browser session, so Phase 2 can continue from the page state left
by Phase 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.core.llm_orchestrator import RunResult

# ── Definitions (immutable) ──────────────────────────


@dataclass(frozen=True)
class PhaseDefinition:
    """A single phase within a multi-phase scenario.

    Attributes:
        name: Phase name (used as screenshot prefix and report heading).
        intent: Natural-language intent passed to ``orch.run()``.
        url: URL to navigate to before this phase (``None`` = stay on current page).
        expected_min_steps: Minimum expected steps (for reporting only).
        timeout_s: Per-phase timeout in seconds.
    """

    name: str
    intent: str
    url: str | None = None
    expected_min_steps: int = 3
    timeout_s: int = 90


@dataclass(frozen=True)
class ScenarioDefinition:
    """A complete multi-phase scenario definition.

    Attributes:
        name: Scenario identifier (used as folder name).
        description: Human-readable description.
        context: User context injected into every phase intent.
        phases: Ordered list of phases to execute.
        tags: Tags for filtering (e.g. ``["naver", "map"]``).
        max_cost_usd: Budget cap for the entire scenario.
        timeout_s: Total scenario timeout in seconds.
    """

    name: str
    description: str
    context: str
    phases: list[PhaseDefinition]
    tags: list[str] = field(default_factory=list)
    max_cost_usd: float = 0.10
    timeout_s: int = 300


# ── Results (mutable) ────────────────────────────────


@dataclass
class PhaseResult:
    """Result of a single phase execution.

    Attributes:
        phase: The phase definition that was executed.
        run_result: Orchestrator result (``None`` if phase could not start).
        wall_time_s: Wall-clock time for this phase.
        error: Error message if the phase raised an exception.
        timed_out: Whether the phase hit its timeout.
    """

    phase: PhaseDefinition
    run_result: RunResult | None
    wall_time_s: float
    error: str | None = None
    timed_out: bool = False


@dataclass
class ScenarioResult:
    """Aggregated result for a complete scenario.

    Attributes:
        scenario: The scenario definition.
        phase_results: Results for each phase.
        total_wall_time_s: Total wall-clock time.
        started_at: ISO timestamp when the scenario started.
        finished_at: ISO timestamp when the scenario finished.
        overall_success: ``True`` only if **all** phases succeeded.
        total_tokens: Sum of tokens across all phases.
        total_cost_usd: Sum of cost across all phases.
        total_steps_ok: Number of successful steps across all phases.
        total_steps_all: Total number of steps across all phases.
        error: Top-level error message if the scenario failed to start.
    """

    scenario: ScenarioDefinition
    phase_results: list[PhaseResult]
    total_wall_time_s: float
    started_at: str
    finished_at: str
    overall_success: bool
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_steps_ok: int = 0
    total_steps_all: int = 0
    error: str | None = None


# ── YAML Loader ──────────────────────────────────────


def _parse_phase(raw: dict[str, Any]) -> PhaseDefinition:
    return PhaseDefinition(
        name=raw["name"],
        intent=raw["intent"],
        url=raw.get("url"),
        expected_min_steps=raw.get("expected_min_steps", 3),
        timeout_s=raw.get("timeout_s", 90),
    )


def _parse_scenario(raw: dict[str, Any]) -> ScenarioDefinition:
    phases = [_parse_phase(p) for p in raw["phases"]]
    return ScenarioDefinition(
        name=raw["name"],
        description=raw["description"],
        context=raw.get("context", ""),
        phases=phases,
        tags=raw.get("tags", []),
        max_cost_usd=raw.get("max_cost_usd", 0.10),
        timeout_s=raw.get("timeout_s", 300),
    )


def load_scenarios(path: str | Path) -> list[ScenarioDefinition]:
    """Load scenario definitions from a YAML file.

    Args:
        path: Path to the YAML file.

    Returns:
        List of parsed ``ScenarioDefinition`` objects.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the YAML is malformed.
        KeyError: If required fields are missing.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [_parse_scenario(s) for s in data["scenarios"]]
