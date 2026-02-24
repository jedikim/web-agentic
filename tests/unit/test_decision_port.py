"""Unit tests for Decision Port + Human Loop — ``src.core.decision_port``."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.core.decision_port import (
    Decision,
    DecisionPort,
    DecisionType,
    HumanLoopResult,
    RunResult,
    run_human_loop,
)

# ── Helpers ─────────────────────────────────────────────


class StubDecisionPort:
    """A simple DecisionPort that returns decisions from a pre-set queue."""

    def __init__(self, decisions: list[Decision]) -> None:
        self._decisions = list(decisions)
        self._index = 0

    async def request_decision(self, context: dict[str, Any]) -> Decision:
        decision = self._decisions[self._index]
        self._index += 1
        return decision


def _make_run_fn(results: list[RunResult]) -> AsyncMock:
    """Create an AsyncMock that returns results from a list in order."""
    mock = AsyncMock(side_effect=results)
    return mock


# ── Test: pass on first run ─────────────────────────────


class TestPassOnFirstRun:
    """run_human_loop returns pass immediately when run_fn passes."""

    @pytest.mark.asyncio
    async def test_pass_on_first_run(self) -> None:
        run_fn = _make_run_fn([RunResult(status="pass")])
        port = StubDecisionPort([])

        result = await run_human_loop(run_fn=run_fn, decision_port=port)

        assert result.status == "pass"
        assert result.turns == 1
        assert result.revisions == 0
        assert result.decisions == []
        run_fn.assert_called_once()


# ── Test: fail on first run ─────────────────────────────


class TestFailOnFirstRun:
    """run_human_loop returns fail immediately when run_fn fails."""

    @pytest.mark.asyncio
    async def test_fail_on_first_run(self) -> None:
        run_fn = _make_run_fn([RunResult(status="fail", reason="critical error")])
        port = StubDecisionPort([])

        result = await run_human_loop(run_fn=run_fn, decision_port=port)

        assert result.status == "fail"
        assert result.turns == 1
        assert result.revisions == 0
        assert result.decisions == []
        run_fn.assert_called_once()


# ── Test: need_user → go → pass ─────────────────────────


class TestNeedUserGoThenPass:
    """need_user + go decision continues the loop; pass on second run."""

    @pytest.mark.asyncio
    async def test_need_user_go_then_pass(self) -> None:
        run_fn = _make_run_fn([
            RunResult(status="need_user", question="Continue?"),
            RunResult(status="pass"),
        ])
        port = StubDecisionPort([
            Decision(decision_type="go", reason="Approved"),
        ])

        result = await run_human_loop(run_fn=run_fn, decision_port=port)

        assert result.status == "pass"
        assert result.turns == 2
        assert result.revisions == 0
        assert len(result.decisions) == 1
        assert result.decisions[0].decision_type == "go"


# ── Test: need_user → not_go → blocked ──────────────────


class TestNeedUserNotGoBlocks:
    """need_user + not_go decision blocks the loop immediately."""

    @pytest.mark.asyncio
    async def test_need_user_not_go_blocks(self) -> None:
        run_fn = _make_run_fn([
            RunResult(status="need_user", reason="Needs approval"),
        ])
        port = StubDecisionPort([
            Decision(decision_type="not_go", reason="Rejected by user"),
        ])

        result = await run_human_loop(run_fn=run_fn, decision_port=port)

        assert result.status == "blocked"
        assert result.turns == 1
        assert result.revisions == 0
        assert len(result.decisions) == 1
        assert result.decisions[0].decision_type == "not_go"


# ── Test: need_user → unknown → blocked ─────────────────


class TestNeedUserUnknownBlocks:
    """need_user + unknown decision blocks the loop immediately."""

    @pytest.mark.asyncio
    async def test_need_user_unknown_blocks(self) -> None:
        run_fn = _make_run_fn([
            RunResult(status="need_user"),
        ])
        port = StubDecisionPort([
            Decision(decision_type="unknown", reason="Could not determine"),
        ])

        result = await run_human_loop(run_fn=run_fn, decision_port=port)

        assert result.status == "blocked"
        assert result.turns == 1
        assert result.revisions == 0
        assert len(result.decisions) == 1
        assert result.decisions[0].decision_type == "unknown"


# ── Test: revise → pass ─────────────────────────────────


class TestReviseThenPass:
    """need_user + revise calls revise_fn, then pass on next run."""

    @pytest.mark.asyncio
    async def test_revise_then_pass(self) -> None:
        run_fn = _make_run_fn([
            RunResult(status="need_user", question="Correct this?"),
            RunResult(status="pass"),
        ])
        revise_fn = AsyncMock()
        port = StubDecisionPort([
            Decision(
                decision_type="revise",
                reason="Fix typo",
                revision_hint="Change name field",
            ),
        ])

        result = await run_human_loop(
            run_fn=run_fn,
            decision_port=port,
            revise_fn=revise_fn,
        )

        assert result.status == "pass"
        assert result.turns == 2
        assert result.revisions == 1
        assert len(result.decisions) == 1
        assert result.decisions[0].decision_type == "revise"
        assert result.decisions[0].revision_hint == "Change name field"
        revise_fn.assert_called_once()


# ── Test: revise without revise_fn ───────────────────────


class TestReviseWithoutReviseFn:
    """revise decision without revise_fn still increments revisions and continues."""

    @pytest.mark.asyncio
    async def test_revise_without_revise_fn(self) -> None:
        run_fn = _make_run_fn([
            RunResult(status="need_user"),
            RunResult(status="pass"),
        ])
        port = StubDecisionPort([
            Decision(decision_type="revise", reason="Try again"),
        ])

        result = await run_human_loop(
            run_fn=run_fn,
            decision_port=port,
            revise_fn=None,
        )

        assert result.status == "pass"
        assert result.turns == 2
        assert result.revisions == 1


# ── Test: max turns exceeded ────────────────────────────


class TestMaxTurnsExceeded:
    """Loop returns blocked when max_turns is exhausted."""

    @pytest.mark.asyncio
    async def test_max_turns_exceeded(self) -> None:
        # Every run returns need_user, every decision is go.
        run_fn = _make_run_fn([
            RunResult(status="need_user") for _ in range(3)
        ])
        port = StubDecisionPort([
            Decision(decision_type="go", reason="Continue") for _ in range(3)
        ])

        result = await run_human_loop(
            run_fn=run_fn,
            decision_port=port,
            max_turns=3,
        )

        assert result.status == "blocked"
        assert result.turns == 3
        assert result.revisions == 0
        assert len(result.decisions) == 3
        assert run_fn.call_count == 3


# ── Test: multiple revisions ────────────────────────────


class TestMultipleRevisions:
    """Multiple revise decisions accumulate revision count."""

    @pytest.mark.asyncio
    async def test_multiple_revisions(self) -> None:
        run_fn = _make_run_fn([
            RunResult(status="need_user", question="First?"),
            RunResult(status="need_user", question="Second?"),
            RunResult(status="need_user", question="Third?"),
            RunResult(status="pass"),
        ])
        revise_fn = AsyncMock()
        port = StubDecisionPort([
            Decision(decision_type="revise", reason="Fix 1"),
            Decision(decision_type="revise", reason="Fix 2"),
            Decision(decision_type="revise", reason="Fix 3"),
        ])

        result = await run_human_loop(
            run_fn=run_fn,
            decision_port=port,
            revise_fn=revise_fn,
        )

        assert result.status == "pass"
        assert result.turns == 4
        assert result.revisions == 3
        assert len(result.decisions) == 3
        assert revise_fn.call_count == 3


# ── Test: DecisionPort protocol ─────────────────────────


class TestDecisionPortProtocol:
    """DecisionPort is a runtime-checkable Protocol."""

    def test_stub_satisfies_protocol(self) -> None:
        port = StubDecisionPort([])
        assert isinstance(port, DecisionPort)

    def test_non_conforming_class_fails(self) -> None:
        class BadPort:
            pass

        assert not isinstance(BadPort(), DecisionPort)

    def test_decision_type_literal(self) -> None:
        """DecisionType accepts all four literal values."""
        valid_types: list[DecisionType] = ["go", "not_go", "revise", "unknown"]
        for dt in valid_types:
            d = Decision(decision_type=dt, reason="test")
            assert d.decision_type == dt


# ── Test: Frozen dataclasses ────────────────────────────


class TestFrozenDataclasses:
    """All dataclasses are frozen (immutable)."""

    def test_decision_is_frozen(self) -> None:
        d = Decision(decision_type="go", reason="ok")
        with pytest.raises(AttributeError):
            d.reason = "changed"  # type: ignore[misc]

    def test_run_result_is_frozen(self) -> None:
        r = RunResult(status="pass")
        with pytest.raises(AttributeError):
            r.status = "fail"  # type: ignore[misc]

    def test_human_loop_result_is_frozen(self) -> None:
        h = HumanLoopResult(status="pass", turns=1, revisions=0)
        with pytest.raises(AttributeError):
            h.status = "blocked"  # type: ignore[misc]
