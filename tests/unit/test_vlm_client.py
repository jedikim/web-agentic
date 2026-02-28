"""Unit tests for VLM client — ``src.vision.vlm_client``."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.core.types import ExtractedElement, PatchData
from src.vision.vlm_client import (
    VLMClient,
    create_vlm_client,
)
from src.vision.yolo_detector import Detection

# ── Fixtures ────────────────────────────────────────


@pytest.fixture()
def client() -> VLMClient:
    """Create a VLMClient with a fake API key."""
    return VLMClient(api_key="test-key-12345")


@pytest.fixture()
def candidates() -> list[ExtractedElement]:
    """Sample candidate elements for selection tests."""
    return [
        ExtractedElement(
            eid="btn-login",
            type="button",
            text="Login",
            bbox=(100, 200, 80, 30),
        ),
        ExtractedElement(
            eid="btn-signup",
            type="button",
            text="Sign Up",
            bbox=(200, 200, 100, 30),
        ),
        ExtractedElement(
            eid="input-search",
            type="input",
            text="Search...",
            bbox=(300, 50, 200, 35),
        ),
    ]


@pytest.fixture()
def screenshot_bytes() -> bytes:
    """Minimal fake screenshot bytes (not a real image, but sufficient for mocked calls)."""
    return b"\x89PNG\r\n\x1a\nfake_image_data"


def _make_gemini_response(text: str, input_tokens: int = 100, output_tokens: int = 50) -> dict:
    """Create a fake Gemini API response dict."""
    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


# ── select_element() Tests ──────────────────────────


class TestSelectElement:
    """Tests for VLMClient.select_element()."""

    @pytest.mark.asyncio
    async def test_select_element_returns_patch_data(
        self, client: VLMClient, screenshot_bytes: bytes, candidates: list[ExtractedElement]
    ) -> None:
        """select_element() returns a PatchData object."""
        response = _make_gemini_response(
            json.dumps({"index": 0, "confidence": 0.9, "reason": "Login button matches intent"})
        )
        with patch.object(client, "_call_gemini_vision", return_value=response):
            result = await client.select_element(screenshot_bytes, candidates, "click login")
        assert isinstance(result, PatchData)
        assert result.patch_type == "selector_fix"

    @pytest.mark.asyncio
    async def test_select_element_picks_correct_candidate(
        self, client: VLMClient, screenshot_bytes: bytes, candidates: list[ExtractedElement]
    ) -> None:
        """select_element() selects the candidate indicated by the VLM."""
        response = _make_gemini_response(
            json.dumps({"index": 1, "confidence": 0.85, "reason": "Sign Up button"})
        )
        with patch.object(client, "_call_gemini_vision", return_value=response):
            result = await client.select_element(screenshot_bytes, candidates, "click sign up")
        assert result.target == "btn-signup"
        assert result.data["text"] == "Sign Up"

    @pytest.mark.asyncio
    async def test_select_element_confidence_in_patch(
        self, client: VLMClient, screenshot_bytes: bytes, candidates: list[ExtractedElement]
    ) -> None:
        """PatchData confidence reflects VLM confidence."""
        response = _make_gemini_response(
            json.dumps({"index": 0, "confidence": 0.92, "reason": "exact match"})
        )
        with patch.object(client, "_call_gemini_vision", return_value=response):
            result = await client.select_element(screenshot_bytes, candidates, "click login")
        assert result.confidence == 0.92

    @pytest.mark.asyncio
    async def test_select_element_tier_escalation(
        self, client: VLMClient, screenshot_bytes: bytes, candidates: list[ExtractedElement]
    ) -> None:
        """Low tier-1 confidence triggers tier-2 escalation."""
        tier1_response = _make_gemini_response(
            json.dumps({"index": 0, "confidence": 0.4, "reason": "uncertain"})
        )
        tier2_response = _make_gemini_response(
            json.dumps({"index": 1, "confidence": 0.95, "reason": "high confidence"})
        )
        call_count = 0

        def mock_call(model_name, image_bytes, prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return tier1_response
            return tier2_response

        with patch.object(client, "_call_gemini_vision", side_effect=mock_call):
            result = await client.select_element(screenshot_bytes, candidates, "click something")
        assert call_count == 2
        assert result.confidence == 0.95
        assert result.target == "btn-signup"

    @pytest.mark.asyncio
    async def test_select_element_no_escalation_when_confident(
        self, client: VLMClient, screenshot_bytes: bytes, candidates: list[ExtractedElement]
    ) -> None:
        """High tier-1 confidence does NOT trigger tier-2."""
        response = _make_gemini_response(
            json.dumps({"index": 0, "confidence": 0.9, "reason": "confident"})
        )
        call_count = 0

        def mock_call(model_name, image_bytes, prompt):
            nonlocal call_count
            call_count += 1
            return response

        with patch.object(client, "_call_gemini_vision", side_effect=mock_call):
            await client.select_element(screenshot_bytes, candidates, "click login")
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_select_element_out_of_range_index_defaults_to_zero(
        self, client: VLMClient, screenshot_bytes: bytes, candidates: list[ExtractedElement]
    ) -> None:
        """Index out of range falls back to first candidate."""
        response = _make_gemini_response(
            json.dumps({"index": 99, "confidence": 0.8, "reason": "out of range"})
        )
        with patch.object(client, "_call_gemini_vision", return_value=response):
            result = await client.select_element(screenshot_bytes, candidates, "click something")
        assert result.target == "btn-login"  # first candidate

    @pytest.mark.asyncio
    async def test_select_element_malformed_json_fallback(
        self, client: VLMClient, screenshot_bytes: bytes, candidates: list[ExtractedElement]
    ) -> None:
        """Malformed VLM response falls back gracefully."""
        response = _make_gemini_response("I think candidate 1 is best for this task")
        with patch.object(client, "_call_gemini_vision", return_value=response):
            result = await client.select_element(screenshot_bytes, candidates, "click something")
        # Should parse "1" from text.
        assert result.target == "btn-signup"


# ── describe_page() Tests ───────────────────────────


class TestDescribePage:
    """Tests for VLMClient.describe_page()."""

    @pytest.mark.asyncio
    async def test_describe_page_returns_string(
        self, client: VLMClient, screenshot_bytes: bytes
    ) -> None:
        """describe_page() returns a string description."""
        response = _make_gemini_response(
            "This is a login page with email and password fields."
        )
        with patch.object(client, "_call_gemini_vision", return_value=response):
            result = await client.describe_page(screenshot_bytes)
        assert isinstance(result, str)
        assert "login" in result.lower()

    @pytest.mark.asyncio
    async def test_describe_page_uses_tier1_model(
        self, client: VLMClient, screenshot_bytes: bytes
    ) -> None:
        """describe_page() uses the tier-1 model."""
        response = _make_gemini_response("A web page.")
        models_used = []

        def mock_call(model_name, image_bytes, prompt):
            models_used.append(model_name)
            return response

        with patch.object(client, "_call_gemini_vision", side_effect=mock_call):
            await client.describe_page(screenshot_bytes)
        assert models_used == ["gemini-3-flash-preview"]


# ── find_element() Tests ────────────────────────────


class TestFindElement:
    """Tests for VLMClient.find_element()."""

    @pytest.mark.asyncio
    async def test_find_element_returns_detection(
        self, client: VLMClient, screenshot_bytes: bytes
    ) -> None:
        """find_element() returns a Detection when element is found."""
        response = _make_gemini_response(
            json.dumps({
                "found": True,
                "label": "button",
                "confidence": 0.88,
                "bbox": [100, 200, 80, 30],
            })
        )
        with patch.object(client, "_call_gemini_vision", return_value=response):
            result = await client.find_element(screenshot_bytes, "the login button")
        assert isinstance(result, Detection)
        assert result.label == "button"
        assert result.confidence == 0.88
        assert result.bbox == (100, 200, 80, 30)

    @pytest.mark.asyncio
    async def test_find_element_returns_none_when_not_found(
        self, client: VLMClient, screenshot_bytes: bytes
    ) -> None:
        """find_element() returns None when element is not found."""
        response = _make_gemini_response(json.dumps({"found": False}))
        with patch.object(client, "_call_gemini_vision", return_value=response):
            result = await client.find_element(screenshot_bytes, "nonexistent element")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_element_tier_escalation(
        self, client: VLMClient, screenshot_bytes: bytes
    ) -> None:
        """Low confidence find triggers tier-2 escalation."""
        tier1 = _make_gemini_response(json.dumps({
            "found": True, "label": "button",
            "confidence": 0.4, "bbox": [10, 20, 30, 40],
        }))
        tier2 = _make_gemini_response(json.dumps({
            "found": True, "label": "button",
            "confidence": 0.9, "bbox": [15, 25, 35, 45],
        }))
        calls = []

        def mock_call(model_name, image_bytes, prompt):
            calls.append(model_name)
            if len(calls) == 1:
                return tier1
            return tier2

        with patch.object(client, "_call_gemini_vision", side_effect=mock_call):
            result = await client.find_element(screenshot_bytes, "a button")
        assert len(calls) == 2
        assert result is not None
        assert result.confidence == 0.9
        assert result.bbox == (15, 25, 35, 45)

    @pytest.mark.asyncio
    async def test_find_element_malformed_response_returns_none(
        self, client: VLMClient, screenshot_bytes: bytes
    ) -> None:
        """Malformed response returns None."""
        response = _make_gemini_response("I cannot find that element anywhere.")
        with patch.object(client, "_call_gemini_vision", return_value=response):
            result = await client.find_element(screenshot_bytes, "something")
        assert result is None


# ── analyze_grid() Tests ──────────────────────────


class TestAnalyzeGrid:
    """Tests for VLMClient.analyze_grid()."""

    @pytest.mark.asyncio
    async def test_analyze_grid_parses_response(
        self, client: VLMClient, screenshot_bytes: bytes
    ) -> None:
        """analyze_grid() parses a well-formed JSON array response."""
        vlm_response = _make_gemini_response(json.dumps([
            {
                "index": 0, "label": "shoes", "confidence": 0.9,
                "relevant": True, "description": "Red sneakers",
                "reason": "matches intent",
            },
            {
                "index": 1, "label": "hat", "confidence": 0.7,
                "relevant": False, "description": "Blue hat",
                "reason": "not shoes",
            },
        ]))
        with patch.object(client, "_call_gemini_vision", return_value=vlm_response):
            results = await client.analyze_grid(screenshot_bytes, "find shoes", cell_count=2)
        assert len(results) == 2
        assert results[0]["index"] == 0
        assert results[0]["label"] == "shoes"
        assert results[0]["relevant"] is True
        assert results[1]["relevant"] is False

    @pytest.mark.asyncio
    async def test_analyze_grid_single_api_call(
        self, client: VLMClient, screenshot_bytes: bytes
    ) -> None:
        """analyze_grid() makes exactly one API call."""
        vlm_response = _make_gemini_response(
            json.dumps([{
                "index": 0, "label": "item", "confidence": 0.5,
                "relevant": True, "description": "", "reason": "",
            }])
        )
        call_count = 0

        def mock_call(model_name, image_bytes, prompt):
            nonlocal call_count
            call_count += 1
            return vlm_response

        with patch.object(client, "_call_gemini_vision", side_effect=mock_call):
            await client.analyze_grid(screenshot_bytes, "find item", cell_count=1)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_analyze_grid_malformed_response_fallback(
        self, client: VLMClient, screenshot_bytes: bytes
    ) -> None:
        """Malformed VLM response returns empty fallback results."""
        vlm_response = _make_gemini_response("I cannot parse this image properly.")
        with patch.object(client, "_call_gemini_vision", return_value=vlm_response):
            results = await client.analyze_grid(screenshot_bytes, "find item", cell_count=3)
        assert len(results) == 3
        for r in results:
            assert r["confidence"] == 0.0
            assert r["relevant"] is False

    @pytest.mark.asyncio
    async def test_analyze_grid_uses_tier1_model(
        self, client: VLMClient, screenshot_bytes: bytes
    ) -> None:
        """analyze_grid() uses the tier-1 model."""
        vlm_response = _make_gemini_response("[]")
        models_used = []

        def mock_call(model_name, image_bytes, prompt):
            models_used.append(model_name)
            return vlm_response

        with patch.object(client, "_call_gemini_vision", side_effect=mock_call):
            await client.analyze_grid(screenshot_bytes, "test", cell_count=1)
        assert models_used == ["gemini-3-flash-preview"]


# ── Cost Tracking Tests ─────────────────────────────


class TestCostTracking:
    """Tests for VLM usage and cost tracking."""

    @pytest.mark.asyncio
    async def test_stats_initialized_to_zero(self, client: VLMClient) -> None:
        """Stats start at zero."""
        stats = client.stats
        assert stats.total_calls == 0
        assert stats.total_input_tokens == 0
        assert stats.total_output_tokens == 0
        assert stats.estimated_cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_stats_updated_after_call(
        self, client: VLMClient, screenshot_bytes: bytes
    ) -> None:
        """Stats are updated after an API call."""
        response = _make_gemini_response("A page.", input_tokens=200, output_tokens=100)
        with patch.object(client, "_call_gemini_vision", return_value=response):
            await client.describe_page(screenshot_bytes)
        stats = client.stats
        assert stats.total_calls == 1
        assert stats.total_input_tokens == 200
        assert stats.total_output_tokens == 100
        assert stats.tier1_calls == 1
        assert stats.estimated_cost_usd > 0.0

    @pytest.mark.asyncio
    async def test_stats_accumulate_across_calls(
        self, client: VLMClient, screenshot_bytes: bytes
    ) -> None:
        """Stats accumulate across multiple calls."""
        response = _make_gemini_response("A page.", input_tokens=100, output_tokens=50)
        with patch.object(client, "_call_gemini_vision", return_value=response):
            await client.describe_page(screenshot_bytes)
            await client.describe_page(screenshot_bytes)
        stats = client.stats
        assert stats.total_calls == 2
        assert stats.total_input_tokens == 200
        assert stats.total_output_tokens == 100

    @pytest.mark.asyncio
    async def test_tier2_calls_tracked(
        self, client: VLMClient, screenshot_bytes: bytes, candidates: list[ExtractedElement]
    ) -> None:
        """Tier-2 escalation calls are tracked separately."""
        tier1 = _make_gemini_response(
            json.dumps({"index": 0, "confidence": 0.3, "reason": "low"}),
            input_tokens=100, output_tokens=50,
        )
        tier2 = _make_gemini_response(
            json.dumps({"index": 0, "confidence": 0.9, "reason": "high"}),
            input_tokens=200, output_tokens=80,
        )
        call_count = 0

        def mock_call(model_name, image_bytes, prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return tier1
            return tier2

        with patch.object(client, "_call_gemini_vision", side_effect=mock_call):
            await client.select_element(screenshot_bytes, candidates, "click something")
        stats = client.stats
        assert stats.tier1_calls == 1
        assert stats.tier2_calls == 1
        assert stats.total_calls == 2


# ── Factory Tests ───────────────────────────────────


class TestFactory:
    """Tests for the create_vlm_client factory."""

    def test_create_with_defaults(self) -> None:
        """Factory creates a client with default settings."""
        c = create_vlm_client(api_key="test-key")
        assert isinstance(c, VLMClient)
        assert c._tier1_model == "gemini-3-flash-preview"
        assert c._tier2_model == "gemini-3.1-pro-preview"

    def test_create_with_custom_models(self) -> None:
        """Factory accepts custom model names."""
        c = create_vlm_client(
            api_key="key",
            tier1_model="custom-flash",
            tier2_model="custom-pro",
        )
        assert c._tier1_model == "custom-flash"
        assert c._tier2_model == "custom-pro"
