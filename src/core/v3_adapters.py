"""V3 LLM/VLM Adapters — bridge existing providers to v3 Protocol interfaces.

The v3 pipeline modules define lightweight Protocols:
- IPlannerVLM:     async generate_with_image(prompt, image) -> str
- IActorLLM:       async generate(prompt) -> str
- IRetryVLM:       async generate_with_image(prompt, image) -> str
- ISynthesizerLLM: async generate(prompt) -> str
- ICanvasVLM:      async generate_with_image(prompt, image) -> str
- IBatchVLM:       async generate_with_image(prompt, image) -> str

These adapters wrap existing GeminiProvider / VLMClient to satisfy them.
"""

from __future__ import annotations

import asyncio
import logging
import os
from functools import partial
from typing import Any

logger = logging.getLogger(__name__)


class GeminiTextAdapter:
    """Adapts Gemini SDK to v3 text-only protocols (IActorLLM, ISynthesizerLLM).

    Satisfies: async generate(prompt: str) -> str
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._model = model or os.environ.get(
            "GEMINI_FLASH_MODEL", "gemini-3-flash-preview",
        )
        self._api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY", "")
        )
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def generate(self, prompt: str) -> str:
        """Generate text from prompt."""
        client = self._get_client()
        response = await client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
        )
        return response.text or ""


class GeminiVisionAdapter:
    """Adapts Gemini SDK to v3 vision protocols (IPlannerVLM, IRetryVLM, etc.).

    Satisfies: async generate_with_image(prompt: str, image: bytes) -> str

    When ``json_mode=True``, sets ``response_mime_type="application/json"``
    so Gemini returns well-formed JSON without markdown fencing.
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        json_mode: bool = False,
    ) -> None:
        self._model = model or os.environ.get(
            "GEMINI_FLASH_MODEL", "gemini-3-flash-preview",
        )
        self._api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY", "")
        )
        self._json_mode = json_mode
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def generate_with_image(
        self, prompt: str, image: bytes,
    ) -> str:
        """Generate text from prompt + image."""
        from google.genai import types as _types

        client = self._get_client()
        config: _types.GenerateContentConfig | None = None
        if self._json_mode:
            config = _types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        response = await client.aio.models.generate_content(
            model=self._model,
            contents=[
                prompt,
                _types.Part.from_bytes(
                    data=image, mime_type="image/png",
                ),
            ],
            config=config,
        )
        return response.text or ""

    async def analyze_grid(
        self,
        grid_image: bytes,
        intent: str,
        cell_count: int,
    ) -> list[dict[str, Any]]:
        """VLM grid analysis — classify items against intent.

        Satisfies IVLMGrid protocol for VisualJudge.
        """
        import json

        last_idx = cell_count - 1
        prompt = (
            "You are analyzing a grid image containing multiple items.\n"
            f"The grid has {cell_count} items labelled [0] to [{last_idx}].\n\n"
            f"User intent: {intent}\n\n"
            "For EACH item, evaluate whether it matches the intent.\n"
            "Respond with a JSON array of objects, one per item:\n"
            '[{"index": 0, "label": "item type/name", "confidence": 0.0-1.0, '
            '"relevant": true/false, "description": "brief description", '
            '"reason": "why relevant or not"}]\n\n'
            f"Return ALL items in order [0] to [{last_idx}]."
        )

        raw = await self.generate_with_image(prompt, grid_image)

        # Parse JSON from response (may have markdown fencing)
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            results = json.loads(text)
            if isinstance(results, list):
                return results  # type: ignore[return-value]
        except json.JSONDecodeError:
            pass

        # Fallback: return empty for all cells
        return [
            {"index": i, "label": "", "confidence": 0.0,
             "relevant": False, "description": "", "reason": "parse_error"}
            for i in range(cell_count)
        ]


class LLMProviderTextAdapter:
    """Wraps existing ILLMProvider to satisfy v3 text protocols.

    Use when you already have a GeminiProvider/OpenAIProvider instance.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    async def generate(self, prompt: str) -> str:
        """Delegate to existing provider."""
        result: str = await self._provider.generate(prompt)
        return result


class VLMClientVisionAdapter:
    """Wraps existing VLMClient to satisfy v3 vision protocols.

    The existing VLMClient uses synchronous _call_gemini_vision,
    so we run it in a thread executor to avoid blocking.
    """

    def __init__(self, vlm_client: Any) -> None:
        self._vlm = vlm_client

    async def generate_with_image(
        self, prompt: str, image: bytes,
    ) -> str:
        """Call VLMClient in thread executor."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                self._vlm._call_gemini_vision,
                self._vlm._tier1_model,
                image,
                prompt,
            ),
        )
        text: str = result.get("text", "")
        return text
