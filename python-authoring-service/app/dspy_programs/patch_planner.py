from app.schemas.patch_schema import PlanPatchRequest, PlanPatchResponse


async def plan_patch_for_failure(request: PlanPatchRequest) -> PlanPatchResponse:
    """
    Phase 1 stub: Returns empty patch with human review suggestion.
    Phase 2 will implement real patch generation.
    """
    return PlanPatchResponse(
        requestId=request.request_id,
        patch=[],
        reason=f"Stub: manual review needed for {request.error_type} at step {request.step_id}",
    )
