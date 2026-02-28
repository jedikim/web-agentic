"""Unit tests for PatchSystem — ``src.ai.patch_system``."""
from __future__ import annotations

import pytest

from src.ai.patch_system import VALID_PATCH_TYPES, PatchSystem
from src.core.types import PatchData

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture()
def ps() -> PatchSystem:
    """Create a default PatchSystem."""
    return PatchSystem()


# ── Test: Validation ─────────────────────────────────


class TestValidation:
    """Tests for PatchSystem.validate_patch."""

    def test_valid_selector_fix(self, ps: PatchSystem) -> None:
        """A well-formed selector_fix patch passes validation."""
        patch = PatchData(
            patch_type="selector_fix",
            target="#old-btn",
            data={"new_selector": ".new-btn", "strategy": "class-based"},
            confidence=0.85,
        )
        assert ps.validate_patch(patch) is True

    def test_valid_param_change(self, ps: PatchSystem) -> None:
        """A well-formed param_change patch passes validation."""
        patch = PatchData(
            patch_type="param_change",
            target="step_3",
            data={"param_name": "timeout_ms", "new_value": 15000},
            confidence=0.9,
        )
        assert ps.validate_patch(patch) is True

    def test_valid_rule_add(self, ps: PatchSystem) -> None:
        """A well-formed rule_add patch passes validation."""
        patch = PatchData(
            patch_type="rule_add",
            target="rule_engine",
            data={
                "rule_id": "new_sort_rule",
                "category": "sort",
                "intent_pattern": "sort by price",
                "selector": ".price-sort",
            },
            confidence=0.8,
        )
        assert ps.validate_patch(patch) is True

    def test_valid_strategy_switch(self, ps: PatchSystem) -> None:
        """A well-formed strategy_switch patch passes validation."""
        patch = PatchData(
            patch_type="strategy_switch",
            target="step_5",
            data={"new_strategy": "escalate_vision"},
            confidence=0.75,
        )
        assert ps.validate_patch(patch) is True

    def test_invalid_patch_type(self, ps: PatchSystem) -> None:
        """Unknown patch type fails validation."""
        patch = PatchData(
            patch_type="unknown_type",
            target="x",
            data={"key": "value"},
            confidence=0.5,
        )
        assert ps.validate_patch(patch) is False

    def test_empty_target(self, ps: PatchSystem) -> None:
        """Empty target fails validation."""
        patch = PatchData(
            patch_type="selector_fix",
            target="",
            data={"new_selector": ".x"},
            confidence=0.5,
        )
        assert ps.validate_patch(patch) is False

    def test_confidence_below_zero(self, ps: PatchSystem) -> None:
        """Negative confidence fails validation."""
        patch = PatchData(
            patch_type="selector_fix",
            target="#btn",
            data={"new_selector": ".x"},
            confidence=-0.1,
        )
        assert ps.validate_patch(patch) is False

    def test_confidence_above_one(self, ps: PatchSystem) -> None:
        """Confidence above 1.0 fails validation."""
        patch = PatchData(
            patch_type="selector_fix",
            target="#btn",
            data={"new_selector": ".x"},
            confidence=1.5,
        )
        assert ps.validate_patch(patch) is False

    def test_missing_required_data_keys(self, ps: PatchSystem) -> None:
        """Missing required data keys for patch type fails validation."""
        patch = PatchData(
            patch_type="selector_fix",
            target="#btn",
            data={"wrong_key": "value"},  # missing "new_selector"
            confidence=0.5,
        )
        assert ps.validate_patch(patch) is False

    def test_partial_required_keys(self, ps: PatchSystem) -> None:
        """Having some but not all required keys fails validation."""
        patch = PatchData(
            patch_type="rule_add",
            target="engine",
            data={"rule_id": "r1", "category": "sort"},
            # missing intent_pattern and selector
            confidence=0.5,
        )
        assert ps.validate_patch(patch) is False


# ── Test: Apply Selector Fix ─────────────────────────


