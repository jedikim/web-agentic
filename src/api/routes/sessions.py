"""Session API routes — create, list, execute turns, screenshots, handoffs."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from src.api.chat_automation import ChatAutomationService
from src.api.dependencies import get_session_manager
from src.api.models import (
    CaptchaSubmitRequest,
    ChatStartRequest,
    ChatStartResponse,
    ChatStatusResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    ExecuteTurnRequest,
    ExecuteTurnResponse,
    HandoffItem,
    ResolveHandoffRequest,
    SessionDetail,
    SessionListItem,
    StatusResponse,
)
from src.api.session_manager import SessionNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("/", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    """Create a new browser session."""
    mgr = get_session_manager()
    try:
        session = await mgr.create_session(
            headless=req.headless,
            initial_url=req.url,
            context=req.context,
        )
    except Exception as exc:
        logger.error("Failed to create session: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return CreateSessionResponse(
        session_id=session["id"],
        status=session["status"],
        headless=session["headless"],
        created_at=session["created_at"],
    )


@router.get("/", response_model=list[SessionListItem])
async def list_sessions(
    status: str | None = None, limit: int = 50,
) -> list[dict[str, Any]]:
    """List sessions, optionally filtered by status."""
    mgr = get_session_manager()
    return await mgr._db.list_sessions(status=status, limit=limit)


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session_detail(session_id: str) -> dict[str, Any]:
    """Get session detail with turns."""
    mgr = get_session_manager()
    session = await mgr._db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    turns = await mgr._db.get_session_turns(session_id)
    session["turns"] = turns
    return session


@router.post("/{session_id}/turn", response_model=ExecuteTurnResponse)
async def execute_turn(
    session_id: str, req: ExecuteTurnRequest,
) -> ExecuteTurnResponse:
    """Execute a turn within a session."""
    mgr = get_session_manager()
    try:
        result = await mgr.execute_turn(
            session_id,
            req.intent,
            attachments=[a.model_dump() for a in req.attachments] if req.attachments else None,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except Exception as exc:
        logger.error("Turn execution failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Get current session state for URL and handoff count
    session = await mgr._db.get_session(session_id)
    current_url = session["current_url"] if session else None
    try:
        handoffs = await mgr.get_handoffs(session_id)
        pending_handoffs = len(handoffs)
    except SessionNotFoundError:
        pending_handoffs = 0

    return ExecuteTurnResponse(
        turn_id=result["id"],
        turn_num=result["turn_num"],
        session_id=session_id,
        success=result["success"],
        steps_total=result["steps_total"],
        steps_ok=result["steps_ok"],
        cost_usd=result["cost_usd"],
        tokens_used=result["tokens_used"],
        error_msg=result.get("error_msg"),
        screenshots=result.get("screenshots", []),
        current_url=current_url,
        pending_handoffs=pending_handoffs,
    )


@router.post("/{session_id}/cancel", response_model=StatusResponse)
async def cancel_turn(session_id: str) -> StatusResponse:
    """Cancel the currently running turn for a session."""
    mgr = get_session_manager()
    try:
        cancelled = await mgr.cancel_turn(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    return StatusResponse(
        status="cancelled" if cancelled else "no_active_turn",
        message="Turn cancelled" if cancelled else "No active turn to cancel",
    )


@router.get("/{session_id}/screenshot")
async def get_screenshot(session_id: str) -> Response:
    """Take a screenshot of the current page."""
    mgr = get_session_manager()
    try:
        png_bytes = await mgr.get_screenshot(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except Exception as exc:
        logger.error("Screenshot failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(content=png_bytes, media_type="image/png")


@router.get("/{session_id}/handoffs", response_model=list[HandoffItem])
async def get_handoffs(session_id: str) -> list[HandoffItem]:
    """List pending handoff requests for a session."""
    mgr = get_session_manager()
    try:
        handoffs = await mgr.get_handoffs(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    return [
        HandoffItem(
            request_id=h["request_id"],
            reason=h["reason"],
            url=h["url"],
            title=h["title"],
            message=h.get("message", ""),
            has_screenshot=False,
            created_at=h["created_at"],
        )
        for h in handoffs
    ]


@router.post(
    "/{session_id}/handoffs/{request_id}/resolve",
    response_model=StatusResponse,
)
async def resolve_handoff(
    session_id: str, request_id: str, req: ResolveHandoffRequest,
) -> StatusResponse:
    """Resolve a pending handoff request."""
    mgr = get_session_manager()
    try:
        result = await mgr.resolve_handoff(
            session_id, request_id,
            action_taken=req.action_taken,
            metadata=req.metadata,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except Exception as exc:
        logger.error("Resolve handoff failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return StatusResponse(
        status="resolved",
        message=f"Handoff {request_id} resolved",
        data=result,
    )


@router.delete("/{session_id}", response_model=StatusResponse)
async def close_session(session_id: str) -> StatusResponse:
    """Close a session and release browser resources."""
    mgr = get_session_manager()
    try:
        result = await mgr.close_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except Exception as exc:
        logger.error("Close session failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return StatusResponse(
        status="closed",
        message=f"Session {session_id} closed",
        data={"session_id": result["id"], "status": result["status"]},
    )


# ── Chat Automation ─────────────────────────────────

_chat_service: ChatAutomationService | None = None


def get_chat_service() -> ChatAutomationService:
    """Get or create the chat automation service singleton."""
    global _chat_service  # noqa: PLW0603
    if _chat_service is None:
        _chat_service = ChatAutomationService(session_manager=get_session_manager())
    return _chat_service


@router.post("/{session_id}/chat/start", response_model=ChatStartResponse)
async def start_chat_run(session_id: str, req: ChatStartRequest) -> ChatStartResponse:
    """Start a chat automation run for a session."""
    svc = get_chat_service()
    try:
        run_id = await svc.start_run(session_id, req.instruction, req.headless)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ChatStartResponse(run_id=run_id, status="running")


@router.post("/{session_id}/chat/{run_id}/pause", response_model=StatusResponse)
async def pause_chat_run(session_id: str, run_id: str) -> StatusResponse:
    """Pause a running chat automation."""
    svc = get_chat_service()
    try:
        await svc.pause(run_id)
    except (KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusResponse(status="paused", message=f"Run {run_id} paused")


@router.post("/{session_id}/chat/{run_id}/resume", response_model=StatusResponse)
async def resume_chat_run(session_id: str, run_id: str) -> StatusResponse:
    """Resume a paused chat automation."""
    svc = get_chat_service()
    try:
        await svc.resume(run_id)
    except (KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusResponse(status="running", message=f"Run {run_id} resumed")


@router.post("/{session_id}/chat/{run_id}/cancel", response_model=StatusResponse)
async def cancel_chat_run(session_id: str, run_id: str) -> StatusResponse:
    """Cancel a running or paused chat automation."""
    svc = get_chat_service()
    try:
        await svc.cancel(run_id)
    except (KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusResponse(status="canceled", message=f"Run {run_id} canceled")


@router.post("/{session_id}/chat/{run_id}/captcha", response_model=StatusResponse)
async def submit_captcha_solution(
    session_id: str, run_id: str, req: CaptchaSubmitRequest,
) -> StatusResponse:
    """Submit a CAPTCHA solution for a chat automation run."""
    svc = get_chat_service()
    try:
        await svc.submit_captcha(run_id, req.solution)
    except (KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusResponse(status="submitted", message="CAPTCHA solution submitted")


@router.post("/{session_id}/chat/{run_id}/image", response_model=StatusResponse)
async def attach_image_to_run(session_id: str, run_id: str) -> StatusResponse:
    """Attach an image to a chat automation run (placeholder for multipart upload)."""
    _ = get_chat_service()
    return StatusResponse(status="ok", message="Use multipart upload for images")


@router.get("/{session_id}/chat/{run_id}/status", response_model=ChatStatusResponse)
async def get_chat_status(session_id: str, run_id: str) -> ChatStatusResponse:
    """Get current status of a chat automation run."""
    svc = get_chat_service()
    try:
        status = await svc.get_status(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ChatStatusResponse(**status)
