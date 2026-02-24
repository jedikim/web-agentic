"""One-shot run route — create session, execute, close, return result."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from src.api.dependencies import get_session_manager
from src.api.models import OneShotRequest, OneShotResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["run"])


@router.post("/api/run", response_model=OneShotResponse)
async def oneshot_run(req: OneShotRequest) -> OneShotResponse:
    """Execute a single intent in a temporary session."""
    mgr = get_session_manager()
    try:
        result = await mgr.run_oneshot(
            intent=req.intent,
            initial_url=req.url,
            headless=req.headless,
        )
    except Exception as exc:
        logger.error("One-shot run failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return OneShotResponse(
        success=result["success"],
        steps_total=result["steps_total"],
        steps_ok=result["steps_ok"],
        cost_usd=result["cost_usd"],
        tokens_used=result["tokens_used"],
        error_msg=result.get("error_msg"),
        screenshots=result.get("screenshots", []),
        final_url=None,
    )
