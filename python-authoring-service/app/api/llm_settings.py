"""API endpoints for LLM configuration."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.llm_config import AVAILABLE_MODELS, configure_llm, get_config

router = APIRouter()


class LlmSettingsRequest(BaseModel):
    """Request body for updating LLM settings."""
    model: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None

    model_config = {"populate_by_name": True}


@router.get("")
async def get_llm_settings():
    """Return current LLM configuration (with masked keys)."""
    config = get_config()
    return config.to_safe_dict()


@router.post("")
async def set_llm_settings(req: LlmSettingsRequest):
    """Update LLM settings and configure DSPy."""
    try:
        config = configure_llm(
            model=req.model,
            openai_api_key=req.openai_api_key,
            gemini_api_key=req.gemini_api_key,
        )
        return config.to_safe_dict()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/models")
async def get_available_models():
    """Return available models grouped by provider."""
    config = get_config()
    result = {}
    for provider, models in AVAILABLE_MODELS.items():
        available = provider == "openai" and bool(config.openai_api_key) or \
                    provider == "gemini" and bool(config.gemini_api_key)
        result[provider] = {
            "models": models,
            "available": available,
        }
    return result
