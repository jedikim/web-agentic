"""Tests for RetryHandler — LLM-assisted action retry."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.retry_handler import RetryHandler
from src.core.types import Action, DOMNode, StepPlan


@pytest.fixture
def mock_vlm() -> AsyncMock:
    vlm = AsyncMock()
    vlm.generate_with_image = AsyncMock(
        return_value='{"selector": "#alt-btn", "action": "click", "viewport_xy": [0.3, 0.7]}'
    )
    return vlm


@pytest.fixture
def failed_action() -> Action:
    return Action(selector="#btn", action_type="click", viewport_xy=(0.5, 0.3))


@pytest.fixture
def step() -> StepPlan:
    return StepPlan(
        step_index=0,
        action_type="click",
        target_description="검색 버튼 클릭",
        keyword_weights={"검색": 0.9},
        target_viewport_xy=(0.5, 0.3),
    )


class TestSuggestRetry:
    async def test_returns_new_action(
        self, mock_vlm: AsyncMock, failed_action: Action, step: StepPlan,
    ) -> None:
        handler = RetryHandler(vlm=mock_vlm)
        action = await handler.suggest_retry(
            failed_action, step, b"screenshot", "0: <button> id='alt-btn'",
        )
        assert action.selector == "#alt-btn"
        assert action.action_type == "click"
        assert action.viewport_xy == pytest.approx((0.3, 0.7))

    async def test_includes_failed_info_in_prompt(
        self, mock_vlm: AsyncMock, failed_action: Action, step: StepPlan,
    ) -> None:
        handler = RetryHandler(vlm=mock_vlm)
        await handler.suggest_retry(
            failed_action, step, b"screenshot", "dom info", attempt=2,
        )
        call_args = mock_vlm.generate_with_image.call_args
        prompt = call_args[0][0]
        assert "#btn" in prompt
        assert "2/3" in prompt
        assert "검색 버튼 클릭" in prompt

    async def test_malformed_response_uses_viewport_fallback(
        self, mock_vlm: AsyncMock, failed_action: Action, step: StepPlan,
    ) -> None:
        mock_vlm.generate_with_image = AsyncMock(return_value="I can't help with that")
        handler = RetryHandler(vlm=mock_vlm)
        action = await handler.suggest_retry(
            failed_action, step, b"screenshot", "",
        )
        assert action.selector is None
        assert action.viewport_xy == (0.5, 0.3)  # Falls back to step's xy

    async def test_type_action_retry(
        self, mock_vlm: AsyncMock,
    ) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value=(
                '{"selector": "input#q2", "action": "type",'
                ' "value": "등산복", "viewport_xy": [0.5, 0.1]}'
            )
        )
        step = StepPlan(
            step_index=0, action_type="type",
            target_description="검색어 입력", value="등산복",
            target_viewport_xy=(0.5, 0.05),
        )
        failed = Action(selector="input#q", action_type="type", value="등산복")

        handler = RetryHandler(vlm=mock_vlm)
        action = await handler.suggest_retry(failed, step, b"img", "")
        assert action.action_type == "type"
        assert action.value == "등산복"
        assert action.selector == "input#q2"

    async def test_invalid_viewport_xy_falls_back(
        self, mock_vlm: AsyncMock, failed_action: Action, step: StepPlan,
    ) -> None:
        mock_vlm.generate_with_image = AsyncMock(
            return_value='{"selector": "#x", "action": "click", "viewport_xy": "bad"}'
        )
        handler = RetryHandler(vlm=mock_vlm)
        action = await handler.suggest_retry(
            failed_action, step, b"screenshot", "",
        )
        assert action.selector == "#x"
        assert action.viewport_xy == (0.5, 0.3)  # Falls back to step


class TestFormatDomNodes:
    def test_basic_formatting(self) -> None:
        nodes = [
            DOMNode(node_id=1, tag="button", text="검색", attrs={"id": "search-btn"}),
            DOMNode(node_id=2, tag="input", text="", attrs={"placeholder": "검색어 입력"}),
        ]
        result = RetryHandler.format_dom_nodes(nodes)
        assert "0: <button>" in result
        assert '"검색"' in result
        assert 'id="search-btn"' in result
        assert "1: <input>" in result
        assert 'placeholder="검색어 입력"' in result

    def test_truncates_at_30(self) -> None:
        nodes = [
            DOMNode(node_id=i, tag="div", text=f"item{i}", attrs={})
            for i in range(50)
        ]
        result = RetryHandler.format_dom_nodes(nodes)
        lines = result.strip().split("\n")
        assert len(lines) == 30

    def test_empty_nodes(self) -> None:
        assert RetryHandler.format_dom_nodes([]) == ""

    def test_long_text_truncated(self) -> None:
        node = DOMNode(node_id=1, tag="p", text="a" * 200, attrs={})
        result = RetryHandler.format_dom_nodes([node])
        # Text should be truncated to 60 chars
        assert len(result) < 200
