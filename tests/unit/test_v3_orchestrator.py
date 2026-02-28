"""Tests for v3 Orchestrator — main execution loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.browser import Browser
from src.core.cache import Cache, InMemoryCacheDB
from src.core.types import Action, CacheEntry, DOMNode, ScoredNode, ScreenState, StepPlan
from src.core.v3_orchestrator import MAX_PROGRESSIVE_REPLAN, V3Orchestrator


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


class TestProgressivePlanning:
    """Tests for progressive planning — re-plan after page navigation."""

    async def test_replan_after_url_change(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock,
    ) -> None:
        """When step causes URL change and remaining steps exist, re-plan."""
        step1 = _step(0, desc="검색 버튼 클릭", expected="URL 변경: /search")
        step2 = _step(1, desc="결과 정렬")
        step3 = _step(0, desc="인기순 정렬 버튼")

        planner.plan = AsyncMock(side_effect=[
            [step1, step2],  # initial plan
            [step3],         # progressive re-plan after page nav
        ])

        # Track URL: changes after first execute_action call
        url_state = {"url": "https://example.com"}
        mock_browser._page.url = url_state["url"]

        execute_count = [0]

        async def on_execute(action: Action, browser: Browser) -> None:
            execute_count[0] += 1
            if execute_count[0] == 1:
                url_state["url"] = "https://example.com/search"
                mock_browser._page.url = url_state["url"]

        orchestrator.executor.execute_action = AsyncMock(side_effect=on_execute)

        result = await orchestrator.run("검색 후 인기순 정렬", mock_browser)
        assert result is True
        # initial + progressive re-plan
        assert planner.plan.call_count == 2

    async def test_no_replan_when_url_same(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock,
    ) -> None:
        """No re-plan when URL stays the same (same-page interaction)."""
        planner.plan = AsyncMock(return_value=[
            _step(0, desc="드롭다운 열기"),
            _step(1, desc="옵션 선택"),
        ])

        result = await orchestrator.run("드롭다운에서 옵션 선택", mock_browser)
        assert result is True
        # Only initial plan, no progressive re-plan
        assert planner.plan.call_count == 1

    async def test_no_replan_on_last_step(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock,
    ) -> None:
        """No re-plan when URL changes on the LAST step (no remaining)."""
        planner.plan = AsyncMock(return_value=[_step(0, desc="검색 버튼")])

        async def on_execute(action: Action, browser: Browser) -> None:
            mock_browser._page.url = "https://example.com/results"

        orchestrator.executor.execute_action = AsyncMock(side_effect=on_execute)

        result = await orchestrator.run("검색", mock_browser)
        assert result is True
        # Only initial plan — last step doesn't trigger progressive replan
        assert planner.plan.call_count == 1

    async def test_progressive_replan_limit(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock,
    ) -> None:
        """Progressive re-plans are capped at MAX_PROGRESSIVE_REPLAN."""
        url_counter = [0]

        async def mock_plan(task: str, screenshot: bytes) -> list[StepPlan]:
            return [
                _step(0, desc="step-A"),
                _step(1, desc="step-B"),
            ]

        planner.plan = AsyncMock(side_effect=mock_plan)

        async def on_execute(action: Action, browser: Browser) -> None:
            url_counter[0] += 1
            mock_browser._page.url = f"https://example.com/page{url_counter[0]}"

        orchestrator.executor.execute_action = AsyncMock(side_effect=on_execute)

        result = await orchestrator.run("many page task", mock_browser)
        assert result is True
        # 1 initial + MAX_PROGRESSIVE_REPLAN progressive
        assert planner.plan.call_count == 1 + MAX_PROGRESSIVE_REPLAN


class TestLazyReplan:
    """Tests for lazy replan — DOM-based next-step validation."""

    async def test_hover_menu_triggers_replan(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock, element_filter: MagicMock,
    ) -> None:
        """After hover, if next step's target not in DOM, replan."""
        step_hover = _step(0, action_type="hover", desc="전체 카테고리 호버")
        step_sub = _step(1, desc="스포츠/골프 클릭", kw={"스포츠": 0.9, "골프": 0.9})
        step_after = _step(0, desc="등산복 클릭")

        planner.plan = AsyncMock(side_effect=[
            [step_hover, step_sub],  # initial: hover + guess submenu
            [step_after],            # replan: now can see submenu
        ])

        # After hover, filter returns LOW score for next step (submenu not
        # visible yet in mock DOM) — triggers lazy replan
        call_count = [0]

        def smart_filter(nodes: list, kw: dict) -> list:  # type: ignore[type-arg]
            call_count[0] += 1
            # Lazy replan DOM check: return low score to trigger replan
            if "스포츠" in kw:
                return [_scored(0.1)]  # Not found → triggers replan
            return [_scored(0.8)]  # Normal

        element_filter.filter = MagicMock(side_effect=smart_filter)

        result = await orchestrator.run(
            "전체 카테고리에서 스포츠/골프 > 등산복", mock_browser,
        )
        assert result is True
        # initial + lazy replan after hover
        assert planner.plan.call_count == 2

    async def test_type_action_skips_replan(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock, element_filter: MagicMock,
    ) -> None:
        """Type/fill actions skip lazy replan (don't change page structure)."""
        planner.plan = AsyncMock(return_value=[
            _step(0, action_type="type", desc="검색어 입력"),
            _step(1, desc="검색 버튼 클릭"),
        ])

        # Even if filter returns low score for next step,
        # type action should NOT trigger replan
        element_filter.filter = MagicMock(return_value=[_scored(0.1)])

        result = await orchestrator.run("검색", mock_browser)
        assert result is True
        # Only initial plan — type action skips replan check
        assert planner.plan.call_count == 1

    async def test_next_step_findable_no_replan(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock, element_filter: MagicMock,
    ) -> None:
        """If next step's target is findable in DOM, don't replan."""
        planner.plan = AsyncMock(return_value=[
            _step(0, desc="첫 번째 클릭"),
            _step(1, desc="두 번째 클릭"),
        ])

        # Filter always returns high score → next step always findable
        element_filter.filter = MagicMock(return_value=[_scored(0.9)])

        result = await orchestrator.run("두 번 클릭", mock_browser)
        assert result is True
        assert planner.plan.call_count == 1