class TestApplySelectorFix:
    """Tests for selector_fix patch application."""

    def test_apply_basic_selector_fix(self, ps: PatchSystem) -> None:
        """Applies a selector fix to the context."""
        patch = PatchData(
            patch_type="selector_fix",
            target="#old-btn",
            data={"new_selector": ".new-btn", "strategy": "class-based"},
            confidence=0.9,
        )
        context: dict = {}
        result = ps.apply_patch(patch, context)

        assert result["selectors"]["#old-btn"] == ".new-btn"
        assert len(result["replaced_selectors"]) == 1
        assert result["replaced_selectors"][0]["old"] == "#old-btn"
        assert result["replaced_selectors"][0]["new"] == ".new-btn"
        assert result["replaced_selectors"][0]["strategy"] == "class-based"

    def test_multiple_selector_fixes(self, ps: PatchSystem) -> None:
        """Applying multiple selector fixes accumulates in context."""
        context: dict = {}

        patch1 = PatchData(
            patch_type="selector_fix",
            target="#btn1",
            data={"new_selector": ".btn1-new"},
            confidence=0.8,
        )
        ps.apply_patch(patch1, context)

        patch2 = PatchData(
            patch_type="selector_fix",
            target="#btn2",
            data={"new_selector": ".btn2-new"},
            confidence=0.9,
        )
        ps.apply_patch(patch2, context)

        assert len(context["replaced_selectors"]) == 2
        assert context["selectors"]["#btn1"] == ".btn1-new"
        assert context["selectors"]["#btn2"] == ".btn2-new"

    def test_selector_fix_default_strategy(self, ps: PatchSystem) -> None:
        """Missing strategy defaults to 'unknown'."""
        patch = PatchData(
            patch_type="selector_fix",
            target="#old",
            data={"new_selector": ".new"},
            confidence=0.7,
        )
        context: dict = {}
        ps.apply_patch(patch, context)
        assert context["replaced_selectors"][0]["strategy"] == "unknown"


# ── Test: Apply Param Change ─────────────────────────


class TestApplyParamChange:
    """Tests for param_change patch application."""

    def test_apply_param_change(self, ps: PatchSystem) -> None:
        """Applies a parameter change to context."""
        patch = PatchData(
            patch_type="param_change",
            target="step_3",
            data={"param_name": "timeout_ms", "new_value": 20000},
            confidence=0.85,
        )
        context: dict = {}
        result = ps.apply_patch(patch, context)

        assert result["param_overrides"]["step_3"]["timeout_ms"] == 20000

    def test_multiple_param_changes_same_target(self, ps: PatchSystem) -> None:
        """Multiple param changes on the same target accumulate."""
        context: dict = {}

        p1 = PatchData(
            patch_type="param_change",
            target="step_1",
            data={"param_name": "timeout_ms", "new_value": 15000},
            confidence=0.8,
        )
        ps.apply_patch(p1, context)

        p2 = PatchData(
            patch_type="param_change",
            target="step_1",
            data={"param_name": "max_attempts", "new_value": 5},
            confidence=0.9,
        )
        ps.apply_patch(p2, context)

        assert context["param_overrides"]["step_1"]["timeout_ms"] == 15000
        assert context["param_overrides"]["step_1"]["max_attempts"] == 5


# ── Test: Apply Rule Add ─────────────────────────────


