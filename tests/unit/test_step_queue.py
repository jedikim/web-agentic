"""Unit tests for StepQueue — async-compatible step queue manager.

Tests verify:
  - push / push_many / pop / peek / is_empty / size / clear
  - FIFO ordering
  - Completed and failed step tracking
  - Re-queuing failed steps for retry
  - Edge cases: pop from empty, peek from empty, requeue when no failures
"""
from __future__ import annotations

from src.core.types import StepDefinition
from src.workflow.step_queue import StepQueue

# ── Helpers ──────────────────────────────────────────


def _make_step(step_id: str, intent: str = "test intent") -> StepDefinition:
    """Create a minimal StepDefinition for testing."""
    return StepDefinition(step_id=step_id, intent=intent)


# ── push / pop ───────────────────────────────────────


def test_push_and_pop_single() -> None:
    """push() adds a step; pop() returns it."""
    q = StepQueue()
    step = _make_step("s1")
    q.push(step)
    assert q.pop() is step


def test_pop_returns_none_when_empty() -> None:
    """pop() returns None on an empty queue."""
    q = StepQueue()
    assert q.pop() is None


def test_push_pop_fifo_order() -> None:
    """Steps are dequeued in FIFO order."""
    q = StepQueue()
    s1 = _make_step("s1")
    s2 = _make_step("s2")
    s3 = _make_step("s3")
    q.push(s1)
    q.push(s2)
    q.push(s3)

    assert q.pop() is s1
    assert q.pop() is s2
    assert q.pop() is s3
    assert q.pop() is None


# ── push_many ────────────────────────────────────────


def test_push_many() -> None:
    """push_many() enqueues all steps in order."""
    q = StepQueue()
    steps = [_make_step(f"s{i}") for i in range(5)]
    q.push_many(steps)

    assert q.size() == 5
    for i in range(5):
        popped = q.pop()
        assert popped is not None
        assert popped.step_id == f"s{i}"


def test_push_many_empty_list() -> None:
    """push_many([]) is a no-op."""
    q = StepQueue()
    q.push_many([])
    assert q.is_empty()


# ── peek ─────────────────────────────────────────────


def test_peek_returns_front_without_removing() -> None:
    """peek() shows the next step but does not remove it."""
    q = StepQueue()
    s1 = _make_step("s1")
    s2 = _make_step("s2")
    q.push(s1)
    q.push(s2)

    assert q.peek() is s1
    assert q.size() == 2  # not removed
    assert q.peek() is s1  # still the same


def test_peek_empty() -> None:
    """peek() returns None on an empty queue."""
    q = StepQueue()
    assert q.peek() is None


# ── is_empty / size ──────────────────────────────────


def test_is_empty_initially() -> None:
    """New queue starts empty."""
    q = StepQueue()
    assert q.is_empty()
    assert q.size() == 0


def test_is_empty_after_push() -> None:
    """Queue is not empty after push."""
    q = StepQueue()
    q.push(_make_step("s1"))
    assert not q.is_empty()
    assert q.size() == 1


def test_is_empty_after_pop_all() -> None:
    """Queue is empty after popping all items."""
    q = StepQueue()
    q.push(_make_step("s1"))
    q.pop()
    assert q.is_empty()
    assert q.size() == 0


# ── clear ────────────────────────────────────────────


def test_clear_removes_all_pending() -> None:
    """clear() empties the pending queue."""
    q = StepQueue()
    q.push_many([_make_step(f"s{i}") for i in range(3)])
    assert q.size() == 3

    q.clear()
    assert q.is_empty()
    assert q.size() == 0
    assert q.pop() is None


def test_clear_does_not_affect_completed_or_failed() -> None:
    """clear() only removes pending steps, not completed/failed records."""
    q = StepQueue()
    s1 = _make_step("s1")
    s2 = _make_step("s2")
    s3 = _make_step("s3")

    q.mark_completed(s1)
    q.mark_failed(s2)
    q.push(s3)

    q.clear()

    assert q.is_empty()
    assert len(q.completed) == 1
    assert len(q.failed) == 1


# ── mark_completed / mark_failed ─────────────────────


def test_mark_completed() -> None:
    """mark_completed() records the step in completed list."""
    q = StepQueue()
    s1 = _make_step("s1")
    q.mark_completed(s1)

    assert len(q.completed) == 1
    assert q.completed[0] is s1


def test_mark_failed() -> None:
    """mark_failed() records the step in failed list."""
    q = StepQueue()
    s1 = _make_step("s1")
    q.mark_failed(s1)

    assert len(q.failed) == 1
    assert q.failed[0] is s1


def test_multiple_completed_and_failed() -> None:
    """Multiple steps can be tracked as completed or failed."""
    q = StepQueue()
    q.mark_completed(_make_step("c1"))
    q.mark_completed(_make_step("c2"))
    q.mark_failed(_make_step("f1"))
    q.mark_failed(_make_step("f2"))
    q.mark_failed(_make_step("f3"))

    assert len(q.completed) == 2
    assert len(q.failed) == 3


# ── requeue_failed ───────────────────────────────────


def test_requeue_failed_moves_to_pending() -> None:
    """requeue_failed() moves all failed steps back to pending queue."""
    q = StepQueue()
    f1 = _make_step("f1")
    f2 = _make_step("f2")
    q.mark_failed(f1)
    q.mark_failed(f2)

    count = q.requeue_failed()

    assert count == 2
    assert len(q.failed) == 0
    assert q.size() == 2
    assert q.pop() is f1
    assert q.pop() is f2


def test_requeue_failed_with_no_failures() -> None:
    """requeue_failed() returns 0 when there are no failed steps."""
    q = StepQueue()
    count = q.requeue_failed()
    assert count == 0
    assert q.is_empty()


def test_requeue_failed_appends_after_existing_pending() -> None:
    """Re-queued steps are appended after currently pending steps."""
    q = StepQueue()
    p1 = _make_step("p1")
    f1 = _make_step("f1")

    q.push(p1)
    q.mark_failed(f1)
    q.requeue_failed()

    # p1 should come first (was already pending), then f1
    assert q.pop() is p1
    assert q.pop() is f1


# ── pending property ─────────────────────────────────


def test_pending_returns_copy() -> None:
    """pending property returns a list copy, not the internal deque."""
    q = StepQueue()
    q.push(_make_step("s1"))
    q.push(_make_step("s2"))

    pending = q.pending
    assert len(pending) == 2
    assert pending[0].step_id == "s1"
    assert pending[1].step_id == "s2"

    # Modifying the returned list should not affect the queue
    pending.clear()
    assert q.size() == 2


def test_completed_returns_copy() -> None:
    """completed property returns a list copy."""
    q = StepQueue()
    q.mark_completed(_make_step("c1"))

    completed = q.completed
    completed.clear()
    assert len(q.completed) == 1


def test_failed_returns_copy() -> None:
    """failed property returns a list copy."""
    q = StepQueue()
    q.mark_failed(_make_step("f1"))

    failed = q.failed
    failed.clear()
    assert len(q.failed) == 1
