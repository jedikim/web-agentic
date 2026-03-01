"""Tests for Planner — VLM screenshot-first planning."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.core.planner import Planner, _extract_json_array, _extract_json_object


@pytest.fixture
def mock_vlm() -> AsyncMock:
    vlm = AsyncMock()
    vlm.generate_with_image = AsyncMock(return_value="{}")
    return vlm


class TestCheckScreen:
    async def test_no_obstacle(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value='{"has_obstacle": false}'
        )
        planner = Planner(vlm=mock_vlm)
        state = await planner.check_screen(b"screenshot")

        assert not state.has_obstacle
        assert state.obstacle_type is None
        assert state.obstacle_close_xy is None

    async def test_popup_detected(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value=json.dumps({
                "has_obstacle": True,
                "obstacle_type": "popup",
                "obstacle_close_xy": [0.95, 0.05],
                "obstacle_description": "이벤트 팝업",
            })
        )
        planner = Planner(vlm=mock_vlm)
        state = await planner.check_screen(b"screenshot")

        assert state.has_obstacle
        assert state.obstacle_type == "popup"
        assert state.obstacle_close_xy == (0.95, 0.05)
        assert state.obstacle_description == "이벤트 팝업"

    async def test_cookie_consent(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value=json.dumps({
                "has_obstacle": True,
                "obstacle_type": "cookie_consent",
                "obstacle_close_xy": [0.5, 0.85],
                "obstacle_description": "쿠키 동의창",
            })
        )
        planner = Planner(vlm=mock_vlm)
        state = await planner.check_screen(b"screenshot")

        assert state.has_obstacle
        assert state.obstacle_type == "cookie_consent"
        assert state.obstacle_close_xy == pytest.approx((0.5, 0.85))

    async def test_malformed_response(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value="I can't parse this as JSON"
        )
        planner = Planner(vlm=mock_vlm)
        state = await planner.check_screen(b"screenshot")

        # Falls back to default ScreenState
        assert not state.has_obstacle

    async def test_invalid_close_xy(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value=json.dumps({
                "has_obstacle": True,
                "obstacle_type": "popup",
                "obstacle_close_xy": "not a list",
            })
        )
        planner = Planner(vlm=mock_vlm)
        state = await planner.check_screen(b"screenshot")

        assert state.has_obstacle
        assert state.obstacle_close_xy is None

    async def test_empty_close_xy_list(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value=json.dumps({
                "has_obstacle": True,
                "obstacle_type": "popup",
                "obstacle_close_xy": [],
            })
        )
        planner = Planner(vlm=mock_vlm)
        state = await planner.check_screen(b"screenshot")

        assert state.has_obstacle
        assert state.obstacle_close_xy is None

    async def test_prompt_sent_with_image(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(return_value='{"has_obstacle": false}')
        planner = Planner(vlm=mock_vlm)
        await planner.check_screen(b"screenshot-data")

        mock_vlm.generate_with_image.assert_called_once()
        call_args = mock_vlm.generate_with_image.call_args
        assert call_args[0][1] == b"screenshot-data"
        assert "방해" in call_args[0][0]  # Korean prompt word


class TestPlan:
    async def test_single_step(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value=json.dumps([{
                "step_index": 0,
                "action_type": "click",
                "target_description": "스포츠/레저 카테고리 메뉴",
                "keyword_weights": {"스포츠": 0.9, "레저": 0.8},
                "target_viewport_xy": [0.15, 0.35],
                "expected_result": "URL 변경: /category/sports",
            }])
        )
        planner = Planner(vlm=mock_vlm)
        steps = await planner.plan("등산복 찾기", b"screenshot")

        assert len(steps) == 1
        assert steps[0].action_type == "click"
        assert steps[0].target_description == "스포츠/레저 카테고리 메뉴"
        assert steps[0].keyword_weights == {"스포츠": 0.9, "레저": 0.8}
        assert steps[0].target_viewport_xy == pytest.approx((0.15, 0.35))
        assert steps[0].expected_result == "URL 변경: /category/sports"

    async def test_multi_step(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value=json.dumps([
                {
                    "step_index": 0,
                    "action_type": "click",
                    "target_description": "검색창",
                    "keyword_weights": {"검색": 0.9, "search": 0.8},
                    "target_viewport_xy": [0.5, 0.05],
                    "expected_result": "DOM 존재: input:focus",
                },
                {
                    "step_index": 1,
                    "action_type": "type",
                    "target_description": "검색어 입력",
                    "value": "등산복",
                    "keyword_weights": {"검색": 0.9},
                    "target_viewport_xy": [0.5, 0.05],
                    "expected_result": "화면 변화",
                },
                {
                    "step_index": 2,
                    "action_type": "press",
                    "target_description": "엔터 누르기",
                    "keyword_weights": {},
                    "target_viewport_xy": [0.5, 0.05],
                    "expected_result": "URL 변경: /search?q=등산복",
                },
            ])
        )
        planner = Planner(vlm=mock_vlm)
        steps = await planner.plan("등산복 검색", b"screenshot")

        assert len(steps) == 3
        assert steps[0].action_type == "click"
        assert steps[1].action_type == "type"
        assert steps[1].value == "등산복"
        assert steps[2].action_type == "press"

    async def test_malformed_response_returns_empty(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value="I don't understand the task"
        )
        planner = Planner(vlm=mock_vlm)
        steps = await planner.plan("something", b"screenshot")

        assert steps == []

    async def test_missing_keyword_weights(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value=json.dumps([{
                "step_index": 0,
                "action_type": "click",
                "target_description": "button",
                "target_viewport_xy": [0.5, 0.5],
            }])
        )
        planner = Planner(vlm=mock_vlm)
        steps = await planner.plan("click button", b"screenshot")

        assert len(steps) == 1
        assert steps[0].keyword_weights == {}

    async def test_missing_viewport_xy(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value=json.dumps([{
                "step_index": 0,
                "action_type": "click",
                "target_description": "button",
                "keyword_weights": {"button": 1.0},
            }])
        )
        planner = Planner(vlm=mock_vlm)
        steps = await planner.plan("click button", b"screenshot")

        assert len(steps) == 1
        assert steps[0].target_viewport_xy is None

    async def test_code_fence_json(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value='```json\n[{"step_index": 0, "action_type": "click", '
            '"target_description": "btn", "keyword_weights": {}, '
            '"target_viewport_xy": [0.5, 0.5]}]\n```'
        )
        planner = Planner(vlm=mock_vlm)
        steps = await planner.plan("click", b"screenshot")

        assert len(steps) == 1
        assert steps[0].action_type == "click"

    async def test_step_index_auto_assigned(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value=json.dumps([
                {"action_type": "click", "target_description": "a"},
                {"action_type": "type", "target_description": "b", "value": "x"},
            ])
        )
        planner = Planner(vlm=mock_vlm)
        steps = await planner.plan("task", b"screenshot")

        assert len(steps) == 2
        assert steps[0].step_index == 0
        assert steps[1].step_index == 1

    async def test_prompt_includes_task(self, mock_vlm: AsyncMock) -> None:
        mock_vlm.generate_with_image = AsyncMock(return_value="[]")
        planner = Planner(vlm=mock_vlm)
        await planner.plan("나이키 운동화 검색", b"img")

        call_args = mock_vlm.generate_with_image.call_args
        assert "나이키 운동화 검색" in call_args[0][0]


class TestExtractJsonObject:
    def test_raw_json(self) -> None:
        result = _extract_json_object('{"has_obstacle": true}')
        assert result == {"has_obstacle": True}

    def test_code_fence(self) -> None:
        result = _extract_json_object('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_surrounding_text(self) -> None:
        result = _extract_json_object('Here is the result: {"x": 1} done.')
        assert result == {"x": 1}

    def test_invalid_returns_none(self) -> None:
        assert _extract_json_object("no json here") is None

    def test_empty_string(self) -> None:
        assert _extract_json_object("") is None


class TestExtractJsonArray:
    def test_raw_array(self) -> None:
        result = _extract_json_array('[{"a": 1}]')
        assert result == [{"a": 1}]

    def test_code_fence(self) -> None:
        result = _extract_json_array('```json\n[{"a": 1}]\n```')
        assert result == [{"a": 1}]

    def test_nested_arrays(self) -> None:
        result = _extract_json_array('[{"kw": {"a": 1}}, {"kw": {"b": 2}}]')
        assert result is not None
        assert len(result) == 2

    def test_surrounding_text(self) -> None:
        result = _extract_json_array('Steps: [{"a": 1}] end')
        assert result == [{"a": 1}]

    def test_invalid_returns_none(self) -> None:
        assert _extract_json_array("no array here") is None

    def test_empty_string(self) -> None:
        assert _extract_json_array("") is None

    def test_unbalanced_brackets(self) -> None:
        # Should handle gracefully
        result = _extract_json_array('[{"a": 1}')
        assert result is None


class TestPlannerPromptManager:
    async def test_plan_uses_prompt_manager(self) -> None:
        """Planner loads plan prompt from PromptManager when available."""
        from src.ai.prompt_manager import PromptManager

        pm = PromptManager()
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(return_value="[]")
        planner = Planner(vlm=vlm, prompt_manager=pm)

        await planner.plan("테스트 태스크", b"screenshot")

        prompt = vlm.generate_with_image.call_args[0][0]
        assert "테스트 태스크" in prompt
        assert "visual_filter" in prompt

    async def test_check_screen_uses_prompt_manager(self) -> None:
        """Planner loads check_screen prompt from PromptManager."""
        from src.ai.prompt_manager import PromptManager

        pm = PromptManager()
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(
            return_value='{"has_obstacle": false}',
        )
        planner = Planner(vlm=vlm, prompt_manager=pm)

        state = await planner.check_screen(b"screenshot")
        assert not state.has_obstacle

        prompt = vlm.generate_with_image.call_args[0][0]
        assert "obstacle" in prompt

    async def test_fallback_when_no_prompt_manager(self) -> None:
        """Planner uses inline prompts when PromptManager is None."""
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(return_value="[]")
        planner = Planner(vlm=vlm)  # No prompt_manager

        await planner.plan("fallback test", b"screenshot")

        prompt = vlm.generate_with_image.call_args[0][0]
        assert "fallback test" in prompt
        assert "visual_filter" in prompt

    async def test_fallback_when_prompt_not_registered(self) -> None:
        """Planner falls back to inline if PromptManager lacks the prompt."""
        from src.ai.prompt_manager import PromptManager
        from pathlib import Path

        # Empty dir → no prompts loaded
        pm = PromptManager(prompts_dir=Path("/tmp/nonexistent_prompts_dir"))
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(return_value="[]")
        planner = Planner(vlm=vlm, prompt_manager=pm)

        await planner.plan("missing prompt", b"screenshot")

        prompt = vlm.generate_with_image.call_args[0][0]
        assert "missing prompt" in prompt


class TestPlannerSiteKnowledge:
    async def test_plan_with_site_knowledge(self) -> None:
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(return_value="[]")
        planner = Planner(vlm=vlm)

        await planner.plan(
            "검색 버튼 클릭", b"screenshot",
            site_knowledge="## 메뉴\n- hover로 탐색",
        )

        prompt = vlm.generate_with_image.call_args[0][0]
        assert "메뉴" in prompt
        assert "hover" in prompt

    async def test_plan_without_site_knowledge(self) -> None:
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(return_value="[]")
        planner = Planner(vlm=vlm)

        await planner.plan("검색", b"screenshot")

        prompt = vlm.generate_with_image.call_args[0][0]
        assert "[사이트 지식]" not in prompt


class TestPlannerVisualFilter:
    async def test_parse_visual_filter_step(self) -> None:
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(return_value="""[
            {
                "step_index": 0,
                "action_type": "visual_filter",
                "target_description": "빨간색 상품 선택",
                "visual_filter_query": "빨간색",
                "visual_complexity": "simple",
                "keyword_weights": {},
                "target_viewport_xy": [0.5, 0.5]
            }
        ]""")
        planner = Planner(vlm=vlm)
        steps = await planner.plan("빨간색 찾기", b"screenshot")

        assert len(steps) == 1
        assert steps[0].action_type == "visual_filter"
        assert steps[0].visual_filter_query == "빨간색"
        assert steps[0].visual_complexity == "simple"

    async def test_visual_filter_null_fields(self) -> None:
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(return_value=json.dumps([{
            "step_index": 0,
            "action_type": "click",
            "target_description": "버튼",
            "visual_filter_query": None,
            "visual_complexity": None,
            "keyword_weights": {"버튼": 0.9},
            "target_viewport_xy": [0.5, 0.5],
        }]))
        planner = Planner(vlm=vlm)
        steps = await planner.plan("버튼 클릭", b"screenshot")

        assert len(steps) == 1
        assert steps[0].visual_filter_query is None
        assert steps[0].visual_complexity is None

    async def test_prompt_contains_visual_filter_guidance(self) -> None:
        vlm = AsyncMock()
        vlm.generate_with_image = AsyncMock(return_value="[]")
        planner = Planner(vlm=vlm)
        await planner.plan("빨간색 상품 찾기", b"img")

        prompt = vlm.generate_with_image.call_args[0][0]
        assert "visual_filter" in prompt
        assert "visual_filter_query" in prompt
        assert "visual_complexity" in prompt
