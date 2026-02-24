"""IProgressCallback → SSE bridge adapter.

Converts orchestrator progress events into Notifier SSE broadcasts
so that connected clients receive real-time step updates.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.core.types import ProgressInfo
from src.evolution.notifier import Notifier

logger = logging.getLogger(__name__)


class NotifierProgressCallback:
    """IProgressCallback implementation that publishes to SSE via Notifier.

    Args:
        notifier: SSE event broadcaster.
        session_id: Session to tag events with.
    """

    def __init__(self, notifier: Notifier, session_id: str) -> None:
        self._notifier = notifier
        self._session_id = session_id

    def on_progress(self, info: ProgressInfo) -> None:
        """Convert a ProgressInfo into an SSE event."""
        data: dict[str, Any] = {
            "session_id": self._session_id,
            "event": info.event.value,
            "step_id": info.step_id,
            "step_index": info.step_index,
            "total_steps": info.total_steps,
            "method": info.method,
            "attempt": info.attempt,
            "message": info.message,
        }
        try:
            asyncio.ensure_future(
                self._notifier.publish("session_progress", data),
            )
        except RuntimeError:
            # No running event loop (e.g. during shutdown)
            logger.debug("Cannot publish progress — no event loop")
