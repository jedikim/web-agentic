"""LiteLLM Router wrapper — vendor auto-detection from API keys.

Detects GEMINI_API_KEY or OPENAI_API_KEY and maps all model aliases
(fast, strong, codegen, vision) to the appropriate vendor models.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

# ── Vendor model mapping ──

VENDOR_MODELS: dict[str, dict[str, str]] = {
    "gemini": {
        "fast": "gemini/gemini-3-flash-preview",
        "strong": "gemini/gemini-3.1-pro-preview",
        "codegen": "gemini/gemini-3.1-pro-preview",
        "vision": "gemini/gemini-3-flash-preview",
    },
    "openai": {
        "fast": "openai/gpt-5-mini",
        "strong": "openai/gpt-5.3-codex",
        "codegen": "openai/gpt-5.3-codex",
        "vision": "openai/gpt-5-mini",
    },
}

# Models with known sunset dates
MODEL_SUNSET: dict[str, str] = {
    "gemini/gemini-2.0-flash": "2026-06-01",
    "gemini/gemini-2.0-pro": "2026-06-01",
}

FALLBACK_CHAINS: list[dict[str, list[str]]] = [
    {"fast": ["strong", "codegen"]},
    {"codegen": ["strong"]},
    {"vision": ["fast"]},
]


def detect_vendor() -> str:
    """Auto-detect LLM vendor from environment API keys."""
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    raise RuntimeError("GEMINI_API_KEY or OPENAI_API_KEY required")


def assert_model_lifecycle(model_name: str) -> None:
    """Raise if a model has passed its sunset date."""
    sunset = MODEL_SUNSET.get(model_name)
    if sunset and date.today().isoformat() >= sunset:
        raise RuntimeError(f"Model sunset reached: {model_name} ({sunset})")


def build_model_registry(
    vendor: str | None = None,
) -> dict[str, str]:
    """Build model alias → full model name mapping.

    Environment variables MODEL_FAST, MODEL_STRONG etc. can override defaults.
    """
    if vendor is None:
        vendor = detect_vendor()
    defaults = VENDOR_MODELS.get(vendor, VENDOR_MODELS["gemini"])
    registry: dict[str, str] = {}
    for alias, default_model in defaults.items():
        env_key = f"MODEL_{alias.upper()}"
        registry[alias] = os.getenv(env_key, default_model)
    # Lifecycle check
    for model in registry.values():
        assert_model_lifecycle(model)
    return registry


def get_api_key() -> str:
    """Get the appropriate API key for the detected vendor."""
    for env_var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
        key = os.getenv(env_var)
        if key:
            return key
    raise RuntimeError("No API key found")


class LLMRouter:
    """Wrapper around LiteLLM Router with vendor auto-detection.

    Usage::

        router = LLMRouter()
        response = await router.complete("fast", messages=[...])
    """

    def __init__(
        self,
        vendor: str | None = None,
        registry: dict[str, str] | None = None,
    ) -> None:
        self._vendor = vendor or detect_vendor()
        self._registry = registry or build_model_registry(self._vendor)
        self._api_key = get_api_key()
        self._router: Any = None
        logger.info(
            "LLMRouter initialized (vendor=%s, models=%s)",
            self._vendor,
            list(self._registry.keys()),
        )

    @property
    def registry(self) -> dict[str, str]:
        """Current model alias → model name mapping."""
        return dict(self._registry)

    def _ensure_router(self) -> Any:
        """Lazy-init LiteLLM Router."""
        if self._router is not None:
            return self._router
        try:
            from litellm import Router

            model_list = [
                {
                    "model_name": alias,
                    "litellm_params": {
                        "model": model,
                        "api_key": self._api_key,
                    },
                }
                for alias, model in self._registry.items()
            ]
            self._router = Router(
                model_list=model_list,
                fallbacks=FALLBACK_CHAINS,
                set_verbose=False,
            )
        except ImportError:
            logger.warning("litellm not installed; using direct calls")
            self._router = None
        return self._router

    async def complete(
        self,
        alias: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 4000,
        temperature: float = 0.1,
        **kwargs: Any,
    ) -> str:
        """Send a completion request through the router.

        Args:
            alias: Model alias ("fast", "strong", "codegen", "vision").
            messages: Chat messages.
            max_tokens: Maximum response tokens.
            temperature: Sampling temperature.
            **kwargs: Extra parameters passed to LiteLLM.

        Returns:
            Response text content.
        """
        router = self._ensure_router()
        if router is not None:
            resp = await router.acompletion(
                model=alias,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
            return str(resp.choices[0].message.content)

        # Fallback: direct litellm.acompletion
        import litellm

        model = self._registry.get(alias, self._registry["fast"])
        resp = await litellm.acompletion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=self._api_key,
            **kwargs,
        )
        return str(resp.choices[0].message.content)

    def resolve_model(self, alias: str) -> str:
        """Resolve alias to full model name."""
        return self._registry.get(alias, self._registry["fast"])
