"""YAML DSL parser — convert workflow files into ``list[StepDefinition]``.

Supports the 9 node types defined in the PRD:
action, extract, decide, verify, branch, loop, wait, recover, handoff.

Each step can carry guardrails (``max_retries``, ``timeout_ms``) and an
optional ``verify`` condition that is checked after execution.

Example workflow YAML::

    workflow:
      name: "naver_shopping_sort"
      description: "Search and sort products on Naver Shopping"
      steps:
        - id: "open_page"
          intent: "Go to Naver Shopping"
          node_type: "action"
          selector: null
          arguments: ["https://shopping.naver.com"]
          max_retries: 2
          timeout_ms: 15000

        - id: "search_product"
          intent: "Search for wireless earbuds"
          node_type: "action"
          arguments: ["무선 이어폰"]
          verify:
            type: "url_contains"
            value: "query="
            timeout_ms: 5000

        - id: "extract_products"
          intent: "Extract product list"
          node_type: "extract"
          max_retries: 3
          timeout_ms: 10000

        - id: "check_results"
          intent: "Decide if results are relevant"
          node_type: "decide"
          arguments: ["relevance_check"]

        - id: "sort_popular"
          intent: "Sort by popularity"
          node_type: "action"
          verify:
            type: "url_contains"
            value: "sort=rel"

        - id: "wait_reload"
          intent: "Wait for page reload"
          node_type: "wait"
          arguments: ["network_idle"]
          timeout_ms: 8000

        - id: "verify_sort"
          intent: "Verify sort order changed"
          node_type: "verify"
          verify:
            type: "element_visible"
            value: ".sort-active"

        - id: "loop_pages"
          intent: "Loop through pagination"
          node_type: "loop"
          arguments: ["next_page", "5"]
          max_retries: 5
          timeout_ms: 30000

        - id: "handle_captcha"
          intent: "Handle CAPTCHA if detected"
          node_type: "handoff"
          arguments: ["captcha"]
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from src.core.types import StepDefinition, VerifyCondition

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────

VALID_NODE_TYPES = frozenset(
    {"action", "extract", "decide", "verify", "branch", "loop", "wait", "recover", "handoff"}
)

# Guardrail constraints.
_MAX_RETRIES_MIN = 1
_MAX_RETRIES_MAX = 20
_TIMEOUT_MS_MIN = 500
_TIMEOUT_MS_MAX = 300_000  # 5 minutes

# Valid verify condition types.
VALID_VERIFY_TYPES = frozenset(
    {
        "url_changed",
        "url_contains",
        "element_visible",
        "element_gone",
        "text_present",
        "network_idle",
        "selector",
        "url",
        "text",
        "timeout",
    }
)


# ── Exceptions ───────────────────────────────────────


class DSLValidationError(ValueError):
    """Raised when a workflow YAML fails validation."""


# ── Parser ───────────────────────────────────────────


def parse_workflow(source: str | Path) -> list[StepDefinition]:
    """Parse a workflow YAML string or file into a list of step definitions.

    Args:
        source: Either a YAML string or a ``Path`` to a ``.yaml`` file.

    Returns:
        Ordered list of ``StepDefinition`` objects.

    Raises:
        DSLValidationError: If the YAML structure is invalid.
        FileNotFoundError: If *source* is a path that does not exist.
    """
    if isinstance(source, Path):
        if not source.exists():
            raise FileNotFoundError(f"Workflow file not found: {source}")
        text = source.read_text(encoding="utf-8")
    else:
        text = source

    data = yaml.safe_load(text)
    if data is None:
        raise DSLValidationError("Empty YAML document")

    return _parse_document(data)


def _parse_document(data: Any) -> list[StepDefinition]:
    """Parse the top-level YAML document."""
    if not isinstance(data, dict):
        raise DSLValidationError(
            f"Expected top-level mapping, got {type(data).__name__}"
        )

    workflow = data.get("workflow", data)
    if not isinstance(workflow, dict):
        raise DSLValidationError(
            f"Expected 'workflow' to be a mapping, got {type(workflow).__name__}"
        )

    steps_raw = workflow.get("steps")
    if steps_raw is None:
        raise DSLValidationError("Missing 'steps' key in workflow")
    if not isinstance(steps_raw, list):
        raise DSLValidationError(
            f"Expected 'steps' to be a list, got {type(steps_raw).__name__}"
        )
    if len(steps_raw) == 0:
        raise DSLValidationError("Workflow must have at least one step")

    steps: list[StepDefinition] = []
    seen_ids: set[str] = set()

    for idx, raw in enumerate(steps_raw):
        step = _parse_step(raw, idx)
        if step.step_id in seen_ids:
            raise DSLValidationError(
                f"Duplicate step id '{step.step_id}' at index {idx}"
            )
        seen_ids.add(step.step_id)
        steps.append(step)

    return steps


def _parse_step(raw: Any, idx: int) -> StepDefinition:
    """Parse a single step mapping.

    Args:
        raw: The raw YAML mapping for one step.
        idx: Zero-based index (for error messages).

    Returns:
        A validated ``StepDefinition``.

    Raises:
        DSLValidationError: On invalid structure or values.
    """
    if not isinstance(raw, dict):
        raise DSLValidationError(
            f"Step at index {idx}: expected mapping, got {type(raw).__name__}"
        )

    # Required fields.
    step_id = raw.get("id")
    if not step_id or not isinstance(step_id, str):
        raise DSLValidationError(
            f"Step at index {idx}: missing or invalid 'id'"
        )

    intent = raw.get("intent")
    if not intent or not isinstance(intent, str):
        raise DSLValidationError(
            f"Step '{step_id}': missing or invalid 'intent'"
        )

    # Node type (default: action).
    node_type = raw.get("node_type", "action")
    if node_type not in VALID_NODE_TYPES:
        raise DSLValidationError(
            f"Step '{step_id}': invalid node_type '{node_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_NODE_TYPES))}"
        )

    # Optional fields.
    selector = raw.get("selector")
    if selector is not None and not isinstance(selector, str):
        raise DSLValidationError(
            f"Step '{step_id}': 'selector' must be a string or null"
        )

    arguments = raw.get("arguments", [])
    if not isinstance(arguments, list):
        raise DSLValidationError(
            f"Step '{step_id}': 'arguments' must be a list"
        )
    arguments = [str(a) for a in arguments]

    # Guardrails.
    max_retries = raw.get("max_retries", 3)
    timeout_ms = raw.get("timeout_ms", 10000)
    _validate_guardrails(step_id, max_retries, timeout_ms)

    # Verify condition.
    verify_condition = _parse_verify(raw.get("verify"), step_id)

    return StepDefinition(
        step_id=step_id,
        intent=intent,
        node_type=node_type,
        selector=selector,
        arguments=arguments,
        verify_condition=verify_condition,
        max_attempts=max_retries,
        timeout_ms=timeout_ms,
    )


def _parse_verify(raw: Any, step_id: str) -> VerifyCondition | None:
    """Parse an optional verify condition block."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DSLValidationError(
            f"Step '{step_id}': 'verify' must be a mapping"
        )

    vtype = raw.get("type")
    if not vtype or not isinstance(vtype, str):
        raise DSLValidationError(
            f"Step '{step_id}': verify missing 'type'"
        )
    if vtype not in VALID_VERIFY_TYPES:
        raise DSLValidationError(
            f"Step '{step_id}': invalid verify type '{vtype}'. "
            f"Must be one of: {', '.join(sorted(VALID_VERIFY_TYPES))}"
        )

    value = str(raw.get("value", ""))
    timeout_ms = raw.get("timeout_ms", 5000)
    if not isinstance(timeout_ms, (int, float)):
        raise DSLValidationError(
            f"Step '{step_id}': verify timeout_ms must be a number"
        )

    return VerifyCondition(type=vtype, value=value, timeout_ms=int(timeout_ms))


