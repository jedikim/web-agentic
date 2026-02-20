from fastapi import APIRouter, HTTPException
from app.schemas.recipe_schema import CompileIntentRequest, CompileIntentResponse
from app.dspy_programs.intent_to_workflow import compile_intent_to_recipe

router = APIRouter()


@router.post("", response_model=CompileIntentResponse)
async def compile_intent(request: CompileIntentRequest):
    try:
        result = await compile_intent_to_recipe(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
