"""Tests for codegen DSL quality — intent-aware + menu navigation first.

Validates that:
- Intent is passed through the pipeline to LLM prompts
- Nav context (menu_items, category_tree, interaction_patterns) is included
- evaluate action works in the executor
- Orchestrator forwards intent to codegen
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.codegen.agent import CodeGenAgent
from src.codegen.dsl_generator import DSLGenerator
from src.codegen.prompt_generator import PromptGenerator
from src.models.bundle import StrategyAssignment
from src.models.site_profile import (
    CanvasUsage,
    CategoryNode,
    ContentPattern,
    DOMComplexity,
    FormPattern,
    InteractionPattern,
    ListStructure,
    NavigationStructure,
    SearchConfig,
    SiteProfile,
)
from src.runtime.executor import _VALID_ACTIONS, BundleExecutor

# ── Helpers ──


class FakeLLMRouter:
    """Fake LLM router that captures calls."""

    def __init__(self, response: str = "{}") -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self, alias: str, messages: list[dict[str, Any]], **kwargs: Any,
    ) -> str:
        self.calls.append({"alias": alias, "messages": messages})
        return self._response


class FakeKBManager:
    """Minimal KB stub."""

    def save_pattern_meta(self, *a: Any) -> None: ...
    def save_workflow(self, *a: Any) -> None: ...
    def save_prompts(self, *a: Any) -> None: ...
    def save_macro(self, *a: Any, **kw: Any) -> None: ...


def _make_profile(
    *,
    domain: str = "shop.example.com",
    menu_items: list[dict[str, Any]] | None = None,
    category_tree: list[CategoryNode] | None = None,
    interaction_patterns: list[InteractionPattern] | None = None,
    form_types: list[FormPattern] | None = None,
    list_structures: list[ListStructure] | None = None,
    search_functionality: SearchConfig | None = None,
    navigation: NavigationStructure | None = None,
) -> SiteProfile:
    nav = navigation or NavigationStructure(
        menu_depth=2,
        menu_items=menu_items or [],
        menu_requires_hover=True,
        has_search=True,
    )
    return SiteProfile(
        domain=domain,
        purpose="ecommerce",
        dom_complexity=DOMComplexity(
            total_elements=800, interactive_elements=60,
            max_depth=12, text_node_ratio=0.4, aria_coverage=0.3,
        ),
        canvas_usage=CanvasUsage(),
        image_density="medium",
        content_types=[
            ContentPattern(page_type="home", url_pattern="/", dom_readable=True),
        ],
        navigation=nav,
        search_functionality=search_functionality,
        category_tree=category_tree or [],
        interaction_patterns=interaction_patterns or [],
        form_types=form_types or [],
        list_structures=list_structures or [],
    )


# ═══════════════════════════════════════════════════════════
# 1. Intent passed to LLM
# ═══════════════════════════════════════════════════════════


class TestIntentPassthrough:

    @pytest.mark.asyncio
    async def test_intent_passed_to_llm(self) -> None:
        """Intent string appears in the LLM user message."""
        llm = FakeLLMRouter(response=json.dumps({
            "domain": "shop.example.com", "strategy": "dom_only",
            "task_type": "search", "steps": [{"action": "goto"}],
        }))
        gen = DSLGenerator()
        profile = _make_profile()
        assignments = [
            StrategyAssignment(page_type="home", url_pattern="/", strategy="dom_only"),
        ]

        await gen.generate(profile, assignments, "search", llm, intent="스포츠의류 카테고리로 이동")

        user_msg = llm.calls[0]["messages"][1]["content"]
        assert "스포츠의류 카테고리로 이동" in user_msg
        assert "## User Task" in user_msg

    @pytest.mark.asyncio
    async def test_no_intent_omits_section(self) -> None:
        """Without intent, no User Task section in the message."""
        llm = FakeLLMRouter(response="{}")
        gen = DSLGenerator()
        profile = _make_profile()
        assignments = [
            StrategyAssignment(page_type="home", url_pattern="/", strategy="dom_only"),
        ]

        await gen.generate(profile, assignments, "search", llm)

        user_msg = llm.calls[0]["messages"][1]["content"]
        assert "## User Task" not in user_msg


# ═══════════════════════════════════════════════════════════
# 2. Nav context includes menu_items
# ═══════════════════════════════════════════════════════════


class TestNavContext:

    def test_nav_context_includes_menu_items(self) -> None:
        """menu_items appear in profile_summary."""
        profile = _make_profile(menu_items=[
            {"name": "스포츠·레저", "selector": "#gnb > li:nth-child(3)", "requires_hover": True},
            {"name": "디지털·가전", "selector": "#gnb > li:nth-child(1)", "requires_hover": True},
        ])
        assignments = [
            StrategyAssignment(page_type="home", url_pattern="/", strategy="dom_only"),
        ]

        ctx = DSLGenerator._build_context(profile, assignments)

        assert "Menu items:" in ctx["profile_summary"]
        assert "스포츠·레저" in ctx["profile_summary"]
        assert "#gnb > li:nth-child(3)" in ctx["profile_summary"]
        assert "requires_hover=True" in ctx["profile_summary"]

    def test_nav_context_includes_category_tree(self) -> None:
        """category_tree nodes appear in profile_summary."""
        profile = _make_profile(category_tree=[
            CategoryNode(name="스포츠", selector=".cat-sport", depth=0),
            CategoryNode(name="여성스포츠의류", selector=".cat-women", depth=1),
        ])
        assignments = [
            StrategyAssignment(page_type="home", url_pattern="/", strategy="dom_only"),
        ]

        ctx = DSLGenerator._build_context(profile, assignments)

        assert "Category tree:" in ctx["profile_summary"]
        assert "스포츠" in ctx["profile_summary"]
        assert ".cat-sport" in ctx["profile_summary"]
        assert "여성스포츠의류" in ctx["profile_summary"]
        assert "depth=1" in ctx["profile_summary"]

    def test_nav_context_includes_interaction_patterns(self) -> None:
        """hover_menu interaction patterns appear in profile_summary."""
        profile = _make_profile(interaction_patterns=[
            InteractionPattern(
                type="hover_menu",
                selector="#gnb-menu",
                recommended_action_type="hover",
            ),
        ])
        assignments = [
            StrategyAssignment(page_type="home", url_pattern="/", strategy="dom_only"),
        ]

        ctx = DSLGenerator._build_context(profile, assignments)

        assert "Hover menu patterns:" in ctx["profile_summary"]
        assert "#gnb-menu" in ctx["profile_summary"]

    def test_nav_context_includes_filter_selectors(self) -> None:
        """filter_selectors from list_structures appear in profile_summary."""
        profile = _make_profile(list_structures=[
            ListStructure(
                url_pattern="/category/*",
                item_selector=".product-item",
                filter_selectors={"color": ".filter-color", "price": ".filter-price"},
            ),
        ])
        assignments = [
            StrategyAssignment(page_type="home", url_pattern="/", strategy="dom_only"),
        ]

        ctx = DSLGenerator._build_context(profile, assignments)

        assert "Filter selectors:" in ctx["profile_summary"]
        assert ".filter-color" in ctx["profile_summary"]
        assert ".filter-price" in ctx["profile_summary"]

    def test_empty_nav_data_no_crash(self) -> None:
        """Empty nav data produces no crash and omits optional sections."""
        profile = _make_profile()
        assignments = [
            StrategyAssignment(page_type="home", url_pattern="/", strategy="dom_only"),
        ]

        ctx = DSLGenerator._build_context(profile, assignments)

        assert "Menu items:" not in ctx["profile_summary"]
        assert "Category tree:" not in ctx["profile_summary"]
        assert "Hover menu patterns:" not in ctx["profile_summary"]


# ═══════════════════════════════════════════════════════════
# 3. evaluate action in executor
# ═══════════════════════════════════════════════════════════


class TestEvaluateAction:

    def test_evaluate_in_valid_actions(self) -> None:
        """evaluate is listed in _VALID_ACTIONS."""
        assert "evaluate" in _VALID_ACTIONS

    @pytest.mark.asyncio
    async def test_evaluate_action_accepted(self) -> None:
        """Executor runs evaluate step via page.evaluate()."""
        from src.models.bundle import GeneratedBundle

        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "test.com",
                "strategy": "dom_only",
                "task_type": "search",
                "steps": [
                    {"action": "evaluate", "value": "document.title"},
                ],
            },
        )

        page = AsyncMock()
        page.url = "https://test.com"
        browser = AsyncMock()
        browser.get_page.return_value = page

        executor = BundleExecutor()
        result = await executor.execute(bundle, browser, "test task")

        assert result.success is True
        assert result.steps_completed == 1
        page.evaluate.assert_called_once_with("document.title")

    @pytest.mark.asyncio
    async def test_evaluate_uses_selector_as_fallback(self) -> None:
        """When value is empty, evaluate uses selector as expression."""
        from src.models.bundle import GeneratedBundle

        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "test.com",
                "strategy": "dom_only",
                "task_type": "search",
                "steps": [
                    {"action": "evaluate", "selector": "window.scrollTo(0, 0)"},
                ],
            },
        )

        page = AsyncMock()
        page.url = "https://test.com"
        browser = AsyncMock()
        browser.get_page.return_value = page

        executor = BundleExecutor()
        result = await executor.execute(bundle, browser, "scroll test")

        assert result.success is True
        page.evaluate.assert_called_once_with("window.scrollTo(0, 0)")


# ═══════════════════════════════════════════════════════════
# 4. PromptGenerator includes intent
# ═══════════════════════════════════════════════════════════


class TestPromptGeneratorIntent:

    def test_prompt_generator_includes_intent(self) -> None:
        """Navigate prompt includes task_description when intent is provided."""
        gen = PromptGenerator()
        profile = _make_profile()

        result = gen.generate(profile, "search", "dom_only", intent="등산복 찾기")

        assert "task_description: 등산복 찾기" in result["navigate"]

    def test_prompt_generator_no_intent(self) -> None:
        """Navigate prompt omits task_description when intent is empty."""
        gen = PromptGenerator()
        profile = _make_profile()

        result = gen.generate(profile, "search", "dom_only")

        assert "task_description:" not in result["navigate"]


# ═══════════════════════════════════════════════════════════
# 5. CodeGenAgent passes intent
# ═══════════════════════════════════════════════════════════


class TestCodeGenAgentIntent:

    @pytest.mark.asyncio
    async def test_agent_passes_intent_to_dsl_and_prompt(self) -> None:
        """CodeGenAgent.generate_bundle() forwards intent to sub-generators."""
        llm = FakeLLMRouter(response=json.dumps({
            "domain": "shop.example.com", "strategy": "dom_only",
            "task_type": "search",
            "steps": [{"action": "click", "selector": ".btn"}],
        }))
        kb = FakeKBManager()
        profile = _make_profile(
            domain="shop.example.com",
        )

        agent = CodeGenAgent()
        bundle = await agent.generate_bundle(
            "shop.example.com", profile, "search", kb, llm,
            intent="스포츠의류 카테고리에서 등산복 검색",
        )

        # Verify intent reached the LLM via DSL generator
        user_msg = llm.calls[0]["messages"][1]["content"]
        assert "스포츠의류 카테고리에서 등산복 검색" in user_msg

        # Verify intent reached the prompt generator (navigate prompt)
        assert "task_description: 스포츠의류 카테고리에서 등산복 검색" in bundle.prompts["navigate"]


# ═══════════════════════════════════════════════════════════
# 6. System prompt includes menu nav guide
# ═══════════════════════════════════════════════════════════


class TestSystemPromptNavGuide:

    def test_system_prompt_includes_menu_navigation_guide(self) -> None:
        """System prompt mentions hover→wait→click and step ordering."""
        profile = _make_profile()
        prompt = DSLGenerator._system_prompt(profile)

        assert "hover" in prompt.lower()
        assert "wait(500ms)" in prompt
        assert "navigation first" in prompt
        assert "menu_items" in prompt

    def test_user_rules_include_menu_navigation(self) -> None:
        """User message rules include rules 7-10 for menu navigation."""
        import inspect

        gen = DSLGenerator()
        source = inspect.getsource(gen.generate)
        assert "hover→wait→click" in source
        assert "menu_depth>=2" in source
        assert "navigation → filters → search" in source
        assert "category_tree" in source


# ═══════════════════════════════════════════════════════════
# 7. text_match fallback in executor
# ═══════════════════════════════════════════════════════════


class TestTextMatchFallback:

    @pytest.mark.asyncio
    async def test_text_match_resolves_when_css_fails(self) -> None:
        """CSS selector fails → text_match Playwright text selector succeeds."""
        from src.models.bundle import GeneratedBundle

        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "test.com",
                "strategy": "dom_only",
                "task_type": "search",
                "steps": [
                    {
                        "action": "click",
                        "selector": "#nonexistent",
                        "fallback_selectors": [],
                        "text_match": "스포츠·레저",
                        "timeout_ms": 1000,
                    },
                ],
            },
        )

        page = AsyncMock()
        page.url = "https://test.com"
        # CSS selector fails, text selector succeeds
        async def mock_query(sel: str) -> Any:
            if sel.startswith("text="):
                return AsyncMock()  # found
            return None  # CSS not found
        page.query_selector.side_effect = mock_query

        browser = AsyncMock()
        browser.get_page.return_value = page

        executor = BundleExecutor()
        result = await executor.execute(bundle, browser, "nav task")

        assert result.success is True
        assert result.steps_completed == 1
        page.click.assert_called_once()
        # Clicked with text selector
        click_sel = page.click.call_args[0][0]
        assert 'text="스포츠·레저"' in click_sel

    @pytest.mark.asyncio
    async def test_text_match_link_fallback(self) -> None:
        """a:has-text() fallback works when text= fails."""
        from src.models.bundle import GeneratedBundle

        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "test.com",
                "strategy": "dom_only",
                "task_type": "search",
                "steps": [
                    {
                        "action": "hover",
                        "selector": "#bad",
                        "fallback_selectors": [],
                        "text_match": "여성스포츠의류",
                        "timeout_ms": 1000,
                    },
                ],
            },
        )

        page = AsyncMock()
        page.url = "https://test.com"

        call_count = 0

        async def mock_query(sel: str) -> Any:
            nonlocal call_count
            call_count += 1
            # CSS fails, text= fails, a:has-text succeeds
            if sel.startswith('a:has-text'):
                return AsyncMock()
            return None
        page.query_selector.side_effect = mock_query

        browser = AsyncMock()
        browser.get_page.return_value = page

        executor = BundleExecutor()
        result = await executor.execute(bundle, browser, "hover task")

        assert result.success is True
        hover_sel = page.hover.call_args[0][0]
        assert 'a:has-text("여성스포츠의류")' in hover_sel

    @pytest.mark.asyncio
    async def test_text_match_empty_skipped(self) -> None:
        """Empty text_match does not add text selectors to candidates."""
        from src.models.bundle import GeneratedBundle

        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "test.com",
                "strategy": "dom_only",
                "task_type": "search",
                "steps": [
                    {
                        "action": "click",
                        "selector": ".btn-ok",
                        "fallback_selectors": [],
                        "text_match": "",
                        "timeout_ms": 1000,
                    },
                ],
            },
        )

        page = AsyncMock()
        page.url = "https://test.com"
        page.query_selector.return_value = AsyncMock()  # CSS found

        browser = AsyncMock()
        browser.get_page.return_value = page

        executor = BundleExecutor()
        result = await executor.execute(bundle, browser, "click task")

        assert result.success is True
        page.click.assert_called_once()
        click_sel = page.click.call_args[0][0]
        assert click_sel == ".btn-ok"

    @pytest.mark.asyncio
    async def test_text_match_wait_for_selector(self) -> None:
        """text_match falls back to wait_for_selector when query_selector fails."""
        from src.models.bundle import GeneratedBundle

        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "test.com",
                "strategy": "dom_only",
                "task_type": "search",
                "steps": [
                    {
                        "action": "click",
                        "selector": "#gone",
                        "fallback_selectors": [],
                        "text_match": "등산복",
                        "timeout_ms": 2000,
                    },
                ],
            },
        )

        page = AsyncMock()
        page.url = "https://test.com"
        # All query_selector calls return None
        page.query_selector.return_value = None
        # wait_for_selector succeeds for text selector
        page.wait_for_selector.return_value = AsyncMock()

        browser = AsyncMock()
        browser.get_page.return_value = page

        executor = BundleExecutor()
        result = await executor.execute(bundle, browser, "wait task")

        assert result.success is True
        # Should have called wait_for_selector with text selector
        wait_calls = [
            call for call in page.wait_for_selector.call_args_list
            if 'text="등산복"' in str(call)
        ]
        assert len(wait_calls) >= 1


# ═══════════════════════════════════════════════════════════
# 7b. fill action uses input-specific resolution (not text labels)
# ═══════════════════════════════════════════════════════════


class TestFillInputResolution:

    @pytest.mark.asyncio
    async def test_fill_resolves_to_input_not_label(self) -> None:
        """fill action with text_match finds <input> by placeholder, not text label."""
        from src.models.bundle import GeneratedBundle

        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "test.com",
                "strategy": "dom_only",
                "task_type": "search",
                "steps": [
                    {
                        "action": "fill",
                        "selector": "#nonexistent-price",
                        "fallback_selectors": [],
                        "text_match": "가격",
                        "value": "100000",
                        "timeout_ms": 1000,
                    },
                ],
            },
        )

        page = AsyncMock()
        page.url = "https://test.com"

        async def mock_query(sel: str) -> Any:
            # CSS primary fails; placeholder-based input selector succeeds
            if 'placeholder' in sel and '가격' in sel:
                return AsyncMock()
            return None
        page.query_selector.side_effect = mock_query

        browser = AsyncMock()
        browser.get_page.return_value = page

        executor = BundleExecutor()
        result = await executor.execute(bundle, browser, "price fill")

        assert result.success is True
        fill_sel = page.fill.call_args[0][0]
        assert "placeholder" in fill_sel
        assert "가격" in fill_sel

    @pytest.mark.asyncio
    async def test_fill_js_fallback_finds_input_near_label(self) -> None:
        """fill action JS fallback finds input near matching text label."""
        from src.models.bundle import GeneratedBundle

        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "test.com",
                "strategy": "dom_only",
                "task_type": "search",
                "steps": [
                    {
                        "action": "fill",
                        "selector": "#bad",
                        "fallback_selectors": [],
                        "text_match": "최대가격",
                        "value": "100000",
                        "timeout_ms": 1000,
                    },
                ],
            },
        )

        page = AsyncMock()
        page.url = "https://test.com"

        query_count = 0

        async def mock_query(sel: str) -> Any:
            nonlocal query_count
            query_count += 1
            # CSS/placeholder fail; JS-returned selector succeeds
            if sel == '#priceMax':
                return AsyncMock()
            return None
        page.query_selector.side_effect = mock_query
        # JS evaluate returns the input selector found near "최대가격" label
        page.evaluate.return_value = "#priceMax"

        browser = AsyncMock()
        browser.get_page.return_value = page

        executor = BundleExecutor()
        result = await executor.execute(bundle, browser, "price fill js")

        assert result.success is True
        fill_sel = page.fill.call_args[0][0]
        assert fill_sel == "#priceMax"

    @pytest.mark.asyncio
    async def test_fill_does_not_use_text_selector(self) -> None:
        """fill action NEVER resolves to text= selector (would match labels)."""
        from src.models.bundle import GeneratedBundle

        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "test.com",
                "strategy": "dom_only",
                "task_type": "search",
                "steps": [
                    {
                        "action": "fill",
                        "selector": "#bad",
                        "fallback_selectors": [],
                        "text_match": "가격",
                        "value": "100000",
                        "timeout_ms": 1000,
                    },
                ],
            },
        )

        page = AsyncMock()
        page.url = "https://test.com"
        # All resolution fails
        page.query_selector.return_value = None
        page.evaluate.return_value = None
        page.wait_for_selector.side_effect = Exception("timeout")

        browser = AsyncMock()
        browser.get_page.return_value = page

        executor = BundleExecutor()
        result = await executor.execute(bundle, browser, "fill fail test")

        # Should fail, NOT succeed with text= selector
        assert result.success is False
        # Verify no text= selector was used for fill
        for call in page.fill.call_args_list:
            assert 'text=' not in str(call)


# ═══════════════════════════════════════════════════════════
# 8. DSL generator text_match rules
# ═══════════════════════════════════════════════════════════


class TestDSLGeneratorTextMatch:

    @pytest.mark.asyncio
    async def test_rules_mention_text_match(self) -> None:
        """User message rules include text_match rule."""
        llm = FakeLLMRouter(response=json.dumps({
            "domain": "shop.example.com", "strategy": "dom_only",
            "task_type": "search", "steps": [],
        }))
        gen = DSLGenerator()
        profile = _make_profile()
        assignments = [
            StrategyAssignment(page_type="home", url_pattern="/", strategy="dom_only"),
        ]

        await gen.generate(profile, assignments, "search", llm)

        user_msg = llm.calls[0]["messages"][1]["content"]
        assert "text_match" in user_msg
        assert "visible text label" in user_msg

    def test_system_prompt_mentions_text_match(self) -> None:
        """System prompt includes text_match guidance."""
        profile = _make_profile()
        prompt = DSLGenerator._system_prompt(profile)

        assert "text_match" in prompt
        assert "fallback when CSS selectors fail" in prompt


# ═══════════════════════════════════════════════════════════
# 9. Orchestrator intent-specific regeneration
# ═══════════════════════════════════════════════════════════


class TestOrchestratorIntentRegeneration:

    @pytest.mark.asyncio
    async def test_regenerates_dsl_when_intent_provided(self) -> None:
        """When intent is provided and KB has a hit, codegen is re-run."""
        from unittest.mock import MagicMock, patch

        # Fake KB that returns a hit with profile
        fake_profile = _make_profile(domain="shop.example.com")
        kb = MagicMock()
        lookup_result = MagicMock()
        lookup_result.hit = True
        lookup_result.profile = fake_profile
        kb.lookup.return_value = lookup_result

        # Codegen spy
        codegen = AsyncMock()

        # Runtime returns success
        runtime_result = MagicMock()
        runtime_result.success = True
        runtime_result.llm_calls = 0
        runtime_result.failure_evidence = None
        runtime = AsyncMock()
        runtime.run.return_value = runtime_result

        # Browser adapter
        browser = AsyncMock()
        page = AsyncMock()
        page.url = "https://shop.example.com/category"
        browser.get_page.return_value = page

        # Build orchestrator
        from src.core.v4_orchestrator import V4Orchestrator

        orch = V4Orchestrator(
            kb=kb,
            llm=MagicMock(),
            maturity_tracker=MagicMock(),
            change_detector=AsyncMock(),
            codegen=codegen,
            runtime=runtime,
            failure_analyzer=AsyncMock(),
            improver=AsyncMock(),
        )

        with patch.object(orch, "_run_codegen", new_callable=AsyncMock) as mock_cg:
            await orch.run(
                "스포츠의류 카테고리로 이동",
                browser,
                task_type="navigation",
                skip_change_detect=True,
            )

            # codegen was called with the intent
            assert mock_cg.called
            call_kwargs = mock_cg.call_args
            assert "스포츠의류 카테고리로 이동" in str(call_kwargs)
