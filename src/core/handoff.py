"""H(Human Handoff) — Human-in-the-loop interface for unresolvable situations.

Token cost: 0 (pure coordination, no LLM calls).

The handoff manager provides a structured interface for requesting human
intervention when the automation encounters situations it cannot resolve
autonomously: CAPTCHA challenges, 2FA verification, payment flows, and
age verification gates.

* **request_handoff** — creates a ``HandoffRequest`` and notifies callbacks.
* **wait_for_resolution** — blocks (via asyncio.Event) until ``resolve()``
  is called or timeout is reached.
* **resolve** — marks a pending request as resolved and unblocks waiters.
* **get_pending** — returns all unresolved handoff requests.
* **get_history** — returns all requests with their responses (if any).
* **on_handoff** — registers a callback to be invoked on new handoff requests.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)


# ── Enums ────────────────────────────────────────────


class HandoffReason(str, Enum):
    """Reason for requesting human handoff."""
    CAPTCHA = "captcha"
    AUTH_2FA = "2fa"
    PAYMENT = "payment"
    AGE_VERIFY = "age_verify"
    CUSTOM = "custom"


# ── Data Classes ─────────────────────────────────────


@dataclass
class HandoffRequest:
    """A request for human intervention.

    Attributes:
        reason: Why handoff is needed.
        url: Current page URL.
        title: Current page title.
        screenshot: Optional screenshot bytes for context.
        message: Human-readable description of what is needed.
        metadata: Additional context data.
        created_at: ISO 8601 timestamp of when the request was created.
        request_id: Unique identifier (UUID4).
    """
    reason: HandoffReason
    url: str
    title: str
    screenshot: bytes | None = None
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    request_id: str = ""


@dataclass
class HandoffResponse:
    """Response to a handoff request.

    Attributes:
        request_id: The ID of the request this responds to.
        resolved: Whether the situation was successfully resolved.
        action_taken: Description of what the human did.
        metadata: Additional response data.
    """
    request_id: str
    resolved: bool
    action_taken: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Exceptions ───────────────────────────────────────


class HandoffTimeoutError(Exception):
    """Raised when wait_for_resolution exceeds the timeout."""


class HandoffNotFoundError(Exception):
    """Raised when referencing a non-existent handoff request_id."""


# ── HandoffManager ───────────────────────────────────


class HandoffManager:
    """Manages human-in-the-loop handoff requests.

    The manager tracks pending requests, notifies registered callbacks,
    and coordinates resolution via asyncio events.

    Example::

        manager = HandoffManager()
        manager.on_handoff(lambda req: print(f"Handoff needed: {req.reason}"))

        request = await manager.request_handoff(
            reason=HandoffReason.CAPTCHA,
            url="https://example.com/login",
            title="Login Page",
            message="reCAPTCHA detected, please solve it.",
        )

        # In another coroutine or thread:
        await manager.resolve(request.request_id, action_taken="Solved CAPTCHA")

        # The original waiter:
        response = await manager.wait_for_resolution(request.request_id)
        assert response.resolved is True
    """

    def __init__(self) -> None:
        self._pending: dict[str, HandoffRequest] = {}
        self._responses: dict[str, HandoffResponse] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._history: list[tuple[HandoffRequest, HandoffResponse | None]] = []
        self._callbacks: list[Callable[[HandoffRequest], None]] = []

    # ── Public API ───────────────────────────────────

    async def request_handoff(
        self,
        reason: HandoffReason,
        url: str,
        title: str,
        screenshot: bytes | None = None,
        message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> HandoffRequest:
        """Create a handoff request and notify registered callbacks.

        Args:
            reason: Why handoff is needed.
            url: Current page URL.
            title: Current page title.
            screenshot: Optional screenshot bytes.
            message: Human-readable message.
            metadata: Additional context.

        Returns:
            The created ``HandoffRequest``.
        """
        request_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        request = HandoffRequest(
            reason=reason,
            url=url,
            title=title,
            screenshot=screenshot,
            message=message,
            metadata=metadata or {},
            created_at=created_at,
            request_id=request_id,
        )

        self._pending[request_id] = request
        self._events[request_id] = asyncio.Event()
        self._history.append((request, None))

        logger.info(
            "Handoff requested: id=%s reason=%s url=%s",
            request_id,
            reason.value,
            url,
        )

        # Notify callbacks.
        for callback in self._callbacks:
            try:
                callback(request)
            except Exception:
                logger.exception("Handoff callback failed")

        return request

    async def wait_for_resolution(
        self, request_id: str, timeout_s: float = 300.0
    ) -> HandoffResponse:
        """Wait for a handoff request to be resolved.

        Blocks until ``resolve()`` is called for the given request_id
        or the timeout is exceeded.

        Args:
            request_id: The request ID to wait on.
            timeout_s: Maximum seconds to wait (default 300s / 5 minutes).

        Returns:
            The ``HandoffResponse`` after resolution.

        Raises:
            HandoffNotFoundError: If request_id is not known.
            HandoffTimeoutError: If timeout is exceeded.
        """
        event = self._events.get(request_id)
        if event is None:
            # Check if already resolved.
            if request_id in self._responses:
                return self._responses[request_id]
            raise HandoffNotFoundError(
                f"No handoff request found with id={request_id}"
            )

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            raise HandoffTimeoutError(
                f"Handoff request {request_id} timed out after {timeout_s}s"
            ) from None

        return self._responses[request_id]

    async def resolve(
        self,
        request_id: str,
        action_taken: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Resolve a pending handoff request.

        Args:
            request_id: The request ID to resolve.
            action_taken: Description of what the human did.
            metadata: Additional response data.

        Raises:
            HandoffNotFoundError: If request_id is not in pending.
        """
        if request_id not in self._pending:
            raise HandoffNotFoundError(
                f"No pending handoff request with id={request_id}"
            )

        response = HandoffResponse(
            request_id=request_id,
            resolved=True,
            action_taken=action_taken,
            metadata=metadata or {},
        )

        self._responses[request_id] = response

        # Update history entry.
        for i, (req, _resp) in enumerate(self._history):
            if req.request_id == request_id:
                self._history[i] = (req, response)
                break

        # Remove from pending.
        del self._pending[request_id]

        # Signal waiters.
        event = self._events.pop(request_id, None)
        if event is not None:
            event.set()

        logger.info(
            "Handoff resolved: id=%s action=%s",
            request_id,
            action_taken,
        )

    def get_pending(self) -> list[HandoffRequest]:
        """Return all unresolved handoff requests.

        Returns:
            List of pending ``HandoffRequest`` objects.
        """
        return list(self._pending.values())

    def get_history(self) -> list[tuple[HandoffRequest, HandoffResponse | None]]:
        """Return all handoff requests with their responses.

        Returns:
            List of ``(HandoffRequest, HandoffResponse | None)`` tuples.
            Response is ``None`` if the request has not been resolved yet.
        """
        return list(self._history)

    def on_handoff(self, callback: Callable[[HandoffRequest], None]) -> None:
        """Register a callback to be invoked on new handoff requests.

        The callback receives the ``HandoffRequest`` object and should
        not raise exceptions (they are caught and logged).

        Args:
            callback: A callable accepting a ``HandoffRequest``.
        """
        self._callbacks.append(callback)

    def clear(self) -> None:
        """Clear all state (pending, responses, history, events).

        Useful for testing or resetting the manager.
        """
        self._pending.clear()
        self._responses.clear()
        self._events.clear()
        self._history.clear()
