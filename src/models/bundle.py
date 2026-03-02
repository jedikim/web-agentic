"""Generated execution bundle — DSL + optional macros + prompts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StrategyAssignment:
    """Strategy assignment for a page type."""

    page_type: str = ""
    url_pattern: str = ""
    # dom_only | dom_with_objdet_backup | objdet_dom_hybrid | grid_vlm | vlm_only
    strategy: str = "dom_only"
    tools_needed: list[str] = field(default_factory=list)


@dataclass
class GeneratedBundle:
    """Execution bundle produced by CodeGenAgent."""

    workflow_dsl: dict[str, Any] = field(default_factory=dict)
    python_macro: str | None = None
    ts_macro: str | None = None
    prompts: dict[str, str] = field(default_factory=dict)
    strategy: str = "dom_only"
    dependencies: list[str] = field(default_factory=list)
    selector_patches: list[dict[str, Any]] = field(default_factory=list)
    version: int = 1


@dataclass
class ValidationResult:
    """Result of 5-stage validation gate."""

    dsl_ok: bool = False
    macro_ok: bool = True
    selector_ok: bool = False
    har_replay_ok: bool = False
    canary_ok: bool = False
    trace_ok: bool = False
    trace_path: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def overall(self) -> bool:
        """All gates must pass."""
        return all([
            self.dsl_ok,
            self.macro_ok,
            self.selector_ok,
            self.har_replay_ok,
            self.canary_ok,
            self.trace_ok,
        ])
