"""
Run-recipe API: spawn node-runtime CLI, stream JSONL→SSE, cancel support.

POST /            — start a run (recipe JSON in body)
GET  /stream/{id} — SSE stream of JSONL events
POST /cancel/{id} — send SIGTERM to running subprocess
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

# ── active runs registry ──────────────────────────

class _ActiveRun:
    def __init__(self, proc: asyncio.subprocess.Process):
        self.proc = proc
        self.lines: list[str] = []
        self.done = asyncio.Event()
        self.subscribers: list[asyncio.Queue[str | None]] = []

_active_runs: dict[str, _ActiveRun] = {}

RUN_TIMEOUT_S = 120


# ── request / response models ─────────────────────

class RunRecipeRequest(BaseModel):
    recipe: dict[str, Any]
    options: dict[str, Any] | None = None


class RunStartResponse(BaseModel):
    runId: str


# ── background reader ─────────────────────────────

async def _read_stdout(run_id: str, run: _ActiveRun) -> None:
    """Read subprocess stdout line-by-line, broadcast to subscribers."""
    try:
        assert run.proc.stdout is not None
        while True:
            line_bytes = await asyncio.wait_for(
                run.proc.stdout.readline(), timeout=RUN_TIMEOUT_S
            )
            if not line_bytes:
                break
            line = line_bytes.decode().rstrip("\n")
            if not line:
                continue
            run.lines.append(line)
            for q in run.subscribers:
                await q.put(line)
    except asyncio.TimeoutError:
        error_line = json.dumps({"type": "run_error", "error": f"Timeout after {RUN_TIMEOUT_S}s"})
        run.lines.append(error_line)
        for q in run.subscribers:
            await q.put(error_line)
        run.proc.kill()
    except Exception:
        pass
    finally:
        # If no output was produced, check stderr for error info
        if not run.lines and run.proc.stderr:
            try:
                stderr_bytes = await asyncio.wait_for(run.proc.stderr.read(), timeout=5)
                if stderr_bytes:
                    err_msg = stderr_bytes.decode().strip()
                    error_line = json.dumps({"type": "run_error", "error": f"Subprocess error: {err_msg[:500]}"})
                    run.lines.append(error_line)
                    for q in run.subscribers:
                        await q.put(error_line)
            except Exception:
                pass
        # Signal end-of-stream to subscribers
        for q in run.subscribers:
            await q.put(None)
        run.done.set()
        _active_runs.pop(run_id, None)


# ── endpoints ──────────────────────────────────────

@router.post("/", response_model=RunStartResponse)
async def start_run(req: RunRecipeRequest) -> RunStartResponse:
    run_id = f"run-{uuid.uuid4().hex[:12]}"

    payload = json.dumps({"recipe": req.recipe, "options": req.options or {}})

    # Resolve project root (one level up from python-authoring-service/)
    project_root = str(Path(__file__).resolve().parents[3])

    proc = await asyncio.create_subprocess_exec(
        "npx", "tsx", "node-runtime/src/cli/run-recipe.ts",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=project_root,
    )

    # Feed recipe via stdin then close
    assert proc.stdin is not None
    proc.stdin.write(payload.encode())
    await proc.stdin.drain()
    proc.stdin.close()

    run = _ActiveRun(proc)
    _active_runs[run_id] = run

    # Start background reader
    asyncio.create_task(_read_stdout(run_id, run))

    return RunStartResponse(runId=run_id)


@router.get("/stream/{run_id}")
async def stream_run(run_id: str) -> StreamingResponse:
    run = _active_runs.get(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id} not found or already finished")

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    # Replay buffered lines
    for line in run.lines:
        await queue.put(line)

    # If already done, signal end
    if run.done.is_set():
        await queue.put(None)
    else:
        run.subscribers.append(queue)

    async def event_generator():
        try:
            while True:
                line = await queue.get()
                if line is None:
                    break
                yield f"data: {line}\n\n"
        finally:
            if queue in run.subscribers:
                run.subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/cancel/{run_id}")
async def cancel_run(run_id: str) -> dict[str, str]:
    run = _active_runs.get(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id} not found or already finished")

    try:
        run.proc.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        pass

    return {"status": "cancelled", "runId": run_id}
