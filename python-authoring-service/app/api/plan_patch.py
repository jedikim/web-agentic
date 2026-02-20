import logging
import time

from fastapi import APIRouter, HTTPException

from app.schemas.patch_schema import PlanPatchRequest, PlanPatchResponse
from app.dspy_programs.patch_planner import plan_patch_for_failure

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=PlanPatchResponse)
async def plan_patch(request: PlanPatchRequest):
    start = time.monotonic()
    try:
        result = await plan_patch_for_failure(request)
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "plan_patch requestId=%s error_type=%s step=%s patches=%d elapsed_ms=%.1f",
            request.request_id,
            request.error_type,
            request.step_id,
            len(result.patch),
            elapsed_ms,
        )
        return result
    except Exception as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.error(
            "plan_patch failed requestId=%s error_type=%s step=%s elapsed_ms=%.1f error=%s",
            request.request_id,
            request.error_type,
            request.step_id,
            elapsed_ms,
            str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))
