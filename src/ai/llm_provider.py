"""LLM Provider abstraction — supports Gemini and OpenAI dynamically.

Defines the ``ILLMProvider`` protocol and concrete implementations for
Google Gemini and OpenAI. Use ``create_provider()`` factory to instantiate
the appropriate provider by name.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class ILLMProvider(Protocol):
    """Protocol for LLM providers."""

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text from prompt."""
        ...

    async def generate_structured(
        self, prompt: str, schema: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        """Generate structured output matching schema."""
        ...

    @property
    def model_name(self) -> str:
        """Current model name."""
        ...

    @property
    def provider_name(self) -> str:
        """Provider identifier (e.g., 'gemini', 'openai')."""
        ...


class GeminiProvider:
    """Gemini LLM provider using google-genai SDK."""

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        api_key: str | None = None,
    ) -> None:
        from google import genai

        self._model = model
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._client = genai.Client(api_key=self._api_key)

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text from prompt via Gemini API."""
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=kwargs.get("config"),
        )
        return response.text or ""

    async def generate_structured(
        self, prompt: str, schema: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        """Generate structured output via Gemini API."""
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=kwargs.get("config"),
        )
        text = response.text or "{}"
        result: dict[str, Any] = json.loads(text)
        return result

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "gemini"


class OpenAIProvider:
    """OpenAI LLM provider (optional dependency)."""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
    ) -> None:
        try:
            import openai
        except ImportError as err:
            raise ImportError(
                "openai package required. Install with: pip install web-agentic[openai]"
            ) from err
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._client = openai.AsyncOpenAI(api_key=self._api_key)

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text from prompt via OpenAI API."""
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", 0.1),
            max_tokens=kwargs.get("max_tokens", 2048),
        )
        return response.choices[0].message.content or ""

    async def generate_structured(
        self, prompt: str, schema: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        """Generate structured JSON output via OpenAI API."""
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=kwargs.get("temperature", 0.1),
            max_tokens=kwargs.get("max_tokens", 2048),
        )
        text = response.choices[0].message.content or "{}"
        result: dict[str, Any] = json.loads(text)
        return result

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "openai"


def create_provider(
    provider: str = "gemini",
    model: str | None = None,
    api_key: str | None = None,
) -> ILLMProvider:
    """Factory: create LLM provider by name.

    Args:
        provider: Provider name ('gemini' or 'openai').
        model: Optional model override.
        api_key: Optional API key override.

    Returns:
        ILLMProvider instance.

    Raises:
        ValueError: If the provider name is not recognized.
    """
    if provider == "gemini":
        return GeminiProvider(model=model or "gemini-2.0-flash", api_key=api_key)
    elif provider == "openai":
        return OpenAIProvider(model=model or "gpt-4o", api_key=api_key)
    else:
        raise ValueError(f"Unknown provider: {provider}. Supported: gemini, openai")
