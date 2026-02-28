"""Unit tests for YAML DSL parser — ``src.workflow.dsl_parser``."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.workflow.dsl_parser import (
    VALID_NODE_TYPES,
    DSLValidationError,
    parse_workflow,
)

# ── Helpers ──────────────────────────────────────────

_MINIMAL_WORKFLOW = textwrap.dedent("""\
    workflow:
      name: "test"
      steps:
        - id: "step1"
          intent: "Do something"
""")


def _workflow_yaml(*steps: str) -> str:
    """Build a workflow YAML string from step snippets."""
    joined = "\n".join(f"        {line}" for step in steps for line in step.splitlines())
    return textwrap.dedent(f"""\
        workflow:
          name: "test"
          steps:
    {joined}
    """)


# ── Test: Valid Workflow Parsing ──────────────────────


class TestValidWorkflow:
    """Tests for parsing well-formed workflows."""

    def test_minimal_workflow(self) -> None:
        """A minimal workflow with one step parses correctly."""
        steps = parse_workflow(_MINIMAL_WORKFLOW)
        assert len(steps) == 1
        assert steps[0].step_id == "step1"
        assert steps[0].intent == "Do something"
        assert steps[0].node_type == "action"  # default
        assert steps[0].max_attempts == 3  # default
        assert steps[0].timeout_ms == 10000  # default

    def test_full_workflow_with_verify(self) -> None:
        """Workflow with verify condition parses correctly."""
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "full"
              steps:
                - id: "search"
                  intent: "Search for product"
                  node_type: "action"
                  arguments: ["laptop"]
                  max_retries: 5
                  timeout_ms: 15000
                  verify:
                    type: "url_contains"
                    value: "query=laptop"
                    timeout_ms: 3000
        """)
        steps = parse_workflow(yaml_str)
        assert len(steps) == 1
        step = steps[0]
        assert step.step_id == "search"
        assert step.arguments == ["laptop"]
        assert step.max_attempts == 5
        assert step.timeout_ms == 15000
        assert step.verify_condition is not None
        assert step.verify_condition.type == "url_contains"
        assert step.verify_condition.value == "query=laptop"
        assert step.verify_condition.timeout_ms == 3000

    def test_multiple_steps_preserve_order(self) -> None:
        """Multiple steps maintain their YAML ordering."""
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "multi"
              steps:
                - id: "step_a"
                  intent: "First"
                - id: "step_b"
                  intent: "Second"
                - id: "step_c"
                  intent: "Third"
        """)
        steps = parse_workflow(yaml_str)
        assert [s.step_id for s in steps] == ["step_a", "step_b", "step_c"]

    def test_parse_from_file(self, tmp_path: Path) -> None:
        """Parsing from a file Path works."""
        filepath = tmp_path / "wf.yaml"
        filepath.write_text(_MINIMAL_WORKFLOW, encoding="utf-8")
        steps = parse_workflow(filepath)
        assert len(steps) == 1
        assert steps[0].step_id == "step1"


# ── Test: All 9 Node Types ──────────────────────────


class TestNodeTypes:
    """Each of the 9 node types is accepted."""

    @pytest.mark.parametrize("node_type", sorted(VALID_NODE_TYPES))
    def test_valid_node_type(self, node_type: str) -> None:
        yaml_str = textwrap.dedent(f"""\
            workflow:
              name: "test"
              steps:
                - id: "s1"
                  intent: "Test {node_type}"
                  node_type: "{node_type}"
        """)
        steps = parse_workflow(yaml_str)
        assert steps[0].node_type == node_type

    def test_invalid_node_type_raises(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "test"
              steps:
                - id: "s1"
                  intent: "bad"
                  node_type: "teleport"
        """)
        with pytest.raises(DSLValidationError, match="invalid node_type"):
            parse_workflow(yaml_str)


# ── Test: Validation Errors ──────────────────────────


class TestValidationErrors:
    """Tests that invalid YAML raises DSLValidationError."""

    def test_empty_yaml(self) -> None:
        with pytest.raises(DSLValidationError, match="Empty YAML"):
            parse_workflow("")

    def test_missing_steps_key(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "no_steps"
        """)
        with pytest.raises(DSLValidationError, match="Missing 'steps'"):
            parse_workflow(yaml_str)

    def test_empty_steps_list(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "empty"
              steps: []
        """)
        with pytest.raises(DSLValidationError, match="at least one step"):
            parse_workflow(yaml_str)

    def test_missing_step_id(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "test"
              steps:
                - intent: "No ID"
        """)
        with pytest.raises(DSLValidationError, match="missing or invalid 'id'"):
            parse_workflow(yaml_str)

    def test_missing_intent(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "test"
              steps:
                - id: "s1"
        """)
        with pytest.raises(DSLValidationError, match="missing or invalid 'intent'"):
            parse_workflow(yaml_str)

    def test_duplicate_step_ids(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "test"
              steps:
                - id: "dup"
                  intent: "First"
                - id: "dup"
                  intent: "Second"
        """)
        with pytest.raises(DSLValidationError, match="Duplicate step id"):
            parse_workflow(yaml_str)

    def test_max_retries_too_low(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "test"
              steps:
                - id: "s1"
                  intent: "Test"
                  max_retries: 0
        """)
        with pytest.raises(DSLValidationError, match="max_retries"):
            parse_workflow(yaml_str)

    def test_timeout_ms_too_low(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "test"
              steps:
                - id: "s1"
                  intent: "Test"
                  timeout_ms: 100
        """)
        with pytest.raises(DSLValidationError, match="timeout_ms"):
            parse_workflow(yaml_str)

    def test_invalid_verify_type(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "test"
              steps:
                - id: "s1"
                  intent: "Test"
                  verify:
                    type: "magic_check"
        """)
        with pytest.raises(DSLValidationError, match="invalid verify type"):
            parse_workflow(yaml_str)

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            parse_workflow(tmp_path / "nonexistent.yaml")

    def test_steps_not_a_list(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "test"
              steps: "not a list"
        """)
        with pytest.raises(DSLValidationError, match="'steps' to be a list"):
            parse_workflow(yaml_str)


# ── Test: Selector and Arguments ─────────────────────


class TestFieldParsing:
    """Tests for optional field handling."""

    def test_selector_parsed(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "test"
              steps:
                - id: "s1"
                  intent: "Click button"
                  selector: "#submit-btn"
        """)
        steps = parse_workflow(yaml_str)
        assert steps[0].selector == "#submit-btn"

    def test_arguments_coerced_to_strings(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "test"
              steps:
                - id: "s1"
                  intent: "Test"
                  arguments: [123, true, "text"]
        """)
        steps = parse_workflow(yaml_str)
        assert steps[0].arguments == ["123", "True", "text"]

    def test_null_selector_allowed(self) -> None:
        yaml_str = textwrap.dedent("""\
            workflow:
              name: "test"
              steps:
                - id: "s1"
                  intent: "Test"
                  selector: null
        """)
        steps = parse_workflow(yaml_str)
        assert steps[0].selector is None
