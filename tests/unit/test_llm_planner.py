"""Unit tests for LLMPlanner — ``src.ai.llm_planner``."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.llm_planner import LLMPlanner, UsageStats, _extract_json, create_llm_planner
from src.ai.prompt_manager import PromptManager
from src.core.types import ExtractedElement, PatchData, StepDefinition


# ── Fixtures ─────────────────────────────────────────


@pytest.fixture()
def prompt_manager() -> PromptManager:
    """Fresh PromptManager with built-in prompts."""
    return PromptManager()


@pytest.fixture()
def planner(prompt_manager: PromptManager) -> LLMPlanner:
    """LLMPlanner with mocked API (no real Gemini calls)."""
    return LLMPlanner(
        prompt_manager=prompt_manager,
        api_key="test-key-not-real",
    )


@pytest.fixture()
def sample_candidates() -> list[ExtractedElement]:
    """Sample element candidates for select tests."""
    return [
        ExtractedElement(
            eid="btn-search",
            type="button",
            text="Search",
            role="button",
            visible=True,
        ),
        ExtractedElement(
            eid="link-home",
            type="link",
            text="Home",
            role="link",
            visible=True,
        ),
        ExtractedElement(
            eid="input-query",
            type="input",
            text="",
            role="textbox",
            visible=True,
        ),
    ]


# ── Helper: Mock Gemini response ─────────────────────


def _mock_gemini_response(text: str, total_tokens: int = 100) -> AsyncMock:
    """Create a mock for _call_gemini that returns given text and tokens."""
    return AsyncMock(return_value=(text, total_tokens))


# ── Test: Plan Parsing ───────────────────────────────


class TestPlanParsing:
    """Tests for _parse_plan_response."""

    def test_parse_direct_array(self) -> None:
        """Parses a direct JSON array of steps."""
        text = json.dumps([
            {
                "step_id": "step_1",
                "intent": "Navigate to page",
                "node_type": "action",
                "selector": None,
                "arguments": ["https://example.com"],
                "max_attempts": 3,
                "timeout_ms": 10000,
            },
            {
                "step_id": "step_2",
                "intent": "Click search",
                "node_type": "action",
                "selector": "#search-btn",
                "arguments": [],
            },
        ])
        steps, confidence = LLMPlanner._parse_plan_response(text)
        assert len(steps) == 2
        assert confidence == 1.0
        assert steps[0].step_id == "step_1"
        assert steps[0].intent == "Navigate to page"
        assert steps[0].arguments == ["https://example.com"]
        assert steps[1].selector == "#search-btn"

    def test_parse_wrapped_with_confidence(self) -> None:
        """Parses wrapped format with confidence score."""
        text = json.dumps({
            "confidence": 0.85,
            "steps": [
                {
                    "step_id": "s1",
                    "intent": "Click button",
                    "node_type": "action",
                },
            ],
        })
        steps, confidence = LLMPlanner._parse_plan_response(text)
        assert len(steps) == 1
        assert confidence == 0.85
        assert steps[0].step_id == "s1"

    def test_parse_with_markdown_fences(self) -> None:
        """Strips markdown code fences from response."""
        text = '```json\n[{"step_id": "s1", "intent": "test", "node_type": "action"}]\n```'
        steps, confidence = LLMPlanner._parse_plan_response(text)
        assert len(steps) == 1
        assert steps[0].intent == "test"

    def test_parse_empty_steps_raises(self) -> None:
        """Empty steps list raises ValueError."""
        text = json.dumps([])
        with pytest.raises(ValueError, match="no steps"):
            LLMPlanner._parse_plan_response(text)

    def test_parse_invalid_json_raises(self) -> None:
        """Invalid JSON raises JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            LLMPlanner._parse_plan_response("not valid json {{{")

    def test_parse_non_dict_step_raises(self) -> None:
        """Non-dict step entry raises ValueError."""
        text = json.dumps(["not a dict"])
        with pytest.raises(ValueError, match="not a dict"):
            LLMPlanner._parse_plan_response(text)

    def test_parse_defaults_for_missing_fields(self) -> None:
        """Missing optional fields use defaults."""
        text = json.dumps([{"intent": "do something"}])
        steps, _ = LLMPlanner._parse_plan_response(text)
        assert steps[0].step_id == "step_1"
        assert steps[0].node_type == "action"
        assert steps[0].selector is None
        assert steps[0].arguments == []
        assert steps[0].max_attempts == 3
        assert steps[0].timeout_ms == 10000


