"""Chat automation service — pause/resume/cancel + captcha + image."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class RunStatus(StrEnum):
    """Status of a chat automation run."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_CAPTCHA = "waiting_captcha"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass
class ChatAutomationState:
    """Mutable state for a running chat automation."""
    run_id: str
    session_id: str
    status: RunStatus = RunStatus.IDLE
    current_step: int = 0
    total_steps: int = 0
    pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_flag: bool = False
    captcha_future: asyncio.Future[str] | None = None
    error: str | None = None
    image_paths: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.pause_event.set()  # Start in running (not paused) state


class ChatAutomationService:
    """Manages chat automation runs with pause/resume/cancel support."""

    def __init__(
        self,
        session_manager: Any = None,
        image_dir: str = "data/chat_images",
    ) -> None:
        self._session_manager = session_manager
        self._image_dir = image_dir
        self._runs: dict[str, ChatAutomationState] = {}
        self._session_runs: dict[str, str] = {}  # session_id -> active run_id

    async def start_run(
        self,
        session_id: str,
        instruction: str,
        headless: bool = True,
    ) -> str:
        """Start a new automation run.

        Args:
            session_id: Session to run in.
            instruction: Natural language instruction.
            headless: Whether to run headless.

        Returns:
            run_id: Unique run identifier.

        Raises:
            RuntimeError: If session already has an active run.
        """
        if session_id in self._session_runs:
            existing = self._session_runs[session_id]
            existing_state = self._runs.get(existing)
            if existing_state and existing_state.status in (
                RunStatus.RUNNING, RunStatus.PAUSED, RunStatus.WAITING_CAPTCHA
            ):
                raise RuntimeError(
                    f"Session {session_id} already has active run {existing}"
                )

        run_id = str(uuid.uuid4())
        state = ChatAutomationState(run_id=run_id, session_id=session_id)
        state.status = RunStatus.RUNNING
        self._runs[run_id] = state
        self._session_runs[session_id] = run_id

        # Start execution in background task
        asyncio.create_task(self._run_automation(run_id, session_id, instruction))
        return run_id

    async def _run_automation(
        self, run_id: str, session_id: str, instruction: str,
    ) -> None:
        """Background task that executes the automation."""
        state = self._runs[run_id]
        try:
            if self._session_manager is not None:
                result = await self._session_manager.execute_turn(
                    session_id, instruction,
                )
                state.status = (
                    RunStatus.COMPLETED if result.get("success", False)
                    else RunStatus.FAILED
                )
            else:
                state.status = RunStatus.COMPLETED
        except asyncio.CancelledError:
            state.status = RunStatus.CANCELED
        except Exception as exc:
            logger.error("Chat automation run %s failed: %s", run_id, exc)
            state.status = RunStatus.FAILED
            state.error = str(exc)

    async def pause(self, run_id: str) -> None:
        """Pause a running automation."""
        state = self._get_state(run_id)
        if state.status not in (RunStatus.RUNNING,):
            raise RuntimeError(
                f"Cannot pause run in status {state.status.value}"
            )
        state.pause_event.clear()
        state.status = RunStatus.PAUSED

    async def resume(self, run_id: str) -> None:
        """Resume a paused automation."""
        state = self._get_state(run_id)
        if state.status != RunStatus.PAUSED:
            raise RuntimeError(
                f"Cannot resume run in status {state.status.value}"
            )
        state.pause_event.set()
        state.status = RunStatus.RUNNING

    async def cancel(self, run_id: str) -> None:
        """Cancel a running or paused automation."""
        state = self._get_state(run_id)
        if state.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELED):
            raise RuntimeError(
                f"Cannot cancel run in status {state.status.value}"
            )
        state.cancel_flag = True
        state.pause_event.set()  # Unblock if paused
        state.status = RunStatus.CANCELED

    async def submit_captcha(self, run_id: str, solution: str) -> None:
        """Submit a CAPTCHA solution."""
        state = self._get_state(run_id)
        if state.captcha_future is not None and not state.captcha_future.done():
            state.captcha_future.set_result(solution)
            state.status = RunStatus.RUNNING

    async def attach_image(
        self, run_id: str, image_data: bytes, filename: str,
    ) -> str:
        """Attach an image to the current run.

        Returns:
            Path where the image was saved.
        """
        state = self._get_state(run_id)
        os.makedirs(self._image_dir, exist_ok=True)
        safe_name = f"{run_id}_{filename}"
        path = os.path.join(self._image_dir, safe_name)
        with open(path, "wb") as f:
            f.write(image_data)
        state.image_paths.append(path)
        return path

    async def get_status(self, run_id: str) -> dict[str, Any]:
        """Get current run status."""
        state = self._get_state(run_id)
        return {
            "run_id": state.run_id,
            "session_id": state.session_id,
            "status": state.status.value,
            "current_step": state.current_step,
            "total_steps": state.total_steps,
            "error": state.error,
        }

    def _get_state(self, run_id: str) -> ChatAutomationState:
        """Get state or raise KeyError."""
        if run_id not in self._runs:
            raise KeyError(f"Unknown run_id: {run_id}")
        return self._runs[run_id]
