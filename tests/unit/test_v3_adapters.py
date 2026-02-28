"""Tests for v3 LLM/VLM adapters."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from src.core.v3_adapters import (
    LLMProviderTextAdapter,
    VLMClientVisionAdapter,
)


class TestLLMProviderTextAdapter:
    async def test_delegates_to_provider(self) -> None:
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value="hello world")
        adapter = LLMProviderTextAdapter(provider)

        result = await adapter.generate("test prompt")

        assert result == "hello world"
        provider.generate.assert_called_once_with("test prompt")

    async def test_satisfies_text_protocol(self) -> None:
        """Adapter has generate(prompt: str) -> str."""
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value="ok")
        adapter = LLMProviderTextAdapter(provider)

        assert hasattr(adapter, "generate")
        result = await adapter.generate("p")
        assert isinstance(result, str)


class TestVLMClientVisionAdapter:
    async def test_delegates_to_vlm_client(self) -> None:
        vlm = MagicMock()
        vlm._tier1_model = "test-model"
        vlm._call_gemini_vision = MagicMock(
            return_value={"text": "detected button"},
        )
        adapter = VLMClientVisionAdapter(vlm)

        result = await adapter.generate_with_image("find button", b"img")

        assert result == "detected button"
        vlm._call_gemini_vision.assert_called_once_with(
            "test-model", b"img", "find button",
        )

    async def test_empty_text_fallback(self) -> None:
        vlm = MagicMock()
        vlm._tier1_model = "m"
        vlm._call_gemini_vision = MagicMock(return_value={})
        adapter = VLMClientVisionAdapter(vlm)

        result = await adapter.generate_with_image("p", b"img")
        assert result == ""

    async def test_satisfies_vision_protocol(self) -> None:
        """Adapter has generate_with_image(prompt, image) -> str."""
        vlm = MagicMock()
        vlm._tier1_model = "m"
        vlm._call_gemini_vision = MagicMock(
            return_value={"text": "ok"},
        )
        adapter = VLMClientVisionAdapter(vlm)

        assert hasattr(adapter, "generate_with_image")
        result = await adapter.generate_with_image("p", b"i")
        assert isinstance(result, str)
