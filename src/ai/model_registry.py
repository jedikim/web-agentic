"""Model registry — maps model names to providers and tiers.

Provides a lookup table of known models and a ``resolve_model()``
helper that returns (provider_name, model_name) for any specification.
"""
from __future__ import annotations

SUPPORTED_MODELS: dict[str, dict[str, str]] = {
    "gemini-2.0-flash": {"provider": "gemini", "tier": "flash"},
    "gemini-2.5-pro-preview-05-06": {"provider": "gemini", "tier": "pro"},
    "gemini-3-flash-preview": {"provider": "gemini", "tier": "flash"},
    "gemini-3.1-pro-preview": {"provider": "gemini", "tier": "pro"},
    "gpt-4o": {"provider": "openai", "tier": "pro"},
    "gpt-4o-mini": {"provider": "openai", "tier": "flash"},
}

# Default models per provider+tier
_DEFAULTS: dict[str, dict[str, str]] = {
    "gemini": {"flash": "gemini-2.0-flash", "pro": "gemini-2.5-pro-preview-05-06"},
    "openai": {"flash": "gpt-4o-mini", "pro": "gpt-4o"},
}


def resolve_model(
    model: str | None = None,
    tier: str = "flash",
    provider: str = "gemini",
) -> tuple[str, str]:
    """Resolve model specification to (provider, model_name).

    Args:
        model: Explicit model name (if provided, used directly).
        tier: Model tier ('flash' or 'pro').
        provider: Provider name ('gemini' or 'openai').

    Returns:
        Tuple of (provider_name, model_name).

    Raises:
        ValueError: If no model can be resolved for the given provider/tier.
    """
    if model and model in SUPPORTED_MODELS:
        info = SUPPORTED_MODELS[model]
        return (info["provider"], model)

    if model:
        # Unknown model, assume given provider
        return (provider, model)

    # Resolve from defaults
    if provider in _DEFAULTS and tier in _DEFAULTS[provider]:
        return (provider, _DEFAULTS[provider][tier])

    raise ValueError(f"Cannot resolve model for provider={provider}, tier={tier}")
