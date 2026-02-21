"""
LLM configuration module.

Manages DSPy language model configuration using LiteLLM-compatible model strings.
Supports OpenAI and Gemini providers with OpenAI-first priority.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import dspy

logger = logging.getLogger(__name__)

AVAILABLE_MODELS = {
    "openai": [
        {"id": "openai/gpt-4o", "name": "GPT-4o", "description": "Flagship multimodal model"},
        {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "description": "Fast and affordable"},
        {"id": "openai/o3-mini", "name": "o3-mini", "description": "Reasoning model"},
    ],
    "gemini": [
        {"id": "gemini/gemini-2.5-flash", "name": "Gemini 2.5 Flash", "description": "Fastest Gemini"},
        {"id": "gemini/gemini-2.0-flash", "name": "Gemini 2.0 Flash", "description": "Stable and fast"},
        {"id": "gemini/gemini-2.5-pro", "name": "Gemini 2.5 Pro", "description": "Best quality"},
    ],
}


def _mask_key(key: str) -> str:
    """Mask API key for display, showing only last 4 chars."""
    if not key or len(key) < 8:
        return "****"
    return f"{key[:3]}...{key[-4:]}"


@dataclass
class LlmConfig:
    """In-memory LLM configuration state."""
    model: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    is_configured: bool = False
    provider: str | None = None

    def to_safe_dict(self) -> dict:
        """Return config dict with masked API keys."""
        return {
            "model": self.model,
            "provider": self.provider,
            "isConfigured": self.is_configured,
            "openaiKeySet": bool(self.openai_api_key),
            "geminiKeySet": bool(self.gemini_api_key),
            "openaiKeyMasked": _mask_key(self.openai_api_key) if self.openai_api_key else None,
            "geminiKeyMasked": _mask_key(self.gemini_api_key) if self.gemini_api_key else None,
        }


# Module-level singleton
_config = LlmConfig()


def get_config() -> LlmConfig:
    """Return current LLM configuration."""
    return _config


def configure_llm(
    model: str | None = None,
    openai_api_key: str | None = None,
    gemini_api_key: str | None = None,
) -> LlmConfig:
    """
    Configure the DSPy language model using LiteLLM-compatible model strings.

    Priority: If both keys provided, uses the model's provider.
    If model not specified, auto-selects: OpenAI first, Gemini fallback.
    """
    global _config

    # Update stored keys (keep existing if not provided)
    if openai_api_key is not None:
        _config.openai_api_key = openai_api_key if openai_api_key else None
    if gemini_api_key is not None:
        _config.gemini_api_key = gemini_api_key if gemini_api_key else None

    # Auto-select model if not specified
    if model:
        selected_model = model
    elif _config.openai_api_key:
        selected_model = "openai/gpt-4o"
    elif _config.gemini_api_key:
        selected_model = "gemini/gemini-2.5-flash"
    else:
        # No keys, unconfigure
        _config.model = None
        _config.provider = None
        _config.is_configured = False
        logger.info("LLM unconfigured: no API keys provided")
        return _config

    # Determine provider and API key
    provider = selected_model.split("/")[0]
    if provider == "openai":
        api_key = _config.openai_api_key
    elif provider == "gemini":
        api_key = _config.gemini_api_key
    else:
        api_key = _config.openai_api_key or _config.gemini_api_key

    if not api_key:
        logger.warning("No API key for provider %s", provider)
        _config.model = None
        _config.provider = None
        _config.is_configured = False
        return _config

    # Configure DSPy with LiteLLM
    try:
        lm = dspy.LM(selected_model, api_key=api_key)
        dspy.configure(lm=lm)
        _config.model = selected_model
        _config.provider = provider
        _config.is_configured = True
        logger.info("LLM configured: model=%s provider=%s", selected_model, provider)
    except Exception as exc:
        logger.error("Failed to configure LLM: %s", exc)
        _config.model = None
        _config.provider = None
        _config.is_configured = False
        raise

    return _config
