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
