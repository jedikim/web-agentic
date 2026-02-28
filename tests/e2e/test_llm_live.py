"""Live LLM E2E tests — verifies real Gemini API calls work.

Only runs when GOOGLE_API_KEY or GEMINI_API_KEY is set.
Tests actual model availability and response parsing.
"""
from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")),
        reason="Gemini API key not set (need GOOGLE_API_KEY or GEMINI_API_KEY)",
    ),
]


# ── LLM Planner: plan() ─────────────────────────────


class TestLLMPlannerLive:
    """Test LLMPlanner with real Gemini API calls."""

    async def test_plan_returns_steps(self) -> None:
        """plan() returns valid StepDefinition list from real API."""
        from src.ai.llm_planner import create_llm_planner

        planner = create_llm_planner()
        steps = await planner.plan("Go to example.com and click the More information link")

        assert len(steps) >= 1
        for step in steps:
            assert step.intent  # non-empty intent
            assert step.step_id  # non-empty step_id
        assert planner.usage.calls >= 1
        assert planner.usage.total_tokens > 0
        assert planner.usage.total_cost_usd > 0

    async def test_plan_tier1_model_name(self) -> None:
        """plan() uses the configured tier1 model (gemini-3-flash-preview)."""
        from src.ai.llm_planner import DEFAULT_FLASH_MODEL, create_llm_planner

        planner = create_llm_planner()
        assert planner.tier1_model == DEFAULT_FLASH_MODEL

        await planner.plan("Navigate to example.com")
        assert planner.usage.call_log[0]["model"] == DEFAULT_FLASH_MODEL

    async def test_select_returns_patch(self) -> None:
        """select() returns PatchData from real API."""
        from src.ai.llm_planner import create_llm_planner
        from src.core.types import ExtractedElement, PatchData

        planner = create_llm_planner()
        candidates = [
            ExtractedElement(eid="btn-login", type="button", text="Login"),
            ExtractedElement(eid="btn-signup", type="button", text="Sign Up"),
            ExtractedElement(eid="link-help", type="link", text="Help"),
        ]
        patch = await planner.select(candidates, "click the login button")

        assert isinstance(patch, PatchData)
        assert patch.target in {"btn-login", "btn-signup", "link-help"}
        assert 0.0 <= patch.confidence <= 1.0


# ── VLM Client: text-only capability check ──────────


class TestVLMClientLive:
    """Test VLMClient with real Gemini API (text prompt, minimal image)."""

    async def test_describe_page_returns_text(self) -> None:
        """describe_page() returns a non-empty string description."""
        from src.vision.vlm_client import create_vlm_client

        client = create_vlm_client()

        # Minimal 2x2 red PNG
        import struct
        import zlib

        def _make_png() -> bytes:
            def chunk(t: bytes, d: bytes) -> bytes:
                c = t + d
                crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
                return struct.pack(">I", len(d)) + c + crc

            ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
            raw = b"\x00\xff\x00\x00\xff\x00\x00" * 2
            idat = zlib.compress(raw)
            return (
                b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", idat)
                + chunk(b"IEND", b"")
            )

        screenshot = _make_png()
        description = await client.describe_page(screenshot)

        assert isinstance(description, str)
        assert len(description) > 10
        assert client.stats.total_calls == 1
        assert client.stats.tier1_calls == 1

    async def test_vlm_model_defaults(self) -> None:
        """VLM client uses correct default model names."""
        from src.vision.vlm_client import (
            DEFAULT_VLM_FLASH,
            DEFAULT_VLM_PRO,
            create_vlm_client,
        )

        client = create_vlm_client()
        assert client._tier1_model == DEFAULT_VLM_FLASH
        assert client._tier2_model == DEFAULT_VLM_PRO
        assert "gemini-3-flash-preview" in DEFAULT_VLM_FLASH
        assert "gemini-3.1-pro-preview" in DEFAULT_VLM_PRO


# ── Code Generator: model availability ──────────────


class TestCodeGeneratorLive:
    """Test EvolutionCodeGenerator model connectivity."""

    async def test_code_generator_model_reachable(self) -> None:
        """Code generator can reach the Pro model (gemini-3.1-pro-preview)."""
        from src.evolution.code_generator import EvolutionCodeGenerator

        gen = EvolutionCodeGenerator()
        result = await gen.generate_fixes(
            failure_patterns=[{
                "pattern_type": "timeout",
                "error_message": "TimeoutError: page.click exceeded 30000ms",
                "count": 3,
            }],
            relevant_files={
                "src/example.py": "async def click(selector): await page.click(selector)",
            },
        )

        # Even if the LLM returns imperfect JSON, the call itself should succeed
        assert result is not None
        assert result.usage.calls >= 1
        assert result.usage.total_tokens > 0
