"""Session Manager — manages live browser sessions and orchestration.

Bridges the API layer with the core automation engine. Each session holds
a live Executor + orchestrator pair. Supports both legacy (LLMFirstOrchestrator)
and v3 pipeline via EngineConfig.v3_pipeline.enabled.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any

from src.ai.candidate_filter import create_candidate_filter
from src.ai.llm_planner import create_llm_planner
from src.api.progress_adapter import NotifierProgressCallback
from src.api.session_db import SessionDB
from src.core.browser import Browser as V3Browser
from src.core.config import EngineConfig
from src.core.executor import Executor, create_executor
from src.core.executor_pool import ExecutorPool
from src.core.extractor import DOMExtractor
from src.core.fallback_router import FallbackRouter
from src.core.handoff import HandoffManager
from src.core.llm_orchestrator import LLMFirstOrchestrator
from src.core.selector_cache import SelectorCache
from src.core.v3_factory import V3Pipeline, create_v3_pipeline
from src.core.v3_orchestrator import V3RunResult
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
        v3_pipeline: V3 pipeline components (None if using legacy).
        use_v3: Whether this session uses the v3 pipeline.
    """

    session_id: str
    executor: Executor
    orchestrator: LLMFirstOrchestrator
    handoff_manager: HandoffManager
    headless: bool = True
    turn_count: int = 0
    total_cost_usd: float = 0.0
    running_task: asyncio.Task[Any] | None = None
    v3_pipeline: V3Pipeline | None = None
    use_v3: bool = False


# ── Session Manager ──────────────────────────────────


class SessionManager:
    """Manages live browser sessions with automation orchestration.

    Args:
        pool: ExecutorPool for browser lifecycle.
        session_db: Persistent session storage.
        notifier: SSE event broadcaster.
        cache: Optional SelectorCache for cross-session caching.
        config: Optional EngineConfig for candidate filter pipeline.
        idle_timeout_minutes: Minutes of inactivity before session expiry.
    """

    def __init__(
        self,
        pool: ExecutorPool,
        session_db: SessionDB,
        notifier: Notifier,
        cache: SelectorCache | None = None,
        config: EngineConfig | None = None,
        idle_timeout_minutes: int = 30,
    ) -> None:
        self._pool = pool
        self._db = session_db
        self._notifier = notifier
        self._cache = cache
        self._config = config
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
        # 1. Acquire executor (headful bypasses pool — needs its own browser)
        if headless:
            executor = await self._pool.acquire()
        else:
            executor = await create_executor(headless=False)

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

        # Build candidate filter pipeline from config
        candidate_filter = None
        if self._config is not None:
            candidate_filter = create_candidate_filter(
                self._config.candidate_filter,
            )

        orchestrator = LLMFirstOrchestrator(
            executor=executor,
            extractor=extractor,
            planner=planner,
            verifier=verifier,
            cache=self._cache,
            progress_callback=progress_cb,
            fallback_router=FallbackRouter(),
            candidate_filter=candidate_filter,
        )

        # 3c. Build v3 pipeline if enabled
        use_v3 = (
            self._config is not None
            and self._config.v3_pipeline.enabled
        )
        v3_pipeline: V3Pipeline | None = None
        if use_v3:
            try:
                v3_pipeline = create_v3_pipeline(config=self._config)
                logger.info(
                    "V3 pipeline created for session %s", session_id,
                )
            except Exception:
                logger.warning(
                    "V3 pipeline creation failed, falling back to legacy",
                    exc_info=True,
                )
                use_v3 = False

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
            v3_pipeline=v3_pipeline,
            use_v3=use_v3,
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
        if live.use_v3 and live.v3_pipeline:
            coro: Any = self._run_v3(live, intent, attachments)
        else:
            coro = live.orchestrator.run(intent, attachments=attachments)

        run_task: asyncio.Task[Any] = asyncio.create_task(coro)
        live.running_task = run_task
        try:
            raw_result = await run_task
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

        # Normalize result to common shape
        run_result = self._normalize_result(raw_result)

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
        result_summary = getattr(run_result, "result_summary", None) or ""
        completed_turn = await self._db.complete_turn(
            turn_record["id"],
            success=run_result.success,
            cost_usd=run_result.total_cost_usd,
            tokens_used=run_result.total_tokens,
            steps_total=len(run_result.step_results),
            steps_ok=steps_ok,
            error_msg=error_msg,
            result_summary=result_summary,
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
            "result_summary": getattr(run_result, "result_summary", "") or "",
        })

        logger.info(
            "Turn completed: session=%s success=%s cost=$%.4f",
            session_id, run_result.success, run_result.total_cost_usd,
        )
        turn_data = completed_turn or turn_record
        turn_data["result_summary"] = getattr(run_result, "result_summary", None) or ""
        return turn_data

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

        # Collect fallback stats before closing (legacy only)
        fallback_stats = getattr(live.orchestrator, "fallback_stats", None)
        if fallback_stats:
            logger.info(
                "Session %s fallback stats: %s", session_id, fallback_stats,
            )

        # Release executor: pool sessions go back to pool, headful ones close directly
        if live.headless:
            await self._pool.release(live.executor)
        else:
            await live.executor.close()

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
                            if live.headless:
                                await self._pool.release(live.executor)
                            else:
                                await live.executor.close()
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

    # ── V3 Pipeline Execution ────────────────────────

    async def _run_v3(
        self,
        live: LiveSession,
        intent: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> V3RunResult:
        """Execute intent via v3 pipeline.

        Wraps the v3 orchestrator's run_with_result with Browser adapter.
        """
        pipeline = live.v3_pipeline
        assert pipeline is not None

        # Wrap executor's page in v3 Browser
        v3_browser = V3Browser(live.executor._page)

        return await pipeline.orchestrator.run_with_result(
            intent, v3_browser, attachments=attachments,
        )

    @staticmethod
    def _normalize_result(raw_result: Any) -> Any:
        """Normalize V3RunResult to look like RunResult for downstream code.

        Both RunResult and V3RunResult share the same field names:
        success, step_results, screenshots, total_tokens, total_cost_usd.
        """
        # V3RunResult and RunResult have compatible fields
        return raw_result

    # ── Private Helpers ──────────────────────────────

    def _get_live_session(self, session_id: str) -> LiveSession:
        """Get a live session by ID or raise SessionNotFoundError."""
        live = self._sessions.get(session_id)
        if live is None:
            raise SessionNotFoundError(
                f"Session not found: {session_id}"
            )
        return live