# ── Test: Select Parsing ─────────────────────────────


class TestSelectParsing:
    """Tests for _parse_select_response."""

    def test_parse_valid_select(self) -> None:
        """Parses a valid select response into PatchData."""
        text = json.dumps({
            "eid": "btn-search",
            "confidence": 0.95,
            "reasoning": "Button text matches",
        })
        patch = LLMPlanner._parse_select_response(text)
        assert isinstance(patch, PatchData)
        assert patch.patch_type == "selector_fix"
        assert patch.target == "btn-search"
        assert patch.confidence == 0.95
        assert patch.data["selected_eid"] == "btn-search"
        assert patch.data["reasoning"] == "Button text matches"

    def test_parse_select_with_markdown(self) -> None:
        """Handles markdown-wrapped select response."""
        text = '```json\n{"eid": "link-1", "confidence": 0.8, "reasoning": "best match"}\n```'
        patch = LLMPlanner._parse_select_response(text)
        assert patch.target == "link-1"

    def test_parse_select_missing_eid_raises(self) -> None:
        """Missing eid field raises KeyError."""
        text = json.dumps({"confidence": 0.9})
        with pytest.raises(KeyError):
            LLMPlanner._parse_select_response(text)

    def test_parse_select_default_confidence(self) -> None:
        """Missing confidence defaults to 0.5."""
        text = json.dumps({"eid": "btn-1"})
        patch = LLMPlanner._parse_select_response(text)
        assert patch.confidence == 0.5

    def test_parse_select_non_dict_raises(self) -> None:
        """Non-dict response raises ValueError."""
        text = json.dumps([{"eid": "x"}])
        with pytest.raises(ValueError, match="Expected dict"):
            LLMPlanner._parse_select_response(text)


# ── Test: Plan Method (with mocked API) ─────────────


