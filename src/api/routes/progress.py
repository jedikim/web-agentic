"""SSE progress stream route."""
from __future__ import annotations

import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from src.api.dependencies import get_notifier

router = APIRouter(prefix="/api/progress", tags=["progress"])


@router.get("/stream")
async def sse_stream() -> EventSourceResponse:
    """SSE stream for real-time progress updates."""
    notifier = get_notifier()

    async def event_generator():  # type: ignore[no-untyped-def]
        async for evt in notifier.subscribe():
            yield {
                "event": evt.event,
                "data": json.dumps(evt.data),
                "id": evt.id,
            }

    return EventSourceResponse(event_generator())
