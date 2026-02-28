"""Tests for v3 data types."""

from __future__ import annotations

import pytest

from src.core.types import (
    Action,
    CacheEntry,
    Detection,
    DOMNode,
    ScoredNode,
    ScreenState,
    Skill,
    StepPlan,
    V3StepResult,
)


class TestDOMNode:
    def test_create_minimal(self) -> None:
        node = DOMNode(node_id=1, tag="button", text="Click")
        assert node.node_id == 1
        assert node.tag == "button"
        assert node.text == "Click"
        assert node.attrs == {}
        assert node.ax_role is None
        assert node.ax_name is None

    def test_create_full(self) -> None:
        node = DOMNode(
            node_id=42,
            tag="input",
            text="",
            attrs={"type": "text", "placeholder": "검색"},
            ax_role="textbox",
            ax_name="Search",
        )
        assert node.attrs["placeholder"] == "검색"
        assert node.ax_role == "textbox"


class TestScoredNode:
    def test_create(self) -> None:
        node = DOMNode(node_id=1, tag="a", text="Link")
        scored = ScoredNode(node=node, score=0.85)
        assert scored.node.tag == "a"
        assert scored.score == 0.85

    def test_default_score(self) -> None:
        node = DOMNode(node_id=1, tag="a", text="Link")
        scored = ScoredNode(node=node)
        assert scored.score == 0.0


class TestScreenState:
    def test_default(self) -> None:
        state = ScreenState()
        assert state.has_obstacle is False
        assert state.obstacle_type is None

    def test_with_obstacle(self) -> None:
        state = ScreenState(
            has_obstacle=True,
            obstacle_type="popup",
            obstacle_close_xy=(0.95, 0.05),
            obstacle_description="Cookie consent dialog",
        )
        assert state.has_obstacle is True
        assert state.obstacle_close_xy == (0.95, 0.05)


class TestStepPlan:
    def test_create(self) -> None:
        step = StepPlan(
            step_index=0,
            action_type="click",
            target_description="검색 버튼",
            keyword_weights={"검색": 1.0, "버튼": 0.5},
            target_viewport_xy=(0.5, 0.1),
        )
        assert step.step_index == 0
        assert step.keyword_weights["검색"] == 1.0
        assert step.target_viewport_xy == (0.5, 0.1)

    def test_defaults(self) -> None:
        step = StepPlan(
            step_index=1,
            action_type="fill",
            target_description="검색창",
        )
        assert step.value is None
        assert step.keyword_weights == {}
        assert step.target_viewport_xy is None
        assert step.expected_result is None


class TestAction:
    def test_create(self) -> None:
        action = Action(
            selector="input#search",
            action_type="fill",
            value="등산복",
            viewport_xy=(0.5, 0.1),
        )
        assert action.selector == "input#search"
        assert action.value == "등산복"

    def test_no_selector(self) -> None:
        action = Action(
            selector=None,
            action_type="click",
            viewport_xy=(0.3, 0.4),
        )
        assert action.selector is None


class TestCacheEntry:
    def test_create(self) -> None:
        entry = CacheEntry(
            domain="shopping.naver.com",
            url_pattern="https://shopping.naver.com/*",
            task_type="검색창 클릭",
            selector="input[name=query]",
            action_type="click",
            keyword_weights={"검색": 1.0},
        )
        assert entry.domain == "shopping.naver.com"
        assert entry.success_count == 0


class TestSkill:
    def test_create(self) -> None:
        skill = Skill(
            name="naver_search",
            domain="shopping.naver.com",
            task_pattern="검색",
            code="async def naver_search(browser, query): ...",
        )
        assert skill.name == "naver_search"
        assert skill.success_count == 0


class TestDetection:
    def test_create(self) -> None:
        det = Detection(box=(10.0, 20.0, 100.0, 80.0), confidence=0.92)
        assert det.box == (10.0, 20.0, 100.0, 80.0)
        assert det.confidence == 0.92


class TestV3StepResult:
    def test_create(self) -> None:
        step = StepPlan(step_index=0, action_type="click", target_description="btn")
        action = Action(selector="button", action_type="click")
        result = V3StepResult(
            step=step,
            action=action,
            success=True,
            pre_url="https://a.com",
            post_url="https://a.com/next",
        )
        assert result.success is True
        assert result.post_url == "https://a.com/next"
