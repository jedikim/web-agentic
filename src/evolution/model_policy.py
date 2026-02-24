"""Evolution model policy — enforces model tier constraints for evolution tasks.

Coding tasks (analysis, code generation) require high-quality Pro-tier models.
Automation tasks (scenario execution, DOM interaction) use fast Flash-tier models.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_CODING_MODEL = "gemini-3.1-pro-preview"
DEFAULT_AUTOMATION_MODEL = "gemini-3-flash-preview"


@dataclass(frozen=True)
class EvolutionModelPolicy:
    """Resolved model assignments for evolution tasks."""

    coding_model: str
    automation_model: str


def is_flash_model(model: str) -> bool:
    """Return True if *model* belongs to the flash tier."""
    return "flash" in model.lower()


def _assert_coding_model(model: str) -> None:
    if is_flash_model(model):
        raise ValueError(
            f"coding model must be a high-quality coding model, received: {model}"
        )


def _assert_automation_model(model: str) -> None:
    if not is_flash_model(model):
        raise ValueError(
            f"automation model must use a fast flash-tier model, received: {model}"
        )


def resolve_evolution_model_policy(
    coding_model: str | None = None,
    automation_model: str | None = None,
    env: dict[str, str] | None = None,
) -> EvolutionModelPolicy:
    """Build an :class:`EvolutionModelPolicy` with cascading resolution.

    Resolution order (first non-None wins):
      1. Explicit keyword arguments
      2. Environment variables (``EVOLUTION_CODING_MODEL`` / ``EVOLUTION_AUTOMATION_MODEL``)
      3. Built-in defaults

    Raises:
        ValueError: If the resolved coding model is a flash-tier model or the
            resolved automation model is *not* a flash-tier model.
    """
    source = env if env is not None else os.environ

    resolved_coding = (
        coding_model
        or source.get("EVOLUTION_CODING_MODEL")
        or DEFAULT_CODING_MODEL
    )
    resolved_automation = (
        automation_model
        or source.get("EVOLUTION_AUTOMATION_MODEL")
        or DEFAULT_AUTOMATION_MODEL
    )

    _assert_coding_model(resolved_coding)
    _assert_automation_model(resolved_automation)

    return EvolutionModelPolicy(
        coding_model=resolved_coding,
        automation_model=resolved_automation,
    )
