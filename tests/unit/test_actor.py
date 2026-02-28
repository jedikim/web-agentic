"""Tests for Actor — LLM element selection from candidates."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.actor import Actor
from src.core.browser import Browser
from src.core.types import Action, DOMNode, ScoredNode, StepPlan


def _scored(
    text: str = "Click",
    tag: str = "button",
    attrs: dict[str, str] | None = None,
    score: float = 1.0,
    node_id: int = 1,
    ax_name: str | None = None,
    ax_role: str | None = None,
) -> ScoredNode:
    return ScoredNode(
        node=DOMNode(
            node_id=node_id,
            tag=tag,
            text=text,
            attrs=attrs or {},
            ax_name=ax_name,
            ax_role=ax_role,
        ),
        score=score,
    )


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value='{"index": 0, "selector": "#btn", "action": "click"}')
    return llm


@pytest.fixture
def mock_browser() -> Browser:
    page = AsyncMock()
    page.url = "https://example.com"
    page.viewport_size = {"width": 1280, "height": 720}
    page.evaluate = AsyncMock(return_value={
        "cx": 0.5, "cy": 0.3,
        "x1": 0.4, "y1": 0.25, "x2": 0.6, "y2": 0.35,
    })
    page.context = AsyncMock()
    page.context.new_cdp_session = AsyncMock(return_value=AsyncMock())
    return Browser(page)


@pytest.fixture
def step() -> StepPlan:
    return StepPlan(
        step_index=0,
        action_type="click",
        target_description="검색 버튼",
        keyword_weights={"검색": 1.0},
    )


class TestActorDecide:
    async def test_basic_decide(
        self, mock_llm: AsyncMock, mock_browser: Browser, step: StepPlan,
    ) -> None:
        actor = Actor(llm=mock_llm)
        candidates = [_scored(text="검색", attrs={"id": "btn"})]

        action = await actor.decide(step, candidates, mock_browser)

        assert action.selector == "#btn"
        assert action.action_type == "click"
        assert action.viewport_xy is not None
        assert action.viewport_xy[0] == pytest.approx(0.5)

    async def test_empty_candidates(
        self, mock_llm: AsyncMock, mock_browser: Browser,
    ) -> None:
        step = StepPlan(
            step_index=0, action_type="click",
            target_description="invisible button",
            target_viewport_xy=(0.7, 0.8),
        )
        actor = Actor(llm=mock_llm)

        action = await actor.decide(step, [], mock_browser)

        assert action.selector is None
        assert action.viewport_xy == (0.7, 0.8)
        mock_llm.generate.assert_not_called()

    async def test_llm_called_with_yaml(
        self, mock_llm: AsyncMock, mock_browser: Browser, step: StepPlan,
    ) -> None:
        actor = Actor(llm=mock_llm)
        candidates = [
            _scored(text="검색", tag="button", score=1.0),
            _scored(text="로그인", tag="a", score=0.3, node_id=2),
        ]

        await actor.decide(step, candidates, mock_browser)

        call_args = mock_llm.generate.call_args
        prompt = call_args[0][0] if call_args[0] else call_args[1]["prompt"]
        assert "검색" in prompt
        assert "index: 0" in prompt
        assert "index: 1" in prompt

    async def test_type_action(
        self, mock_llm: AsyncMock, mock_browser: Browser,
    ) -> None:
        mock_llm.generate = AsyncMock(
            return_value='{"index": 0, "selector": "input#q", "action": "type", "value": "등산복"}'
        )
        step = StepPlan(
            step_index=0, action_type="type",
            target_description="검색창에 등산복 입력",
            value="등산복",
        )
        actor = Actor(llm=mock_llm)
        candidates = [_scored(
            text="", tag="input",
            attrs={"id": "q", "placeholder": "검색어"},
        )]

        action = await actor.decide(step, candidates, mock_browser)
        assert action.action_type == "type"
        assert action.value == "등산복"


class TestActorParsing:
    async def test_fallback_on_bad_json(
        self, mock_llm: AsyncMock, mock_browser: Browser, step: StepPlan,
    ) -> None:
        mock_llm.generate = AsyncMock(return_value="I think the first one")
        actor = Actor(llm=mock_llm)
        candidates = [_scored(text="검색", attrs={"id": "search-btn"})]

        action = await actor.decide(step, candidates, mock_browser)
        # Should fallback to first candidate
        assert action.selector == "#search-btn"

    async def test_invalid_index(
        self, mock_llm: AsyncMock, mock_browser: Browser, step: StepPlan,
    ) -> None:
        mock_llm.generate = AsyncMock(
            return_value='{"index": 99, "selector": "#x", "action": "click"}'
        )
        actor = Actor(llm=mock_llm)
        candidates = [_scored(text="검색", attrs={"id": "ok"})]

        action = await actor.decide(step, candidates, mock_browser)
        # Invalid index → fallback to first
        assert action.selector == "#ok"

    async def test_no_selector_in_response(
        self, mock_llm: AsyncMock, mock_browser: Browser, step: StepPlan,
    ) -> None:
        mock_llm.generate = AsyncMock(
            return_value='{"index": 0, "action": "click"}'
        )
        actor = Actor(llm=mock_llm)
        candidates = [_scored(text="검색", attrs={"name": "query"}, tag="input")]

        action = await actor.decide(step, candidates, mock_browser)
        # Should build selector from node attributes
        assert "query" in (action.selector or "")


class TestActorYAML:
    def test_yaml_format(self, mock_llm: AsyncMock) -> None:
        actor = Actor(llm=mock_llm)
        candidates = [
            _scored(
                text="Submit",
                tag="button",
                attrs={"id": "submit-btn", "type": "submit"},
                ax_name="Submit form",
                ax_role="button",
                score=1.5,
            ),
        ]
        yaml = actor._to_yaml(candidates)
        assert "index: 0" in yaml
        assert "tag: button" in yaml
        assert "text: Submit" in yaml
        assert "id: submit-btn" in yaml
        assert "name: Submit form" in yaml
        assert "score: 1.50" in yaml


class TestActorBuildSelector:
    def test_build_from_id(self, mock_llm: AsyncMock) -> None:
        actor = Actor(llm=mock_llm)
        node = DOMNode(node_id=1, tag="button", text="X", attrs={"id": "close"})
        assert actor._build_selector(node) == "#close"

    def test_build_from_name(self, mock_llm: AsyncMock) -> None:
        actor = Actor(llm=mock_llm)
        node = DOMNode(node_id=1, tag="input", text="", attrs={"name": "query"})
        assert actor._build_selector(node) == 'input[name="query"]'

    def test_build_from_aria_label(self, mock_llm: AsyncMock) -> None:
        actor = Actor(llm=mock_llm)
        node = DOMNode(node_id=1, tag="button", text="", attrs={"aria-label": "Close"})
        assert actor._build_selector(node) == 'button[aria-label="Close"]'

    def test_build_from_placeholder(self, mock_llm: AsyncMock) -> None:
        actor = Actor(llm=mock_llm)
        node = DOMNode(node_id=1, tag="input", text="", attrs={"placeholder": "검색어"})
        assert actor._build_selector(node) == 'input[placeholder*="검색어"]'

    def test_build_fallback_tag(self, mock_llm: AsyncMock) -> None:
        actor = Actor(llm=mock_llm)
        node = DOMNode(node_id=1, tag="span", text="text", attrs={})
        assert actor._build_selector(node) == "span"


class TestActorViewportCoords:
    async def test_returns_coords(self, mock_llm: AsyncMock, mock_browser: Browser) -> None:
        actor = Actor(llm=mock_llm)
        xy, bbox = await actor._get_viewport_coords(mock_browser, "#btn")
        assert xy == (0.5, 0.3)
        assert bbox == (0.4, 0.25, 0.6, 0.35)

    async def test_returns_none_for_no_selector(
        self, mock_llm: AsyncMock, mock_browser: Browser,
    ) -> None:
        actor = Actor(llm=mock_llm)
        xy, bbox = await actor._get_viewport_coords(mock_browser, None)
        assert xy is None
        assert bbox is None

    async def test_returns_none_on_error(
        self, mock_llm: AsyncMock, mock_browser: Browser,
    ) -> None:
        mock_browser._page.evaluate = AsyncMock(return_value=None)
        actor = Actor(llm=mock_llm)
        xy, bbox = await actor._get_viewport_coords(mock_browser, "#missing")
        assert xy is None
        assert bbox is None
