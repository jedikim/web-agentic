"""Session Manager — manages live browser sessions and orchestration.

Bridges the API layer with the core automation engine. Each session holds
a live Executor + LLMFirstOrchestrator pair. The manager handles lifecycle,
turn execution, handoffs, and idle cleanup.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any

from src.ai.llm_planner import create_llm_planner
from src.api.progress_adapter import NotifierProgressCallback
from src.api.session_db import SessionDB
from src.core.executor import Executor
from src.core.executor_pool import ExecutorPool
from src.core.extractor import DOMExtractor
from src.core.fallback_router import FallbackRouter
from src.core.handoff import HandoffManager
from src.core.llm_orchestrator import LLMFirstOrchestrator, RunResult
from src.core.selector_cache import SelectorCache
from src.core.verifier import Verifier
from src.evolution.notifier import Notifier

logger = logging.getLogger(__name__)


# ── Exceptions ───────────────────────────────────────


class SessionNotFoundError(Exception):
    """Raised when a session ID is not found in live sessions."""


# ── Live Session ─────────────────────────────────────


@dataclass
class LiveSession:
    """In-memory state for an active browser session.

    Attributes:
        session_id: Unique session identifier.
        executor: Playwright browser wrapper.
        orchestrator: LLM-First orchestrator for this session.
        handoff_manager: Human handoff coordinator.
        headless: Whether the browser is headless.
        turn_count: Number of turns executed.
        total_cost_usd: Accumulated cost in USD.
        running_task: The currently executing asyncio.Task, if any.
    """

    session_id: str
    executor: Executor
    orchestrator: LLMFirstOrchestrator
    handoff_manager: HandoffManager
    headless: bool = True
    turn_count: int = 0
    total_cost_usd: float = 0.0
    running_task: asyncio.Task[Any] | None = None


# ── Session Manager ──────────────────────────────────


class SessionManager:
    """Manages live browser sessions with automation orchestration.

    Args:
        pool: ExecutorPool for browser lifecycle.
        session_db: Persistent session storage.
        notifier: SSE event broadcaster.
        cache: Optional SelectorCache for cross-session caching.
        idle_timeout_minutes: Minutes of inactivity before session expiry.
    """

    def __init__(
        self,
        pool: ExecutorPool,
        session_db: SessionDB,
        notifier: Notifier,
        cache: SelectorCache | None = None,
        idle_timeout_minutes: int = 30,
    ) -> None:
        self._pool = pool
        self._db = session_db
        self._notifier = notifier
        self._cache = cache
        self._idle_timeout_minutes = idle_timeout_minutes
        self._sessions: dict[str, LiveSession] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    # ── Session Lifecycle ────────────────────────────

    async def create_session(
        self,
        *,
        headless: bool = True,
        initial_url: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new browser session.

        Acquires an executor from the pool, builds the orchestrator stack,
        persists to DB, and publishes an SSE event.

        Args:
            headless: Whether the browser runs headless.
            initial_url: Optional starting URL.
            context: Optional metadata.

        Returns:
            Session dict from the database.
        """
        # 1. Acquire executor
        executor = await self._pool.acquire()

        # 2. Navigate if initial_url provided
        if initial_url:
            await executor.goto(initial_url)

        # 3. Build orchestrator components
        extractor = DOMExtractor()
        verifier = Verifier()
        planner = create_llm_planner()
        handoff_manager = HandoffManager()

        # 3b. Persist to DB first to get session_id for progress callback
        session_record = await self._db.create_session(
            headless=headless,
            initial_url=initial_url,
            context=context,
        )
        session_id = session_record["id"]

        progress_cb = NotifierProgressCallback(self._notifier, session_id)

        orchestrator = LLMFirstOrchestrator(
            executor=executor,
            extractor=extractor,
            planner=planner,
            verifier=verifier,
            cache=self._cache,
            progress_callback=progress_cb,
            fallback_router=FallbackRouter(),
        )

        # 4. Register handoff callback
        def _on_handoff(request: Any) -> None:
            asyncio.ensure_future(
                self._notifier.publish("handoff_requested", {
                    "session_id": session_id,
                    "request_id": request.request_id,
                    "reason": request.reason.value,
                    "message": request.message,
                    "url": request.url,
                })
            )

        handoff_manager.on_handoff(_on_handoff)

        # 6. Store live session
        self._sessions[session_id] = LiveSession(
            session_id=session_id,
            executor=executor,
            orchestrator=orchestrator,
            handoff_manager=handoff_manager,
            headless=headless,
        )

        # 7. SSE event
        await self._notifier.publish("session_created", {
            "session_id": session_id,
            "headless": headless,
            "initial_url": initial_url,
        })

        logger.info("Session created: %s", session_id)
        return session_record

    async def execute_turn(
        self,
        session_id: str,
        intent: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Execute a turn (intent) within an existing session.

        Args:
            session_id: The session to execute in.
            intent: Natural language instruction.
            attachments: Optional list of attachment dicts with
                filename, mime_type, and base64_data keys.

        Returns:
            Turn result dict with success, cost, steps, etc.

        Raises:
            SessionNotFoundError: If session_id is not in live sessions.
        """
        live = self._get_live_session(session_id)

        # SSE: turn started
        await self._notifier.publish("session_turn_started", {
            "session_id": session_id,
            "intent": intent,
            "turn_num": live.turn_count + 1,
        })

        # Create DB turn record
        turn_record = await self._db.create_turn(session_id, intent)

        # Execute via orchestrator (wrapped in Task for cancel support)
        task: asyncio.Task[RunResult] = asyncio.create_task(
            live.orchestrator.run(intent, attachments=attachments),
        )
        live.running_task = task
        try:
            run_result: RunResult = await task
        except asyncio.CancelledError:
            logger.info("Turn cancelled: session=%s", session_id)
            await self._db.complete_turn(
                turn_record["id"],
                success=False,
                error_msg="Cancelled by user",
            )
            await self._notifier.publish("session_turn_completed", {
                "session_id": session_id,
                "turn_id": turn_record["id"],
                "success": False,
                "cancelled": True,
            })
            raise
        finally:
            live.running_task = None

        # Build step details
        step_details = [
            {
                "step_id": sr.step_id,
                "success": sr.success,
                "method": sr.method,
                "tokens_used": sr.tokens_used,
                "latency_ms": sr.latency_ms,
                "cost_usd": sr.cost_usd,
            }
            for sr in run_result.step_results
        ]

        steps_ok = sum(1 for sr in run_result.step_results if sr.success)
        error_msg: str | None = None
        if not run_result.success and run_result.step_results:
            failed = [sr for sr in run_result.step_results if not sr.success]
            if failed:
                error_msg = f"Step {failed[0].step_id} failed"

        # Complete DB turn
        completed_turn = await self._db.complete_turn(
            turn_record["id"],
            success=run_result.success,
            cost_usd=run_result.total_cost_usd,
            tokens_used=run_result.total_tokens,
            steps_total=len(run_result.step_results),
            steps_ok=steps_ok,
            error_msg=error_msg,
            screenshots=run_result.screenshots,
            step_details=step_details,
        )

        # Update live session state
        live.turn_count += 1
        live.total_cost_usd += run_result.total_cost_usd

        # Update DB session totals
        await self._db.update_session(
            session_id,
            total_cost_usd=live.total_cost_usd,
            total_tokens=(
                (await self._db.get_session(session_id) or {}).get("total_tokens", 0)
                + run_result.total_tokens
            ),
        )

        # SSE: turn completed
        await self._notifier.publish("session_turn_completed", {
            "session_id": session_id,
            "turn_id": turn_record["id"],
            "success": run_result.success,
            "cost_usd": run_result.total_cost_usd,
        })

        logger.info(
            "Turn completed: session=%s success=%s cost=$%.4f",
            session_id, run_result.success, run_result.total_cost_usd,
        )
        return completed_turn or turn_record

    async def cancel_turn(self, session_id: str) -> bool:
        """Cancel the currently running turn for a session.

        Args:
            session_id: The session ID.

        Returns:
            True if a running turn was cancelled, False if no active turn.

        Raises:
            SessionNotFoundError: If session_id is not in live sessions.
        """
        live = self._get_live_session(session_id)
        if live.running_task and not live.running_task.done():
            live.running_task.cancel()
            return True
        return False

    async def get_screenshot(self, session_id: str) -> bytes:
        """Take a screenshot of the current page.

        Args:
            session_id: The session ID.

        Returns:
            PNG screenshot bytes.

        Raises:
            SessionNotFoundError: If session_id is not in live sessions.
        """
        live = self._get_live_session(session_id)
        return await live.executor.screenshot()

    async def get_handoffs(self, session_id: str) -> list[dict[str, Any]]:
        """Get pending handoff requests for a session.

        Args:
            session_id: The session ID.

        Returns:
            List of handoff request dicts.

        Raises:
            SessionNotFoundError: If session_id is not in live sessions.
        """
        live = self._get_live_session(session_id)
        pending = live.handoff_manager.get_pending()
        return [
            {
                "request_id": req.request_id,
                "reason": req.reason.value,
                "url": req.url,
                "title": req.title,
                "message": req.message,
                "created_at": req.created_at,
            }
            for req in pending
        ]

    async def resolve_handoff(
        self,
        session_id: str,
        request_id: str,
        action_taken: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve a pending handoff request.

        Args:
            session_id: The session ID.
            request_id: The handoff request ID.
            action_taken: Description of what the human did.
            metadata: Additional response data.

        Returns:
            Dict with resolution details.

        Raises:
            SessionNotFoundError: If session_id is not in live sessions.
        """
        live = self._get_live_session(session_id)
        await live.handoff_manager.resolve(
            request_id, action_taken=action_taken, metadata=metadata,
        )

        await self._notifier.publish("handoff_resolved", {
            "session_id": session_id,
            "request_id": request_id,
            "action_taken": action_taken,
        })

        return {
            "request_id": request_id,
            "resolved": True,
            "action_taken": action_taken,
        }

    async def close_session(self, session_id: str) -> dict[str, Any]:
        """Close a session, releasing browser resources.

        Args:
            session_id: The session ID.

        Returns:
            Closed session dict from DB.

        Raises:
            SessionNotFoundError: If session_id is not in live sessions.
        """
        live = self._get_live_session(session_id)

        # Collect fallback stats before closing
        fallback_stats = live.orchestrator.fallback_stats
        if fallback_stats:
            logger.info(
                "Session %s fallback stats: %s", session_id, fallback_stats,
            )

        # Release executor back to pool
        await self._pool.release(live.executor)

        # Update DB
        closed = await self._db.close_session(session_id)

        # Remove from live sessions
        del self._sessions[session_id]

        # SSE event
        await self._notifier.publish("session_closed", {
            "session_id": session_id,
        })

        logger.info("Session closed: %s", session_id)
        return closed or {"id": session_id, "status": "closed"}

    async def run_oneshot(
        self,
        intent: str,
        initial_url: str | None = None,
        headless: bool = True,
    ) -> dict[str, Any]:
        """Execute a single intent in a temporary session.

        Creates a session, runs one turn, closes, and returns the result.

        Args:
            intent: Natural language instruction.
            initial_url: Optional starting URL.
            headless: Whether the browser runs headless.

        Returns:
            Turn result dict.
        """
        session = await self.create_session(
            headless=headless, initial_url=initial_url,
        )
        try:
            result = await self.execute_turn(session["id"], intent)
        finally:
            await self.close_session(session["id"])
        return result

    # ── Cleanup Loop ─────────────────────────────────

    async def start_cleanup_loop(self) -> None:
        """Start the background cleanup loop for expired sessions."""
        if self._cleanup_task is not None:
            return
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Cleanup loop started (interval=5min, timeout=%dmin)",
                     self._idle_timeout_minutes)

    async def stop_cleanup_loop(self) -> None:
        """Stop the background cleanup loop."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None
            logger.info("Cleanup loop stopped")

    async def _cleanup_loop(self) -> None:
        """Periodically expire idle sessions."""
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes
                expired_ids = await self._db.expire_idle_sessions(
                    self._idle_timeout_minutes,
                )
                for sid in expired_ids:
                    if sid in self._sessions:
                        live = self._sessions.pop(sid)
                        try:
                            await self._pool.release(live.executor)
                        except Exception:
                            logger.warning(
                                "Error releasing expired session %s", sid,
                                exc_info=True,
                            )
                        await self._notifier.publish("session_expired", {
                            "session_id": sid,
                        })
                        logger.info("Expired session: %s", sid)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Cleanup loop error")

    # ── Private Helpers ──────────────────────────────

    def _get_live_session(self, session_id: str) -> LiveSession:
        """Get a live session by ID or raise SessionNotFoundError."""
        live = self._sessions.get(session_id)
        if live is None:
            raise SessionNotFoundError(
                f"Session not found: {session_id}"
            )
        return live
