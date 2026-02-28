"""Unit tests for LLMPlanner — ``src.ai.llm_planner``."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.ai.llm_planner import LLMPlanner, UsageStats, _extract_json, create_llm_planner
from src.ai.prompt_manager import PromptManager
from src.core.types import ExtractedElement, PatchData

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

    def test_field_aliases(self) -> None:
        """Accept id->step_id, description->intent, action->node_type."""
        text = json.dumps([{
            "id": "s1",
            "description": "click the button",
            "action": "extract",
        }])
        steps, _ = LLMPlanner._parse_plan_response(text)
        assert steps[0].step_id == "s1"
        assert steps[0].intent == "click the button"
        assert steps[0].node_type == "extract"

    def test_max_attempts_positive_validation(self) -> None:
        """max_attempts and timeout_ms are clamped to positive integers."""
        text = json.dumps([{
            "step_id": "s1",
            "intent": "test",
            "max_attempts": -1,
            "timeout_ms": 0,
        }])
        steps, _ = LLMPlanner._parse_plan_response(text)
        assert steps[0].max_attempts >= 1
        assert steps[0].timeout_ms >= 1

    def test_preamble_with_json_plan(self) -> None:
        """Parse plan response with preamble text before JSON."""
        text = "Sure! Here is the automation plan:\n" + json.dumps({
            "confidence": 0.95,
            "steps": [{"step_id": "s1", "intent": "navigate"}],
        })
        steps, confidence = LLMPlanner._parse_plan_response(text)
        assert len(steps) == 1
        assert confidence == 0.95


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

    def test_alternative_field_names(self) -> None:
        """Accept element_id, selected_eid, selector, id as alternatives to eid."""
        for field_name in ("element_id", "selected_eid", "selector", "id"):
            text = json.dumps({field_name: "btn-search", "confidence": 0.8})
            patch = LLMPlanner._parse_select_response(text)
            assert patch.target == "btn-search"
            assert patch.confidence == 0.8

    def test_confidence_clamping(self) -> None:
        """Confidence values are clamped to [0.0, 1.0]."""
        # Above 1.0
        text = json.dumps({"eid": "btn", "confidence": 1.5})
        patch = LLMPlanner._parse_select_response(text)
        assert patch.confidence == 1.0

        # Below 0.0
        text = json.dumps({"eid": "btn", "confidence": -0.3})
        patch = LLMPlanner._parse_select_response(text)
        assert patch.confidence == 0.0

    def test_alternative_reasoning_fields(self) -> None:
        """Accept reason, explanation as alternatives to reasoning."""
        for field_name in ("reason", "explanation"):
            text = json.dumps({"eid": "btn", field_name: "because it matches"})
            patch = LLMPlanner._parse_select_response(text)
            assert patch.data["reasoning"] == "because it matches"


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
    async def test_plan_low_confidence_no_escalation(self, planner: LLMPlanner) -> None:
        """Low confidence returns result as-is — no Pro escalation."""
        response = json.dumps({
            "confidence": 0.5,
            "steps": [{"step_id": "s1", "intent": "unclear", "node_type": "action"}],
        })
        planner._call_gemini = _mock_gemini_response(response, 50)

        steps = await planner.plan("Complex task")
        assert len(steps) == 1
        assert planner.usage.calls == 1
        assert planner.usage.escalations == 0

    @pytest.mark.asyncio
    async def test_plan_parse_fail_raises(self, planner: LLMPlanner) -> None:
        """Flash parse failure raises directly — no Pro fallback."""
        planner._call_gemini = _mock_gemini_response("not valid json at all", 30)

        with pytest.raises((json.JSONDecodeError, ValueError)):
            await planner.plan("Do something")

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
    async def test_select_low_confidence_no_escalation(
        self, planner: LLMPlanner, sample_candidates: list[ExtractedElement]
    ) -> None:
        """Tier1 returns low confidence — still returns it (no escalation)."""
        tier1_resp = json.dumps({
            "eid": "link-home",
            "confidence": 0.4,
            "reasoning": "uncertain",
        })

        planner._call_gemini = AsyncMock(return_value=(tier1_resp, 60))

        patch = await planner.select(sample_candidates, "click search")
        assert patch.target == "link-home"
        assert planner.usage.escalations == 0

    @pytest.mark.asyncio
    async def test_select_parse_fail_returns_empty(
        self, planner: LLMPlanner, sample_candidates: list[ExtractedElement]
    ) -> None:
        """Tier1 parse failure returns empty fallback (no escalation)."""
        planner._call_gemini = AsyncMock(return_value=("broken response", 30))

        patch = await planner.select(sample_candidates, "type query")
        assert patch.target == ""
        assert patch.confidence == 0.0

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
        # Compact JSON: no 'visible' field in candidates
        assert '"visible"' not in captured_prompt

    @pytest.mark.asyncio
    async def test_select_passes_page_context_to_prompt(
        self, planner: LLMPlanner, sample_candidates: list[ExtractedElement]
    ) -> None:
        """select() forwards page_context to the prompt template."""
        captured_prompt = None

        async def _capture(prompt: str, model: str) -> tuple[str, int]:
            nonlocal captured_prompt
            captured_prompt = prompt
            return json.dumps({
                "eid": "btn-search", "confidence": 0.9, "reasoning": "ok"
            }), 50

        planner._call_gemini = AsyncMock(side_effect=_capture)

        context = (
            "Page context:\n"
            "- URL: https://shopping.naver.com/sports\n"
            "- Title: 스포츠 - 네이버쇼핑\n"
            "- Previous action: Completed: Click Sports menu"
        )
        await planner.select(sample_candidates, "click jackets", page_context=context)
        assert captured_prompt is not None
        assert "https://shopping.naver.com/sports" in captured_prompt
        assert "스포츠 - 네이버쇼핑" in captured_prompt
        assert "Click Sports menu" in captured_prompt

    @pytest.mark.asyncio
    async def test_select_empty_page_context(
        self, planner: LLMPlanner, sample_candidates: list[ExtractedElement]
    ) -> None:
        """select() works fine with empty page_context (backward compatible)."""
        response = json.dumps({
            "eid": "btn-search",
            "confidence": 0.9,
            "reasoning": "ok",
        })
        planner._call_gemini = _mock_gemini_response(response, 50)

        patch = await planner.select(sample_candidates, "click search")
        assert patch.target == "btn-search"


# ── Test: Cost Tracking ──────────────────────────────


class TestCostTracking:
    """Tests for token usage and cost tracking."""

    def test_usage_stats_record(self) -> None:
        """UsageStats.record accumulates tokens and cost."""
        stats = UsageStats()
        # gemini-3-flash-preview: avg = (0.50 + 3.0) / 2 = 1.75 per million
        stats.record("gemini-3-flash-preview", 1000)
        assert stats.total_tokens == 1000
        assert stats.total_cost_usd == pytest.approx(0.00175)
        assert stats.calls == 1

    def test_usage_stats_multiple_models(self) -> None:
        """Records from different models accumulate correctly."""
        stats = UsageStats()
        # gemini-3-flash-preview: 1000 tokens → $0.00175
        stats.record("gemini-3-flash-preview", 1000)
        # gemini-3.1-pro-preview: avg = (2.00 + 12.0) / 2 = 7.0 → $0.007
        stats.record("gemini-3.1-pro-preview", 1000)
        assert stats.total_tokens == 2000
        assert stats.total_cost_usd == pytest.approx(0.00875)
        assert stats.calls == 2

    def test_usage_stats_call_log(self) -> None:
        """Each call is recorded in the call_log."""
        stats = UsageStats()
        stats.record("gemini-3-flash-preview", 500)
        assert len(stats.call_log) == 1
        assert stats.call_log[0]["model"] == "gemini-3-flash-preview"
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
        """Unknown model name falls back to default cost rate."""
        stats = UsageStats()
        # default: avg = (1.0 + 5.0) / 2 = 3.0 per million → $0.003
        stats.record("unknown-model-xyz", 1000)
        assert stats.total_cost_usd == pytest.approx(0.003)


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

    def test_preamble_before_json(self) -> None:
        """Extract JSON when preamble text precedes it."""
        text = 'Here is the analysis:\n{"eid": "btn-1", "confidence": 0.9}'
        result = _extract_json(text)
        data = json.loads(result)
        assert data["eid"] == "btn-1"

    def test_nested_braces(self) -> None:
        """Handle JSON with nested objects/arrays."""
        text = 'Some text {"outer": {"inner": [1, 2]}, "key": "val"} more text'
        result = _extract_json(text)
        data = json.loads(result)
        assert data["key"] == "val"
        assert data["outer"]["inner"] == [1, 2]

    def test_raw_array_no_fence(self) -> None:
        """Extract raw JSON array without markdown fences."""
        text = 'The steps are: [{"step_id": "s1", "intent": "click"}]'
        result = _extract_json(text)
        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["step_id"] == "s1"


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
        assert planner.tier1_model == "gemini-3-flash-preview"
        assert planner.tier2_model == "gemini-3.1-pro-preview"


# ── Test: Plan With Context ─────────────────────────


class TestPlanWithContext:
    """Tests for plan_with_context method."""

    @pytest.mark.asyncio
    async def test_plan_with_context_includes_page_info(self, monkeypatch):
        """plan_with_context passes page URL/title to prompt."""
        captured_prompts = []

        async def mock_call(self, prompt, model, images=None):
            captured_prompts.append(prompt)
            return (
                '{"confidence": 0.9, "steps": [{"step_id": "s1",'
                ' "intent": "click search", "node_type": "action"}]}'
            ), 100

        monkeypatch.setattr(LLMPlanner, "_call_gemini", mock_call)
        planner = LLMPlanner(PromptManager(), api_key="fake")
        steps = await planner.plan_with_context(
            instruction="노트북 검색",
            page_url="https://shopping.naver.com",
            page_title="네이버쇼핑",
            visible_text_snippet="검색 쇼핑하우 럭셔리",
        )
        assert len(steps) == 1
        assert "shopping.naver.com" in captured_prompts[0]
        assert "네이버쇼핑" in captured_prompts[0]
        assert "노트북 검색" in captured_prompts[0]
