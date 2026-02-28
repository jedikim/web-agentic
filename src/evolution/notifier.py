"""SSE event broadcaster for the evolution system.

Uses asyncio.Queue to fan-out events to multiple SSE clients.
Event types: evolution_status, scenario_progress, version_created.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SSEEvent:
    """A single Server-Sent Event."""
    event: str
    data: dict[str, Any]
    id: str | None = None


class Notifier:
    """Broadcasts SSE events to all connected clients."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[SSEEvent | None]] = []
        self._lock = asyncio.Lock()
        self._event_counter = 0

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish an event to all subscribers."""
        self._event_counter += 1
        evt = SSEEvent(event=event_type, data=data, id=str(self._event_counter))
        async with self._lock:
            dead: list[asyncio.Queue[SSEEvent | None]] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(evt)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)
        logger.debug("Published %s to %d subscribers", event_type, len(self._subscribers))

    async def subscribe(self) -> AsyncIterator[SSEEvent]:
        """Subscribe to events. Yields SSEEvent objects."""
        q: asyncio.Queue[SSEEvent | None] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers.append(q)
        try:
            while True:
                evt = await q.get()
                if evt is None:
                    break
                yield evt
        finally:
            async with self._lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)

    async def close(self) -> None:
        """Signal all subscribers to stop."""
        async with self._lock:
            for q in self._subscribers:
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(None)
            self._subscribers.clear()

    def format_sse(self, evt: SSEEvent) -> str:
        """Format an SSEEvent as an SSE text message."""
        lines: list[str] = []
        if evt.id:
            lines.append(f"id: {evt.id}")
        lines.append(f"event: {evt.event}")
        lines.append(f"data: {json.dumps(evt.data)}")
        lines.append("")
        lines.append("")
        return "\n".join(lines)