def _validate_guardrails(step_id: str, max_retries: Any, timeout_ms: Any) -> None:
    """Validate guardrail values are within acceptable bounds.

    Args:
        step_id: For error context.
        max_retries: Must be int in [1, 20].
        timeout_ms: Must be int/float in [500, 300000].

    Raises:
        DSLValidationError: On invalid values.
    """
    if not isinstance(max_retries, int) or max_retries < _MAX_RETRIES_MIN:
        raise DSLValidationError(
            f"Step '{step_id}': max_retries must be an integer >= {_MAX_RETRIES_MIN}, "
            f"got {max_retries!r}"
        )
    if max_retries > _MAX_RETRIES_MAX:
        raise DSLValidationError(
            f"Step '{step_id}': max_retries must be <= {_MAX_RETRIES_MAX}, "
            f"got {max_retries}"
        )

    if not isinstance(timeout_ms, (int, float)):
        raise DSLValidationError(
            f"Step '{step_id}': timeout_ms must be a number, got {type(timeout_ms).__name__}"
        )
    timeout_ms = int(timeout_ms)
    if timeout_ms < _TIMEOUT_MS_MIN:
        raise DSLValidationError(
            f"Step '{step_id}': timeout_ms must be >= {_TIMEOUT_MS_MIN}, got {timeout_ms}"
        )
    if timeout_ms > _TIMEOUT_MS_MAX:
        raise DSLValidationError(
            f"Step '{step_id}': timeout_ms must be <= {_TIMEOUT_MS_MAX}, got {timeout_ms}"
        )