class TestApplyRuleAdd:
    """Tests for rule_add patch application."""

    def test_apply_rule_add(self, ps: PatchSystem) -> None:
        """Adds a rule to the pending_rules list in context."""
        patch = PatchData(
            patch_type="rule_add",
            target="rule_engine",
            data={
                "rule_id": "sort_popular",
                "category": "sort",
                "intent_pattern": "sort by popular",
                "selector": ".sort-pop",
                "method": "click",
                "priority": 10,
            },
            confidence=0.88,
        )
        context: dict = {}
        result = ps.apply_patch(patch, context)

        assert len(result["pending_rules"]) == 1
        rule = result["pending_rules"][0]
        assert rule["rule_id"] == "sort_popular"
        assert rule["category"] == "sort"
        assert rule["selector"] == ".sort-pop"
        assert rule["method"] == "click"
        assert rule["priority"] == 10
        assert rule["confidence"] == 0.88

    def test_rule_add_defaults(self, ps: PatchSystem) -> None:
        """Rule add uses default method and priority when not provided."""
        patch = PatchData(
            patch_type="rule_add",
            target="rule_engine",
            data={
                "rule_id": "filter_price",
                "category": "filter",
                "intent_pattern": "filter by price",
                "selector": ".price-filter",
            },
            confidence=0.75,
        )
        context: dict = {}
        ps.apply_patch(patch, context)

        rule = context["pending_rules"][0]
        assert rule["method"] == "click"
        assert rule["priority"] == 0

    def test_multiple_rules_accumulate(self, ps: PatchSystem) -> None:
        """Multiple rule_add patches accumulate in pending_rules."""
        context: dict = {}

        for i in range(3):
            patch = PatchData(
                patch_type="rule_add",
                target="rule_engine",
                data={
                    "rule_id": f"rule_{i}",
                    "category": "sort",
                    "intent_pattern": f"intent_{i}",
                    "selector": f".sel-{i}",
                },
                confidence=0.8,
            )
            ps.apply_patch(patch, context)

        assert len(context["pending_rules"]) == 3


# ── Test: Apply Strategy Switch ──────────────────────


class TestApplyStrategySwitch:
    """Tests for strategy_switch patch application."""

    def test_apply_strategy_switch(self, ps: PatchSystem) -> None:
        """Applies a strategy switch to context."""
        patch = PatchData(
            patch_type="strategy_switch",
            target="step_5",
            data={"new_strategy": "escalate_vision"},
            confidence=0.8,
        )
        context: dict = {}
        result = ps.apply_patch(patch, context)

        assert result["strategy_overrides"]["step_5"] == "escalate_vision"

    def test_strategy_switch_overwrites(self, ps: PatchSystem) -> None:
        """A second strategy switch for the same target overwrites the first."""
        context: dict = {}

        p1 = PatchData(
            patch_type="strategy_switch",
            target="step_1",
            data={"new_strategy": "retry"},
            confidence=0.7,
        )
        ps.apply_patch(p1, context)

        p2 = PatchData(
            patch_type="strategy_switch",
            target="step_1",
            data={"new_strategy": "human_handoff"},
            confidence=0.95,
        )
        ps.apply_patch(p2, context)

        assert context["strategy_overrides"]["step_1"] == "human_handoff"


# ── Test: Apply Invalid Patch ────────────────────────


class TestApplyInvalidPatch:
    """Tests for apply_patch with invalid patches."""

    def test_apply_invalid_raises_valueerror(self, ps: PatchSystem) -> None:
        """Applying an invalid patch raises ValueError."""
        patch = PatchData(
            patch_type="unknown",
            target="x",
            data={},
            confidence=0.5,
        )
        with pytest.raises(ValueError, match="Invalid patch"):
            ps.apply_patch(patch, {})

    def test_apply_missing_data_raises(self, ps: PatchSystem) -> None:
        """Applying a patch with missing required data raises ValueError."""
        patch = PatchData(
            patch_type="selector_fix",
            target="#btn",
            data={"wrong": "data"},
            confidence=0.5,
        )
        with pytest.raises(ValueError, match="Invalid patch"):
            ps.apply_patch(patch, {})


# ── Test: Valid Patch Types Constant ─────────────────


class TestConstants:
    """Tests for module-level constants."""

    def test_valid_patch_types_is_frozenset(self) -> None:
        """VALID_PATCH_TYPES is immutable."""
        assert isinstance(VALID_PATCH_TYPES, frozenset)

    def test_all_four_types_present(self) -> None:
        """All four patch types are registered."""
        expected = {"selector_fix", "param_change", "rule_add", "strategy_switch"}
        assert expected == VALID_PATCH_TYPES

    def test_valid_patch_types_immutable(self) -> None:
        """Cannot add to VALID_PATCH_TYPES at runtime."""
        with pytest.raises(AttributeError):
            VALID_PATCH_TYPES.add("new_type")  # type: ignore[attr-defined]
