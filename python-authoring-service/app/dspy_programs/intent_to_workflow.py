from app.schemas.recipe_schema import (
    CompileIntentRequest,
    CompileIntentResponse,
    Workflow,
    WorkflowStep,
)


async def compile_intent_to_recipe(request: CompileIntentRequest) -> CompileIntentResponse:
    """
    Phase 1 stub: Returns a minimal workflow from the intent.
    Phase 3 will replace with DSPy program + GEPA optimization.
    """
    steps = [
        WorkflowStep(
            id="open",
            op="goto",
            args={"url": f"https://{request.domain or 'example.com'}"},
        ),
        WorkflowStep(
            id="checkpoint_start",
            op="checkpoint",
            args={"message": f"Goal: {request.goal}. Proceed?"},
        ),
    ]
    workflow = Workflow(id=f"{request.domain or 'default'}_flow", steps=steps)

    return CompileIntentResponse(
        requestId=request.request_id,
        workflow=workflow,
        actions={},
        selectors={},
        policies={},
        fingerprints={},
    )