class TestProgressivePlanningWithResult:
    """Same progressive tests but via run_with_result for API path."""

    async def test_replan_after_url_change_with_result(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock,
    ) -> None:
        step1 = _step(0, desc="검색 버튼")
        step2 = _step(1, desc="구버전 결과 스텝")
        step3 = _step(0, desc="새페이지 스텝")

        planner.plan = AsyncMock(side_effect=[
            [step1, step2],  # initial
            [step3],         # progressive re-plan
            [],              # post-completion check: no more steps
        ])

        call_count = [0]

        async def on_execute(action: Action, browser: Browser) -> None:
            call_count[0] += 1
            if call_count[0] == 1:
                mock_browser._page.url = "https://example.com/search"

        orchestrator.executor.execute_action = AsyncMock(side_effect=on_execute)

        result = await orchestrator.run_with_result("검색", mock_browser)
        assert result.success is True
        # 2 steps executed: step1 (original) + step3 (from re-plan)
        assert sum(1 for o in result.step_results if o.success) == 2
        # plan called: initial + progressive + post-completion check
        assert planner.plan.call_count == 3

    async def test_post_completion_adds_extra_steps(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock,
    ) -> None:
        """After all steps done, planner finds more work needed."""
        initial_step = _step(0, desc="검색어 입력")
        extra_step = _step(0, desc="검색 버튼 클릭")

        planner.plan = AsyncMock(side_effect=[
            [initial_step],   # initial plan
            [extra_step],     # post-completion: more work needed
            [],               # post-completion after extra: done
        ])

        result = await orchestrator.run_with_result("노트북 검색", mock_browser)
        assert result.success is True
        assert len(result.step_results) == 2  # initial + extra
        # initial + post-completion + post-completion-of-extra
        assert planner.plan.call_count == 3

    async def test_post_completion_no_extra_needed(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock,
    ) -> None:
        """Post-completion check returns empty — task is truly done."""
        planner.plan = AsyncMock(side_effect=[
            [_step(0, desc="버튼 클릭")],  # initial
            [],                              # post-completion: done
        ])

        result = await orchestrator.run_with_result("간단한 클릭", mock_browser)
        assert result.success is True
        assert len(result.step_results) == 1


