"""Tests for v3 Orchestrator — main execution loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.browser import Browser
from src.core.cache import Cache, InMemoryCacheDB
from src.core.types import Action, CacheEntry, DOMNode, ScoredNode, ScreenState, StepPlan
from src.core.v3_orchestrator import V3Orchestrator


def _step(
    idx: int = 0,
    action_type: str = "click",
    desc: str = "검색 버튼",
    kw: dict[str, float] | None = None,
    xy: tuple[float, float] | None = (0.5, 0.3),
    expected: str | None = None,
) -> StepPlan:
    return StepPlan(
        step_index=idx,
        action_type=action_type,
        target_description=desc,
        keyword_weights=kw or {"검색": 0.9},
        target_viewport_xy=xy,
        expected_result=expected,
    )


def _scored(score: float = 0.8) -> ScoredNode:
    return ScoredNode(
        node=DOMNode(node_id=1, tag="button", text="검색", attrs={"id": "btn"}),
        score=score,
    )


def _action(selector: str = "#btn") -> Action:
    return Action(
        selector=selector,
        action_type="click",
        viewport_xy=(0.5, 0.3),
    )


@pytest.fixture
def mock_browser() -> Browser:
    page = AsyncMock()
    page.url = "https://example.com"
    page.viewport_size = {"width": 1280, "height": 720}
    page.screenshot = AsyncMock(return_value=b"screenshot-bytes")
    page.evaluate = AsyncMock(return_value=True)
    page.mouse = AsyncMock()
    page.mouse.click = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.context = AsyncMock()
    page.context.new_cdp_session = AsyncMock(return_value=AsyncMock())
    return Browser(page)


@pytest.fixture
def planner() -> AsyncMock:
    p = AsyncMock()
    p.check_screen = AsyncMock(return_value=ScreenState(has_obstacle=False))
    p.plan = AsyncMock(return_value=[_step()])
    return p


@pytest.fixture
def extractor() -> AsyncMock:
    e = AsyncMock()
    e.extract = AsyncMock(return_value=[
        DOMNode(node_id=1, tag="button", text="검색", attrs={"id": "btn"}),
    ])
    return e


@pytest.fixture
def element_filter() -> MagicMock:
    f = MagicMock()
    f.filter = MagicMock(return_value=[_scored(0.8)])
    return f


@pytest.fixture
def actor() -> AsyncMock:
    a = AsyncMock()
    a.decide = AsyncMock(return_value=_action())
    return a


@pytest.fixture
def executor() -> AsyncMock:
    e = AsyncMock()
    e.execute_action = AsyncMock()
    return e


@pytest.fixture
def cache() -> Cache:
    return Cache(db=InMemoryCacheDB())


@pytest.fixture
def verifier() -> AsyncMock:
    v = AsyncMock()
    v.verify_result = AsyncMock(return_value="ok")
    return v


@pytest.fixture
def orchestrator(
    planner: AsyncMock,
    extractor: AsyncMock,
    element_filter: MagicMock,
    actor: AsyncMock,
    executor: AsyncMock,
    cache: Cache,
    verifier: AsyncMock,
) -> V3Orchestrator:
    return V3Orchestrator(
        planner=planner,
        extractor=extractor,
        element_filter=element_filter,
        actor=actor,
        executor=executor,
        cache=cache,
        verifier=verifier,
    )


class TestRunBasic:
    async def test_single_step_success(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
    ) -> None:
        result = await orchestrator.run("검색 버튼 클릭", mock_browser)
        assert result is True

    async def test_empty_plan_returns_false(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock,
    ) -> None:
        planner.plan = AsyncMock(return_value=[])
        result = await orchestrator.run("impossible task", mock_browser)
        assert result is False

    async def test_multi_step_success(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock,
    ) -> None:
        planner.plan = AsyncMock(return_value=[
            _step(0, desc="검색창 클릭"),
            _step(1, action_type="type", desc="검색어 입력"),
            _step(2, desc="검색 버튼"),
        ])
        result = await orchestrator.run("등산복 검색", mock_browser)
        assert result is True


class TestCachedPath:
    async def test_uses_cache_on_hit(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        cache: Cache, executor: AsyncMock, verifier: AsyncMock,
    ) -> None:
        # Pre-populate cache
        await cache.store(CacheEntry(
            domain="example.com",
            url_pattern="https://example.com",
            task_type="검색 버튼",
            selector="#cached-btn",
            action_type="click",
            viewport_xy=(0.5, 0.3),
        ))

        result = await orchestrator.run("검색 버튼 클릭", mock_browser)
        assert result is True

        # Check that the cached selector was used
        call_args = executor.execute_action.call_args
        action = call_args[0][0]
        assert action.selector == "#cached-btn"

    async def test_cache_miss_goes_to_full_pipeline(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        actor: AsyncMock,
    ) -> None:
        # No cache entry → full pipeline → actor.decide should be called
        result = await orchestrator.run("검색 버튼 클릭", mock_browser)
        assert result is True
        actor.decide.assert_called()

    async def test_cache_failed_falls_through(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        cache: Cache, verifier: AsyncMock, actor: AsyncMock,
    ) -> None:
        await cache.store(CacheEntry(
            domain="example.com",
            url_pattern="https://example.com",
            task_type="검색 버튼",
            selector="#stale-btn",
            action_type="click",
        ))

        # First verify call returns "failed" (cache path), second returns "ok" (full pipeline)
        verifier.verify_result = AsyncMock(side_effect=["failed", "ok"])

        result = await orchestrator.run("검색 버튼 클릭", mock_browser)
        assert result is True
        # Actor should have been called for full pipeline
        actor.decide.assert_called()


class TestFullPipeline:
    async def test_low_score_uses_viewport(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        element_filter: MagicMock, actor: AsyncMock, executor: AsyncMock,
    ) -> None:
        # Low score → viewport path
        element_filter.filter = MagicMock(return_value=[_scored(0.1)])

        result = await orchestrator.run("아이콘 클릭", mock_browser)
        assert result is True
        # Actor should NOT be called (low score)
        actor.decide.assert_not_called()

    async def test_high_score_uses_actor(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        element_filter: MagicMock, actor: AsyncMock,
    ) -> None:
        element_filter.filter = MagicMock(return_value=[_scored(0.9)])

        result = await orchestrator.run("검색 버튼 클릭", mock_browser)
        assert result is True
        actor.decide.assert_called()

    async def test_empty_candidates_uses_viewport(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        element_filter: MagicMock, actor: AsyncMock,
    ) -> None:
        element_filter.filter = MagicMock(return_value=[])

        result = await orchestrator.run("invisible button", mock_browser)
        assert result is True
        actor.decide.assert_not_called()


class TestReplan:
    async def test_replan_on_consecutive_failures(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock, verifier: AsyncMock, executor: AsyncMock,
    ) -> None:
        # Step fails twice (2 consecutive), triggers replan, then succeeds
        fail_step = _step(0, desc="broken step")
        ok_step = _step(0, desc="fixed step")
        planner.plan = AsyncMock(side_effect=[
            [fail_step],   # initial plan
            [ok_step],     # replan
        ])

        # Executor raises for first 6 calls (2 attempts × 3 retries each)
        # Then succeeds for replan
        call_count = 0

        async def side_effect_executor(action: Action, browser: Browser) -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 6:
                raise RuntimeError("element not found")

        executor.execute_action = AsyncMock(side_effect=side_effect_executor)
        verifier.verify_result = AsyncMock(return_value="ok")

        result = await orchestrator.run("task", mock_browser)
        assert result is True
        assert planner.plan.call_count == 2  # initial + replan


class TestObstacleRemoval:
    async def test_obstacle_removed(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock,
    ) -> None:
        # First check: obstacle, second check: clean
        planner.check_screen = AsyncMock(side_effect=[
            ScreenState(has_obstacle=True, obstacle_type="popup", obstacle_close_xy=(0.95, 0.05)),
            ScreenState(has_obstacle=False),
        ])

        result = await orchestrator.run("task", mock_browser)
        assert result is True
        # Should have clicked to remove obstacle
        mock_browser._page.mouse.click.assert_called()

    async def test_obstacle_escape_fallback(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock,
    ) -> None:
        # Obstacle without close_xy → Escape key
        planner.check_screen = AsyncMock(side_effect=[
            ScreenState(has_obstacle=True, obstacle_type="modal"),
            ScreenState(has_obstacle=False),
        ])

        result = await orchestrator.run("task", mock_browser)
        assert result is True
        mock_browser._page.keyboard.press.assert_called_with("Escape")


class TestCacheStore:
    async def test_success_stores_in_cache(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        cache: Cache,
    ) -> None:
        await orchestrator.run("검색 버튼 클릭", mock_browser)

        # Should be cached now
        entry = await cache.lookup("example.com", "https://example.com", "검색 버튼")
        assert entry is not None
        assert entry.action_type == "click"


class TestGetDomain:
    def test_extracts_domain(self, orchestrator: V3Orchestrator) -> None:
        assert orchestrator._get_domain("https://shop.naver.com/search") == "shop.naver.com"

    def test_empty_url(self, orchestrator: V3Orchestrator) -> None:
        assert orchestrator._get_domain("") == ""

    def test_invalid_url(self, orchestrator: V3Orchestrator) -> None:
        assert orchestrator._get_domain("not-a-url") == ""