class TestPlanMethod:
    """Tests for the plan() method with mocked Gemini API."""

    @pytest.mark.asyncio
    async def test_plan_tier1_success(self, planner: LLMPlanner) -> None:
        """Tier1 returns good confidence — no escalation."""
        response = json.dumps({
            "confidence": 0.9,
            "steps": [
                {"step_id": "s1", "intent": "Go to page", "node_type": "action"},
                {"step_id": "s2", "intent": "Click button", "node_type": "action"},
            ],
        })
        planner._call_gemini = _mock_gemini_response(response, 50)

        steps = await planner.plan("Search for laptops on Naver")
        assert len(steps) == 2
        assert steps[0].step_id == "s1"
        assert planner.usage.calls == 1
        assert planner.usage.escalations == 0

    @pytest.mark.asyncio
    async def test_plan_low_confidence_escalates(self, planner: LLMPlanner) -> None:
        """Tier1 returns low confidence — escalates to tier2."""
        tier1_response = json.dumps({
            "confidence": 0.5,
            "steps": [{"step_id": "s1", "intent": "unclear", "node_type": "action"}],
        })
        tier2_response = json.dumps({
            "confidence": 0.95,
            "steps": [
                {"step_id": "s1", "intent": "Navigate", "node_type": "action"},
                {"step_id": "s2", "intent": "Search", "node_type": "action"},
            ],
        })

        call_count = 0

        async def _mock_call(prompt: str, model: str) -> tuple[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return tier1_response, 50
            return tier2_response, 200

        planner._call_gemini = AsyncMock(side_effect=_mock_call)

        steps = await planner.plan("Complex task")
        assert len(steps) == 2
        assert planner.usage.calls == 2
        assert planner.usage.escalations == 1

    @pytest.mark.asyncio
    async def test_plan_parse_fail_escalates(self, planner: LLMPlanner) -> None:
        """Tier1 returns garbage — parse fails, escalates to tier2."""
        tier2_response = json.dumps([
            {"step_id": "s1", "intent": "Fixed step", "node_type": "action"},
        ])

        call_count = 0

        async def _mock_call(prompt: str, model: str) -> tuple[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "not valid json at all", 30
            return tier2_response, 100

        planner._call_gemini = AsyncMock(side_effect=_mock_call)

        steps = await planner.plan("Do something")
        assert len(steps) == 1
        assert steps[0].intent == "Fixed step"
        assert planner.usage.escalations == 1

    @pytest.mark.asyncio
    async def test_plan_uses_correct_prompt(
        self, planner: LLMPlanner, prompt_manager: PromptManager
    ) -> None:
        """Plan call uses the plan_steps prompt with instruction substituted."""
        captured_prompt = None

        async def _capture(prompt: str, model: str) -> tuple[str, int]:
            nonlocal captured_prompt
            captured_prompt = prompt
            return json.dumps([
                {"step_id": "s1", "intent": "test", "node_type": "action"}
            ]), 50

        planner._call_gemini = AsyncMock(side_effect=_capture)

        await planner.plan("Find laptop deals")
        assert captured_prompt is not None
        assert "Find laptop deals" in captured_prompt


# ── Test: Select Method (with mocked API) ────────────


class TestSelectMethod:
    """Tests for the select() method with mocked Gemini API."""

    @pytest.mark.asyncio
    async def test_select_tier1_success(
        self, planner: LLMPlanner, sample_candidates: list[ExtractedElement]
    ) -> None:
        """Tier1 returns good confidence — no escalation."""
        response = json.dumps({
            "eid": "btn-search",
            "confidence": 0.95,
            "reasoning": "Button text matches search intent",
        })
        planner._call_gemini = _mock_gemini_response(response, 80)

        patch = await planner.select(sample_candidates, "click search button")
        assert patch.target == "btn-search"
        assert patch.confidence == 0.95
        assert planner.usage.escalations == 0

    @pytest.mark.asyncio
    async def test_select_low_confidence_escalates(
        self, planner: LLMPlanner, sample_candidates: list[ExtractedElement]
    ) -> None:
        """Tier1 returns low confidence — escalates to tier2."""
        tier1_resp = json.dumps({
            "eid": "link-home",
            "confidence": 0.4,
            "reasoning": "uncertain",
        })
        tier2_resp = json.dumps({
            "eid": "btn-search",
            "confidence": 0.92,
            "reasoning": "Search button is the correct target",
        })

        call_count = 0

        async def _mock_call(prompt: str, model: str) -> tuple[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return tier1_resp, 60
            return tier2_resp, 150

        planner._call_gemini = AsyncMock(side_effect=_mock_call)

        patch = await planner.select(sample_candidates, "click search")
        assert patch.target == "btn-search"
        assert planner.usage.escalations == 1

    @pytest.mark.asyncio
    async def test_select_parse_fail_escalates(
        self, planner: LLMPlanner, sample_candidates: list[ExtractedElement]
    ) -> None:
        """Tier1 parse failure triggers tier2 escalation."""
        tier2_resp = json.dumps({
            "eid": "input-query",
            "confidence": 0.88,
            "reasoning": "Input field for typing",
        })

        call_count = 0

        async def _mock_call(prompt: str, model: str) -> tuple[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "broken response", 30
            return tier2_resp, 120

        planner._call_gemini = AsyncMock(side_effect=_mock_call)

        patch = await planner.select(sample_candidates, "type query")
        assert patch.target == "input-query"

    @pytest.mark.asyncio
    async def test_select_serializes_candidates(
        self, planner: LLMPlanner, sample_candidates: list[ExtractedElement]
    ) -> None:
        """Candidates are serialized to compact JSON in the prompt."""
        captured_prompt = None

        async def _capture(prompt: str, model: str) -> tuple[str, int]:
            nonlocal captured_prompt
            captured_prompt = prompt
            return json.dumps({
                "eid": "btn-search", "confidence": 0.9, "reasoning": "ok"
            }), 50

        planner._call_gemini = AsyncMock(side_effect=_capture)

        await planner.select(sample_candidates, "click search")
        assert captured_prompt is not None
        assert "btn-search" in captured_prompt
        assert "link-home" in captured_prompt
        assert "input-query" in captured_prompt


# ── Test: Cost Tracking ──────────────────────────────


class TestCostTracking:
    """Tests for token usage and cost tracking."""

    def test_usage_stats_record(self) -> None:
        """UsageStats.record accumulates tokens and cost."""
        stats = UsageStats()
        stats.record("gemini-2.0-flash", 1000)
        assert stats.total_tokens == 1000
        assert stats.total_cost_usd == pytest.approx(0.01)
        assert stats.calls == 1

    def test_usage_stats_multiple_models(self) -> None:
        """Records from different models accumulate correctly."""
        stats = UsageStats()
        stats.record("gemini-2.0-flash", 1000)  # 0.01
        stats.record("gemini-2.5-pro-preview-06-05", 1000)  # 0.05
        assert stats.total_tokens == 2000
        assert stats.total_cost_usd == pytest.approx(0.06)
        assert stats.calls == 2

    def test_usage_stats_call_log(self) -> None:
        """Each call is recorded in the call_log."""
        stats = UsageStats()
        stats.record("gemini-2.0-flash", 500)
        assert len(stats.call_log) == 1
        assert stats.call_log[0]["model"] == "gemini-2.0-flash"
        assert stats.call_log[0]["tokens"] == 500

    @pytest.mark.asyncio
    async def test_plan_tracks_cost(self, planner: LLMPlanner) -> None:
        """plan() records usage correctly."""
        response = json.dumps([
            {"step_id": "s1", "intent": "test", "node_type": "action"}
        ])
        planner._call_gemini = _mock_gemini_response(response, 200)

        await planner.plan("test instruction")
        assert planner.usage.total_tokens == 200
        assert planner.usage.total_cost_usd > 0

    def test_unknown_model_uses_default_cost(self) -> None:
        """Unknown model name falls back to default cost per token."""
        stats = UsageStats()
        stats.record("unknown-model-xyz", 1000)
        assert stats.total_cost_usd == pytest.approx(0.01)  # default rate


# ── Test: JSON Extraction Helper ─────────────────────


class TestExtractJson:
    """Tests for the _extract_json helper."""

    def test_plain_json(self) -> None:
        """Returns plain JSON unchanged."""
        assert _extract_json('{"key": "value"}') == '{"key": "value"}'

    def test_markdown_fenced_json(self) -> None:
        """Strips ```json fences."""
        text = '```json\n{"key": "value"}\n```'
        assert _extract_json(text) == '{"key": "value"}'

    def test_markdown_fenced_no_lang(self) -> None:
        """Strips ``` fences without language identifier."""
        text = '```\n[1, 2, 3]\n```'
        assert _extract_json(text) == '[1, 2, 3]'

    def test_whitespace_stripped(self) -> None:
        """Leading/trailing whitespace is stripped."""
        assert _extract_json("  \n  [1]  \n  ") == "[1]"


# ── Test: Factory ────────────────────────────────────


class TestFactory:
    """Tests for the create_llm_planner factory."""

    def test_create_llm_planner_returns_instance(self) -> None:
        """Factory returns a configured LLMPlanner."""
        planner = create_llm_planner(api_key="test-key")
        assert isinstance(planner, LLMPlanner)
        assert isinstance(planner.prompt_manager, PromptManager)

    def test_factory_default_models(self) -> None:
        """Factory creates planner with default model names."""
        planner = create_llm_planner(api_key="test-key")
        assert planner.tier1_model == "gemini-2.0-flash"
        assert planner.tier2_model == "gemini-2.5-pro-preview-06-05"