class TestFastHoverFollowup:
    """Tests for fast hover followup — DOM-based click after hover."""

    async def test_hover_followup_bypasses_vlm(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock, element_filter: MagicMock,
        extractor: AsyncMock, verifier: AsyncMock,
    ) -> None:
        """After hover (last step), fast followup clicks without VLM."""
        hover_step = _step(
            0, action_type="hover", desc="전체 카테고리 호버",
        )
        # Only need initial plan — fast followup handles next action
        planner.plan = AsyncMock(side_effect=[
            [hover_step],  # initial plan
            [],            # post-completion after fast followup
        ])

        # After hover, DOM contains submenu items matching task keywords
        submenu_node = DOMNode(
            node_id=2, tag="a", text="여성스포츠의류",
            attrs={"href": "/sports/women"},
        )
        extractor.extract = AsyncMock(return_value=[submenu_node])
        element_filter.filter = MagicMock(return_value=[
            ScoredNode(node=submenu_node, score=0.85),
        ])
        # Mock browser.evaluate for coordinate lookup
        mock_browser._page.evaluate = AsyncMock(return_value={
            "cx": 0.3, "cy": 0.5,
        })
        verifier.verify_result = AsyncMock(return_value="ok")

        result = await orchestrator.run_with_result(
            "여성스포츠의류 메뉴 클릭", mock_browser,
        )
        assert result.success is True
        # Fast followup creates a "fast_dom" outcome
        fast_outcomes = [o for o in result.step_results if o.method == "fast_dom"]
        assert len(fast_outcomes) == 1
        assert fast_outcomes[0].step_id == "여성스포츠의류"
        # VLM plan called: initial + post-completion after fast followup
        assert planner.plan.call_count == 2

    async def test_chained_hover_followup_navigates(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock, element_filter: MagicMock,
        extractor: AsyncMock, verifier: AsyncMock, executor: AsyncMock,
    ) -> None:
        """Chained followup: click submenu → click item → page navigates."""
        hover_step = _step(
            0, action_type="hover", desc="스포츠 카테고리 호버",
        )
        price_step = _step(0, desc="가격 필터")

        planner.plan = AsyncMock(side_effect=[
            [hover_step],  # initial plan: hover
            [price_step],  # after page nav: price filter
            [],            # post-completion: done
        ])

        # First followup: 여성스포츠의류 (URL same)
        # Second followup: 등산복 (URL changes)
        sub_node = DOMNode(
            node_id=2, tag="a", text="여성스포츠의류",
            attrs={"href": "/sports/women"},
        )
        item_node = DOMNode(
            node_id=3, tag="a", text="등산복",
            attrs={"href": "/sports/women/hiking"},
        )
        extract_calls = [0]

        async def mock_extract(browser: Browser) -> list:  # type: ignore[type-arg]
            extract_calls[0] += 1
            if extract_calls[0] <= 2:
                return [sub_node, item_node]
            return [DOMNode(node_id=4, tag="input", text="가격", attrs={"id": "price"})]

        extractor.extract = AsyncMock(side_effect=mock_extract)

        def mock_filter(nodes: list, kw: dict) -> list:  # type: ignore[type-arg]
            # Keyword-aware filter: match based on keywords, not call count
            if "여성스포츠의류" in kw:
                return [ScoredNode(node=sub_node, score=0.9)]
            if "등산복" in kw:
                return [ScoredNode(node=item_node, score=0.85)]
            # Pipeline calls (hover step uses default {"검색": 0.9})
            return [ScoredNode(
                node=DOMNode(node_id=4, tag="input", text="가격", attrs={"id": "price"}),
                score=0.8,
            )]

        element_filter.filter = MagicMock(side_effect=mock_filter)
        mock_browser._page.evaluate = AsyncMock(return_value={
            "cx": 0.3, "cy": 0.5,
        })

        # Second followup causes URL change
        exec_calls = [0]

        async def mock_exec(action: Action, browser: Browser) -> None:
            exec_calls[0] += 1
            # Call 1: hover execute (from _execute_step)
            # Call 2: first fast followup (여성스포츠의류)
            # Call 3: second fast followup (등산복) → URL changes
            if exec_calls[0] >= 3:
                mock_browser._page.url = "https://danawa.com/hiking"

        executor.execute_action = AsyncMock(side_effect=mock_exec)
        verifier.verify_result = AsyncMock(return_value="ok")

        result = await orchestrator.run_with_result(
            "여성스포츠의류 등산복 가격 필터", mock_browser,
        )
        assert result.success is True
        # 2 fast_dom outcomes (chained followups) + hover + price filter
        fast_outcomes = [o for o in result.step_results if o.method == "fast_dom"]
        assert len(fast_outcomes) == 2
        assert fast_outcomes[0].step_id == "여성스포츠의류"
        assert fast_outcomes[1].step_id == "등산복"

    async def test_hover_followup_falls_through_to_vlm(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock, element_filter: MagicMock,
    ) -> None:
        """If DOM can't find element after hover, fall through to VLM."""
        hover_step = _step(0, action_type="hover", desc="메뉴 호버")
        vlm_step = _step(0, desc="서브메뉴 클릭")

        planner.plan = AsyncMock(side_effect=[
            [hover_step],  # initial
            [vlm_step],    # VLM post-completion (fast followup failed)
            [],            # final post-completion
        ])

        # DOM returns low score — fast followup can't find target
        element_filter.filter = MagicMock(return_value=[_scored(0.1)])

        result = await orchestrator.run_with_result(
            "서브메뉴 찾기", mock_browser,
        )
        assert result.success is True
        # VLM plan called: initial + VLM post-completion + final
        assert planner.plan.call_count == 3

    async def test_non_hover_uses_vlm_for_post_completion(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock,
    ) -> None:
        """Non-hover last steps always use VLM for post-completion."""
        click_step = _step(0, desc="검색 버튼 클릭")  # default: click

        planner.plan = AsyncMock(side_effect=[
            [click_step],  # initial
            [],            # VLM post-completion
        ])

        result = await orchestrator.run_with_result("검색", mock_browser)
        assert result.success is True
        # VLM plan called: initial + post-completion (no fast followup)
        assert planner.plan.call_count == 2

    def test_extract_task_keywords(
        self, orchestrator: V3Orchestrator,
    ) -> None:
        """Task keyword extraction filters stop words, URLs, and completed parts."""
        keywords = orchestrator._extract_task_keywords(
            "danawa.com 에 가서 여성스포츠의류 메뉴안에 등산복",
            ["전체 카테고리 호버"],
        )
        assert "여성스포츠의류" in keywords
        assert "등산복" in keywords
        # URL/domain tokens filtered out
        assert "danawa.com" not in keywords
        # Stop words filtered out
        assert "에" not in keywords
        assert "가서" not in keywords
        # Earlier keywords get higher weight (navigation order)
        assert keywords["여성스포츠의류"] > keywords["등산복"]

    async def test_dead_link_hover_then_anchor_click(
        self, orchestrator: V3Orchestrator, mock_browser: Browser,
        planner: AsyncMock, element_filter: MagicMock,
        extractor: AsyncMock, verifier: AsyncMock, executor: AsyncMock,
    ) -> None:
        """Dead-link keyword is hovered (not clicked), next keyword
        uses anchor to pick the correct candidate."""
        hover_step = _step(
            0, action_type="hover", desc="스포츠 호버",
        )
        planner.plan = AsyncMock(side_effect=[
            [hover_step],
            [],  # post-nav
        ])

        # 여성스포츠의류: dead link (href="#"), node_id=10
        dead_node = DOMNode(
            node_id=10, tag="a", text="여성스포츠의류",
            attrs={"href": "#"},
        )
        # 등산복 under 남성 (node_id=5, before anchor)
        men_node = DOMNode(
            node_id=5, tag="a", text="등산복",
            attrs={"href": "/men/hiking"},
        )
        # 등산복 under 여성 (node_id=15, after anchor)
        women_node = DOMNode(
            node_id=15, tag="a", text="등산복",
            attrs={"href": "/women/hiking"},
        )

        extractor.extract = AsyncMock(
            return_value=[men_node, dead_node, women_node],
        )

        def mock_filter(
            nodes: list, kw: dict,  # type: ignore[type-arg]
        ) -> list:  # type: ignore[type-arg]
            if "여성스포츠의류" in kw:
                return [ScoredNode(node=dead_node, score=0.9)]
            if "등산복" in kw:
                # Both nodes match, men first (lower node_id)
                return [
                    ScoredNode(node=men_node, score=0.9),
                    ScoredNode(node=women_node, score=0.9),
                ]
            return [_scored(0.8)]

        element_filter.filter = MagicMock(side_effect=mock_filter)
        mock_browser._page.evaluate = AsyncMock(return_value={
            "cx": 0.3, "cy": 0.5,
        })
        verifier.verify_result = AsyncMock(return_value="ok")

        # URL changes when women's hiking is clicked
        exec_calls = [0]

        async def mock_exec(
            action: Action, browser: Browser,
        ) -> None:
            exec_calls[0] += 1
            if exec_calls[0] >= 2:
                mock_browser._page.url = (
                    "https://example.com/women/hiking"
                )

        executor.execute_action = AsyncMock(
            side_effect=mock_exec,
        )

        result = await orchestrator.run_with_result(
            "여성스포츠의류 등산복", mock_browser,
        )
        assert result.success is True
        fast = [
            o for o in result.step_results
            if o.method == "fast_dom"
        ]
        # Only 등산복 should be fast_dom (여성스포츠의류 was hovered)
        assert len(fast) == 1
        assert fast[0].step_id == "등산복"

    def test_extract_keywords_first_is_navigation_target(
        self, orchestrator: V3Orchestrator,
    ) -> None:
        """First keyword should be the navigation target, not the URL."""
        task = (
            "danawa.com 에 가서 여성스포츠의류 메뉴안에"
            " 등산복 중에서 10만원 이하의 붉은색 옷을 찾아줘"
        )
        keywords = orchestrator._extract_task_keywords(task, [])
        first_kw = next(iter(keywords))
        assert first_kw == "여성스포츠의류"
        assert "danawa.com" not in keywords


