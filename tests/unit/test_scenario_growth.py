"""Unit tests for the Scenario Pack Builder (F17)."""
from __future__ import annotations

import pytest

from src.evolution.scenario_growth import ScenarioItem, build_scenario_pack

# ── Baseline ───────────────────────────────────────────


def test_baseline_always_present() -> None:
    """build_scenario_pack always returns a baseline scenario."""
    pack = build_scenario_pack("wf-001", trigger="exception")
    assert pack.baseline is not None
    assert pack.baseline.id == "baseline-regression-check"


def test_baseline_checkpoints_count() -> None:
    """Baseline scenario has exactly 5 checkpoints."""
    pack = build_scenario_pack("wf-002", trigger="bug")
    assert len(pack.baseline.checkpoints) == 5


# ── Trigger-Specific ──────────────────────────────────


def test_exception_trigger_includes_ui_drift() -> None:
    """'exception' trigger adds UI drift detection scenario."""
    pack = build_scenario_pack("wf-003", trigger="exception")
    ids = [s.id for s in pack.exceptions]
    assert "ui-drift-detection" in ids


def test_bug_trigger_includes_regression() -> None:
    """'bug' trigger adds bug regression check scenario."""
    pack = build_scenario_pack("wf-004", trigger="bug")
    ids = [s.id for s in pack.exceptions]
    assert "bug-regression-check" in ids


# ── Base Exceptions ────────────────────────────────────


def test_base_exceptions_always_included() -> None:
    """Every pack includes timeout-retry, captcha-escalation, modal-interruption."""
    pack = build_scenario_pack("wf-005", trigger="exception")
    ids = [s.id for s in pack.exceptions]
    assert "timeout-retry" in ids
    assert "captcha-escalation" in ids
    assert "modal-interruption" in ids


# ── Hint-Driven ───────────────────────────────────────


def test_hint_403_adds_auth_rotation() -> None:
    """Failure hint containing '403' adds auth-rotation scenario."""
    pack = build_scenario_pack("wf-006", trigger="exception", failure_hint="HTTP 403 Forbidden")
    ids = [s.id for s in pack.exceptions]
    assert "auth-rotation" in ids


def test_hint_selector_adds_selector_healing() -> None:
    """Failure hint containing 'selector' adds selector-healing scenario."""
    pack = build_scenario_pack(
        "wf-007", trigger="bug", failure_hint="selector not matching after redesign",
    )
    ids = [s.id for s in pack.exceptions]
    assert "selector-healing" in ids


def test_no_hint_no_extra_exceptions() -> None:
    """Without a failure hint, no hint-driven exceptions are added."""
    pack_no_hint = build_scenario_pack("wf-008", trigger="exception", failure_hint=None)
    pack_empty = build_scenario_pack("wf-009", trigger="exception", failure_hint="")

    # Both should have: trigger-specific (1) + base (3) = 4 total
    assert len(pack_no_hint.exceptions) == 4
    assert len(pack_empty.exceptions) == 4

    hint_ids = {"auth-rotation", "selector-healing"}
    for exc in pack_no_hint.exceptions:
        assert exc.id not in hint_ids
    for exc in pack_empty.exceptions:
        assert exc.id not in hint_ids


def test_combined_hints() -> None:
    """A hint containing both '403' and 'selector' adds both hint-driven scenarios."""
    pack = build_scenario_pack(
        "wf-010",
        trigger="exception",
        failure_hint="403 forbidden — selector not found after auth redirect",
    )
    ids = [s.id for s in pack.exceptions]
    assert "auth-rotation" in ids
    assert "selector-healing" in ids
    # trigger(1) + base(3) + hint(2) = 6
    assert len(pack.exceptions) == 6


# ── Frozen Dataclass ──────────────────────────────────


def test_scenario_item_frozen() -> None:
    """ScenarioItem instances are immutable (frozen dataclass)."""
    item = ScenarioItem(
        id="test", title="Test", objective="obj", min_steps=1, checkpoints=["a"],
    )
    with pytest.raises(AttributeError):
        item.id = "changed"  # type: ignore[misc]
