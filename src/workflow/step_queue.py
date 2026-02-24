"""Step Queue Manager — async-compatible queue for workflow step execution.

Manages the ordered execution of ``StepDefinition`` objects, tracking
completed and failed steps separately. Supports re-queuing failed steps
for retry.

See docs/ARCHITECTURE.md for how the Orchestrator consumes the queue.
"""
from __future__ import annotations

import logging
from collections import deque

from src.core.types import StepDefinition

logger = logging.getLogger(__name__)


class StepQueue:
    """Async-compatible queue holding ``StepDefinition`` objects.

    Maintains three internal collections:
    - ``_pending``: Steps waiting to be executed (FIFO deque).
    - ``_completed``: Steps that succeeded.
    - ``_failed``: Steps that failed after all attempts.

    Example::

        queue = StepQueue()
        queue.push_many(parsed_steps)
        while not queue.is_empty():
            step = queue.pop()
            result = await orchestrator.execute_step(step)
            if result.success:
                queue.mark_completed(step)
            else:
                queue.mark_failed(step)
    """

    def __init__(self) -> None:
        self._pending: deque[StepDefinition] = deque()
        self._completed: list[StepDefinition] = []
        self._failed: list[StepDefinition] = []

    def push(self, step: StepDefinition) -> None:
        """Add a single step to the end of the pending queue.

        Args:
            step: The step definition to enqueue.
        """
        self._pending.append(step)
        logger.debug("Pushed step '%s' to queue (size=%d)", step.step_id, len(self._pending))

    def push_many(self, steps: list[StepDefinition]) -> None:
        """Add multiple steps to the end of the pending queue in order.

        Args:
            steps: Ordered list of step definitions to enqueue.
        """
        for step in steps:
            self._pending.append(step)
        logger.debug("Pushed %d steps to queue (size=%d)", len(steps), len(self._pending))

    def pop(self) -> StepDefinition | None:
        """Remove and return the next pending step.

        Returns:
            The next ``StepDefinition``, or ``None`` if the queue is empty.
        """
        if not self._pending:
            return None
        step = self._pending.popleft()
        logger.debug("Popped step '%s' from queue (remaining=%d)", step.step_id, len(self._pending))
        return step

    def peek(self) -> StepDefinition | None:
        """Return the next pending step without removing it.

        Returns:
            The next ``StepDefinition``, or ``None`` if the queue is empty.
        """
        if not self._pending:
            return None
        return self._pending[0]

    def is_empty(self) -> bool:
        """Check whether the pending queue is empty.

        Returns:
            ``True`` if no pending steps remain.
        """
        return len(self._pending) == 0

    def size(self) -> int:
        """Return the number of pending steps.

        Returns:
            Count of steps waiting to be executed.
        """
        return len(self._pending)

    def clear(self) -> None:
        """Remove all pending steps from the queue.

        Does not affect completed or failed step records.
        """
        count = len(self._pending)
        self._pending.clear()
        logger.debug("Cleared %d pending steps from queue", count)

    def mark_completed(self, step: StepDefinition) -> None:
        """Record a step as successfully completed.

        Args:
            step: The step that succeeded.
        """
        self._completed.append(step)
        logger.debug(
            "Marked step '%s' as completed (total completed=%d)",
            step.step_id,
            len(self._completed),
        )

    def mark_failed(self, step: StepDefinition) -> None:
        """Record a step as failed (after exhausting all attempts).

        Args:
            step: The step that failed.
        """
        self._failed.append(step)
        logger.debug(
            "Marked step '%s' as failed (total failed=%d)",
            step.step_id,
            len(self._failed),
        )

    def requeue_failed(self) -> int:
        """Move all failed steps back to the pending queue for retry.

        Returns:
            Number of steps re-queued.
        """
        count = len(self._failed)
        for step in self._failed:
            self._pending.append(step)
        self._failed.clear()
        logger.debug("Re-queued %d failed steps", count)
        return count

    @property
    def completed(self) -> list[StepDefinition]:
        """Return a copy of completed steps.

        Returns:
            List of steps that succeeded.
        """
        return list(self._completed)

    @property
    def failed(self) -> list[StepDefinition]:
        """Return a copy of failed steps.

        Returns:
            List of steps that failed.
        """
        return list(self._failed)

    @property
    def pending(self) -> list[StepDefinition]:
        """Return a copy of pending steps in queue order.

        Returns:
            List of steps waiting to be executed.
        """
        return list(self._pending)