class TestDedupSteps:
    def test_exact_match_removed(self) -> None:
        steps = [_step(desc="가격 필터 적용"), _step(desc="색상 선택")]
        completed = ["가격 필터 적용"]
        result = V3Orchestrator._dedup_steps(steps, completed)
        assert len(result) == 1
        assert result[0].target_description == "색상 선택"

    def test_substring_match_removed(self) -> None:
        steps = [_step(desc="가격대 필터의 검색 버튼")]
        completed = ["가격대 필터의 검색 버튼 클릭"]
        result = V3Orchestrator._dedup_steps(steps, completed)
        assert len(result) == 0

    def test_no_overlap_keeps_all(self) -> None:
        steps = [_step(desc="색상 선택"), _step(desc="상품 클릭")]
        completed = ["메뉴 호버"]
        result = V3Orchestrator._dedup_steps(steps, completed)
        assert len(result) == 2

    def test_empty_completed(self) -> None:
        steps = [_step(desc="색상 선택")]
        result = V3Orchestrator._dedup_steps(steps, [])
        assert len(result) == 1


class TestGetDomain:
    def test_extracts_domain(self, orchestrator: V3Orchestrator) -> None:
        assert orchestrator._get_domain("https://shop.naver.com/search") == "shop.naver.com"

    def test_empty_url(self, orchestrator: V3Orchestrator) -> None:
        assert orchestrator._get_domain("") == ""

    def test_invalid_url(self, orchestrator: V3Orchestrator) -> None:
        assert orchestrator._get_domain("not-a-url") == ""
