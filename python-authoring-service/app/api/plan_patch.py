from fastapi import APIRouter, HTTPException
from app.schemas.patch_schema import PlanPatchRequest, PlanPatchResponse
from app.dspy_programs.patch_planner import plan_patch_for_failure

router = APIRouter()


@router.post("", response_model=PlanPatchResponse)
async def plan_patch(request: PlanPatchRequest):
    try:
        result = await plan_patch_for_failure(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
