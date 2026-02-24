"""Unit tests for Selector Recovery Pipeline — ``src.core.selector_recovery``.

Covers first-attempt pass, non-recoverable errors, successful recovery,
max-attempt exhaustion, missing patch function, LLM call counting,
candidate building, and multi-recovery attempts.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.core.selector_recovery import (
    SelectorRecoveryOutput,
    SelectorRecoveryRunResult,
    execute_with_selector_recovery,
)

# ── Helpers ─────────────────────────────────────────


def _make_pass_result() -> SelectorRecoveryRunResult:
    return SelectorRecoveryRunResult(status="pass")


def _make_fail_result(
    failure_code: str = "SelectorNotFound",
    candidates: list[Any] | None = None,
    proposed_patch: dict[str, Any] | None = None,
) -> SelectorRecoveryRunResult:
    return SelectorRecoveryRunResult(
        status="fail",
        failure_code=failure_code,
        candidates=candidates,
        proposed_patch=proposed_patch,
    )


# ── Tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_pass_on_first_attempt() -> None:
    """If run_fn passes immediately, return pass with 1 attempt and 0 LLM calls."""

    async def run_fn() -> SelectorRecoveryRunResult:
        return _make_pass_result()

    output = await execute_with_selector_recovery(run_fn=run_fn)

    assert output.status == "pass"
    assert output.attempts == 1
    assert output.llm_calls == 0
    assert output.recovered is False


@pytest.mark.asyncio
async def test_fail_non_selector_error() -> None:
    """Non-SelectorNotFound failures should not trigger recovery."""

    async def run_fn() -> SelectorRecoveryRunResult:
        return _make_fail_result(failure_code="NetworkError")

    async def suggest_patch_fn(candidates: list[Any] | None) -> dict[str, Any] | None:
        return {"selector": "#new"}

    output = await execute_with_selector_recovery(
        run_fn=run_fn,
        suggest_patch_fn=suggest_patch_fn,
        max_attempts=3,
    )

    assert output.status == "fail"
    assert output.attempts == 1
    assert output.llm_calls == 0
    assert output.recovered is False


@pytest.mark.asyncio
async def test_recovery_after_selector_not_found() -> None:
    """Recovery should succeed when run_fn passes on the second attempt."""
    call_count = 0

    async def run_fn() -> SelectorRecoveryRunResult:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_fail_result(failure_code="SelectorNotFound")
        return _make_pass_result()

    async def suggest_patch_fn(candidates: list[Any] | None) -> dict[str, Any] | None:
        return {"selector": "#recovered"}

    output = await execute_with_selector_recovery(
        run_fn=run_fn,
        suggest_patch_fn=suggest_patch_fn,
        max_attempts=2,
    )

    assert output.status == "pass"
    assert output.attempts == 2
    assert output.llm_calls == 1
    assert output.recovered is True


@pytest.mark.asyncio
async def test_recovery_fails_after_max_attempts() -> None:
    """When all attempts are exhausted the output should be fail."""

    async def run_fn() -> SelectorRecoveryRunResult:
        return _make_fail_result(failure_code="SelectorNotFound")

    async def suggest_patch_fn(candidates: list[Any] | None) -> dict[str, Any] | None:
        return {"selector": "#try-again"}

    output = await execute_with_selector_recovery(
        run_fn=run_fn,
        suggest_patch_fn=suggest_patch_fn,
        max_attempts=3,
    )

    assert output.status == "fail"
    assert output.attempts == 3
    assert output.llm_calls == 2  # one per recovery attempt (attempts 2 and 3)
    assert output.recovered is False


@pytest.mark.asyncio
async def test_no_patch_fn_returns_fail() -> None:
    """Without a suggest_patch_fn the pipeline cannot recover and should fail."""

    async def run_fn() -> SelectorRecoveryRunResult:
        return _make_fail_result(failure_code="SelectorNotFound")

    output = await execute_with_selector_recovery(
        run_fn=run_fn,
        suggest_patch_fn=None,
        max_attempts=3,
    )

    assert output.status == "fail"
    assert output.attempts == 1
    assert output.llm_calls == 0
    assert output.recovered is False


@pytest.mark.asyncio
async def test_llm_calls_counted() -> None:
    """Each invocation of suggest_patch_fn should increment llm_calls."""
    call_count = 0
    patch_calls = 0

    async def run_fn() -> SelectorRecoveryRunResult:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return _make_fail_result(failure_code="SelectorNotFound")
        return _make_pass_result()

    async def suggest_patch_fn(candidates: list[Any] | None) -> dict[str, Any] | None:
        nonlocal patch_calls
        patch_calls += 1
        return {"selector": f"#patch-{patch_calls}"}

    output = await execute_with_selector_recovery(
        run_fn=run_fn,
        suggest_patch_fn=suggest_patch_fn,
        max_attempts=4,
    )

    assert output.status == "pass"
    assert output.attempts == 3
    assert output.llm_calls == 2
    assert patch_calls == 2
    assert output.recovered is True


@pytest.mark.asyncio
async def test_build_candidates_called() -> None:
    """build_candidates_fn should be called and its result forwarded to suggest_patch_fn."""
    candidates_received: list[Any] = []
    build_called = False

    async def run_fn() -> SelectorRecoveryRunResult:
        if not candidates_received:
            return _make_fail_result(failure_code="SelectorNotFound")
        return _make_pass_result()

    async def build_candidates_fn() -> list[Any]:
        nonlocal build_called
        build_called = True
        return [{"eid": "#btn-submit", "type": "button", "text": "Submit"}]

    async def suggest_patch_fn(candidates: list[Any] | None) -> dict[str, Any] | None:
        if candidates is not None:
            candidates_received.extend(candidates)
        return {"selector": "#btn-submit"}

    output = await execute_with_selector_recovery(
        run_fn=run_fn,
        build_candidates_fn=build_candidates_fn,
        suggest_patch_fn=suggest_patch_fn,
        max_attempts=2,
    )

    assert build_called is True
    assert len(candidates_received) == 1
    assert candidates_received[0]["eid"] == "#btn-submit"
    assert output.status == "pass"
    assert output.recovered is True


@pytest.mark.asyncio
async def test_multiple_recovery_attempts() -> None:
    """The pipeline should retry multiple times before succeeding."""
    call_count = 0

    async def run_fn() -> SelectorRecoveryRunResult:
        nonlocal call_count
        call_count += 1
        # Fail on attempts 1, 2, 3 — succeed on attempt 4
        if call_count < 4:
            return _make_fail_result(failure_code="SelectorNotFound")
        return _make_pass_result()

    async def suggest_patch_fn(candidates: list[Any] | None) -> dict[str, Any] | None:
        return {"selector": f"#attempt-{call_count}"}

    output = await execute_with_selector_recovery(
        run_fn=run_fn,
        suggest_patch_fn=suggest_patch_fn,
        max_attempts=5,
    )

    assert output.status == "pass"
    assert output.attempts == 4
    assert output.llm_calls == 3
    assert output.recovered is True


@pytest.mark.asyncio
async def test_suggest_patch_returns_none_aborts() -> None:
    """If suggest_patch_fn returns None, recovery should abort immediately."""

    async def run_fn() -> SelectorRecoveryRunResult:
        return _make_fail_result(failure_code="SelectorNotFound")

    async def suggest_patch_fn(candidates: list[Any] | None) -> dict[str, Any] | None:
        return None

    output = await execute_with_selector_recovery(
        run_fn=run_fn,
        suggest_patch_fn=suggest_patch_fn,
        max_attempts=3,
    )

    assert output.status == "fail"
    assert output.attempts == 1
    assert output.llm_calls == 1  # still counts the call even though it returned None
    assert output.recovered is False


@pytest.mark.asyncio
async def test_frozen_dataclasses() -> None:
    """SelectorRecoveryRunResult and SelectorRecoveryOutput should be immutable."""
    run_result = _make_pass_result()
    with pytest.raises(AttributeError):
        run_result.status = "fail"  # type: ignore[misc]

    output = SelectorRecoveryOutput(
        status="pass", attempts=1, llm_calls=0, recovered=False,
    )
    with pytest.raises(AttributeError):
        output.status = "fail"  # type: ignore[misc]
