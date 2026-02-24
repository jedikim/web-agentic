"""Unit tests for LLM provider abstraction and model registry."""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.llm_provider import (
    GeminiProvider,
    ILLMProvider,
    OpenAIProvider,
    create_provider,
)
from src.ai.model_registry import SUPPORTED_MODELS, resolve_model

# ── GeminiProvider ──────────────────────────────────────


class TestGeminiProvider:
    def test_creation(self) -> None:
        """GeminiProvider can be created with default model."""
        with patch("google.genai.Client") as mock_client_cls:
            mock_client_cls.return_value = MagicMock()
            provider = GeminiProvider(api_key="test-key")
            assert provider.model_name == "gemini-2.0-flash"
            assert provider.provider_name == "gemini"

    def test_custom_model(self) -> None:
        """GeminiProvider respects custom model name."""
        with patch("google.genai.Client") as mock_client_cls:
            mock_client_cls.return_value = MagicMock()
            provider = GeminiProvider(model="gemini-3-flash-preview", api_key="test-key")
            assert provider.model_name == "gemini-3-flash-preview"

    def test_is_illm_provider(self) -> None:
        """GeminiProvider satisfies ILLMProvider protocol."""
        with patch("google.genai.Client") as mock_client_cls:
            mock_client_cls.return_value = MagicMock()
            provider = GeminiProvider(api_key="test-key")
            assert isinstance(provider, ILLMProvider)

    @pytest.mark.asyncio()
    async def test_generate(self) -> None:
        """GeminiProvider.generate calls the Gemini API."""
        with patch("google.genai.Client") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.text = "Hello world"
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            provider = GeminiProvider(api_key="test-key")
            result = await provider.generate("Say hello")
            assert result == "Hello world"
            mock_client.aio.models.generate_content.assert_awaited_once()


# ── OpenAIProvider ──────────────────────────────────────


class TestOpenAIProvider:
    def test_creation(self) -> None:
        """OpenAIProvider can be created (with mock)."""
        mock_openai = MagicMock()
        with patch.dict(sys.modules, {"openai": mock_openai}):
            provider = OpenAIProvider(api_key="test-key")
            assert provider.model_name == "gpt-4o"
            assert provider.provider_name == "openai"

    def test_import_error(self) -> None:
        """OpenAIProvider raises ImportError when openai not installed."""
        with patch.dict(sys.modules, {"openai": None}), pytest.raises(
            ImportError, match="openai package required"
        ):
            OpenAIProvider(api_key="test-key")

    def test_is_illm_provider(self) -> None:
        """OpenAIProvider satisfies ILLMProvider protocol."""
        mock_openai = MagicMock()
        with patch.dict(sys.modules, {"openai": mock_openai}):
            provider = OpenAIProvider(api_key="test-key")
            assert isinstance(provider, ILLMProvider)


# ── Factory ─────────────────────────────────────────────


class TestCreateProvider:
    def test_gemini_factory(self) -> None:
        """create_provider('gemini') returns GeminiProvider."""
        with patch("google.genai.Client") as mock_client_cls:
            mock_client_cls.return_value = MagicMock()
            provider = create_provider("gemini", api_key="test")
            assert isinstance(provider, GeminiProvider)

    def test_openai_factory(self) -> None:
        """create_provider('openai') returns OpenAIProvider."""
        mock_openai = MagicMock()
        with patch.dict(sys.modules, {"openai": mock_openai}):
            provider = create_provider("openai", api_key="test")
            assert isinstance(provider, OpenAIProvider)

    def test_unknown_provider(self) -> None:
        """create_provider with unknown name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("anthropic")

    def test_model_override(self) -> None:
        """create_provider passes model override through."""
        with patch("google.genai.Client") as mock_client_cls:
            mock_client_cls.return_value = MagicMock()
            provider = create_provider("gemini", model="gemini-3-flash-preview", api_key="test")
            assert provider.model_name == "gemini-3-flash-preview"


# ── Model Registry ──────────────────────────────────────


class TestModelRegistry:
    def test_resolve_flash_gemini(self) -> None:
        """Resolve default flash model for gemini."""
        provider, model = resolve_model(tier="flash", provider="gemini")
        assert provider == "gemini"
        assert "flash" in model.lower() or "2.0" in model

    def test_resolve_pro_openai(self) -> None:
        """Resolve default pro model for openai."""
        provider, model = resolve_model(tier="pro", provider="openai")
        assert provider == "openai"
        assert model == "gpt-4o"

    def test_resolve_explicit_model(self) -> None:
        """Explicit model name resolves to its registered provider."""
        provider, model = resolve_model(model="gpt-4o")
        assert provider == "openai"
        assert model == "gpt-4o"

    def test_resolve_unknown_model(self) -> None:
        """Unknown model name falls back to given provider."""
        provider, model = resolve_model(model="custom-model", provider="gemini")
        assert provider == "gemini"
        assert model == "custom-model"

    def test_resolve_invalid_raises(self) -> None:
        """Invalid provider+tier raises ValueError."""
        with pytest.raises(ValueError, match="Cannot resolve model"):
            resolve_model(tier="flash", provider="unknown")

    def test_supported_models_populated(self) -> None:
        """SUPPORTED_MODELS contains expected entries."""
        assert "gpt-4o" in SUPPORTED_MODELS
        assert "gemini-2.0-flash" in SUPPORTED_MODELS
        assert SUPPORTED_MODELS["gpt-4o"]["provider"] == "openai"
