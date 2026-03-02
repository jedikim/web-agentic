"""Unit tests for v4 CodeGen phase modules.

Covers StrategyDecider, DSLGenerator, PromptGenerator, CodeValidator,
and CodeGenAgent.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.codegen.dsl_generator import DSLGenerator
from src.codegen.prompt_generator import PromptGenerator
from src.codegen.strategy_decider import _TOOL_MAP, STRATEGIES, StrategyDecider
from src.codegen.validator import CodeValidator
from src.models.bundle import GeneratedBundle, StrategyAssignment, ValidationResult
from src.models.site_profile import (
    CanvasUsage,
    ContentPattern,
    DOMComplexity,
    NavigationStructure,
    ObstaclePattern,
    SearchConfig,
    SiteProfile,
    ThumbnailGrid,
)

# ── Mock / Fake objects ──


class FakeLLMRouter:
    """Fake LLM router that returns pre-configured responses."""

    def __init__(self, response: str = "{}") -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        alias: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 4000,
        temperature: float = 0.1,
        **kwargs: Any,
    ) -> str:
        self.calls.append({
            "alias": alias,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        return self._response


class FakeKBManager:
    """Fake KBManager that records save calls."""

    def __init__(self) -> None:
        self.saved_pattern_meta: list[tuple[str, str, str]] = []
        self.saved_workflows: list[tuple[str, str, dict[str, Any]]] = []
        self.saved_prompts: list[tuple[str, str, dict[str, str]]] = []
        self.saved_macros: list[tuple[str, str, str]] = []

    def save_pattern_meta(
        self, domain: str, url_pattern: str, page_type: str
    ) -> None:
        self.saved_pattern_meta.append((domain, url_pattern, page_type))

    def save_workflow(
        self, domain: str, url_pattern: str, dsl: dict[str, Any]
    ) -> None:
        self.saved_workflows.append((domain, url_pattern, dsl))

    def save_prompts(
        self, domain: str, url_pattern: str, prompts: dict[str, str]
    ) -> None:
        self.saved_prompts.append((domain, url_pattern, prompts))

    def save_macro(
        self, domain: str, url_pattern: str, *, python_code: str
    ) -> None:
        self.saved_macros.append((domain, url_pattern, python_code))


class FailingKBManager(FakeKBManager):
    """KBManager that raises on save_pattern_meta."""

    def save_pattern_meta(
        self, domain: str, url_pattern: str, page_type: str
    ) -> None:
        raise RuntimeError("KB write failure")


def _make_profile(
    *,
    domain: str = "example.com",
    purpose: str = "ecommerce",
    text_node_ratio: float = 0.4,
    aria_coverage: float = 0.3,
    canvas_vision_only: bool = False,
    canvas_has: bool = False,
    image_density: str = "low",
    content_types: list[ContentPattern] | None = None,
    thumbnail_structures: list[ThumbnailGrid] | None = None,
    obstacles: list[ObstaclePattern] | None = None,
    framework: str | None = None,
    is_spa: bool = False,
    navigation: NavigationStructure | None = None,
    search_functionality: SearchConfig | None = None,
) -> SiteProfile:
    """Helper to build a SiteProfile with common overrides."""
    return SiteProfile(
        domain=domain,
        purpose=purpose,
        dom_complexity=DOMComplexity(
            total_elements=500,
            interactive_elements=40,
            max_depth=10,
            text_node_ratio=text_node_ratio,
            aria_coverage=aria_coverage,
        ),
        canvas_usage=CanvasUsage(
            has_canvas=canvas_has or canvas_vision_only,
            requires_vision_only=canvas_vision_only,
        ),
        image_density=image_density,
        content_types=content_types or [],
        thumbnail_structures=thumbnail_structures or [],
        obstacles=obstacles or [],
        framework=framework,
        is_spa=is_spa,
        navigation=navigation or NavigationStructure(),
        search_functionality=search_functionality,
    )


# ═══════════════════════════════════════════════════════════
# StrategyDecider Tests
# ═══════════════════════════════════════════════════════════


class TestStrategyDecider:
    """Tests for StrategyDecider.decide()."""

    def setup_method(self) -> None:
        self.decider = StrategyDecider()

    def test_empty_content_types_returns_default(self) -> None:
        """No content_types -> single 'default' assignment with url_pattern '/'."""
        profile = _make_profile(content_types=[])
        result = self.decider.decide(profile, "search")

        assert len(result) == 1
        assert result[0].page_type == "default"
        assert result[0].url_pattern == "/"
        assert result[0].strategy in STRATEGIES
        assert len(result[0].tools_needed) > 0

    def test_dom_readable_content_gets_dom_only(self) -> None:
        """DOM-readable content with high text_node_ratio and aria -> dom_only."""
        content = ContentPattern(
            page_type="home",
            url_pattern="/",
            dom_readable=True,
        )
        profile = _make_profile(
            content_types=[content],
            text_node_ratio=0.5,
            aria_coverage=0.4,
        )
        result = self.decider.decide(profile, "search")

        assert len(result) == 1
        assert result[0].page_type == "home"
        # dom_only gets +1.5 from dom_readable heuristic
        assert result[0].strategy == "dom_only"

    def test_canvas_vision_only_gets_vlm_only(self) -> None:
        """Canvas with requires_vision_only -> vlm_only strategy."""
        content = ContentPattern(page_type="canvas_app", url_pattern="/app")
        profile = _make_profile(
            content_types=[content],
            canvas_vision_only=True,
            text_node_ratio=0.1,
            aria_coverage=0.05,
        )
        result = self.decider.decide(profile, "navigate")

        assert len(result) == 1
        # vlm_only gets +2.0 from canvas_vision_only + 0.4 from has_canvas
        assert result[0].strategy == "vlm_only"

    def test_thumbnail_grid_with_text_gets_objdet_backup(self) -> None:
        """Thumbnail grid with card_has_text -> dom_with_objdet_backup boost."""
        content = ContentPattern(
            page_type="product_list",
            url_pattern="/products",
            dom_readable=True,
        )
        thumb = ThumbnailGrid(
            page_url_pattern="/products",
            card_has_text=True,
        )
        profile = _make_profile(
            content_types=[content],
            thumbnail_structures=[thumb],
            text_node_ratio=0.5,
            aria_coverage=0.3,
        )
        result = self.decider.decide(profile, "search")

        assert len(result) == 1
        # dom_only gets 1.5, dom_with_objdet_backup gets 0.5 + 1.0 = 1.5
        # With equal base scores the perf_bonus (identical) decides, so
        # either dom_only or dom_with_objdet_backup wins depending on dict order
        assert result[0].strategy in ("dom_only", "dom_with_objdet_backup")

    def test_thumbnail_grid_no_text_gets_grid_vlm(self) -> None:
        """Thumbnail grid without text (images only) -> grid_vlm boost."""
        content = ContentPattern(
            page_type="gallery",
            url_pattern="/gallery",
            dom_readable=False,
        )
        thumb = ThumbnailGrid(
            page_url_pattern="/gallery",
            card_has_text=False,
        )
        profile = _make_profile(
            content_types=[content],
            thumbnail_structures=[thumb],
            text_node_ratio=0.1,
            aria_coverage=0.05,
        )
        result = self.decider.decide(profile, "browse")

        assert len(result) == 1
        # grid_vlm gets +1.2 from thumbnail without text
        assert result[0].strategy == "grid_vlm"

    def test_runtime_stats_performance_bonus(self) -> None:
        """Runtime stats can override base heuristic scores."""
        content = ContentPattern(
            page_type="home",
            url_pattern="/",
            dom_readable=True,
        )
        profile = _make_profile(
            content_types=[content],
            text_node_ratio=0.5,
            aria_coverage=0.4,
        )
        # Give vlm_only very good runtime stats
        runtime_stats = {
            "vlm_only": {
                "success_rate": 0.99,
                "avg_cost": 0.001,
                "p95_latency_ms": 500,
            },
            "dom_only": {
                "success_rate": 0.2,
                "avg_cost": 0.01,
                "p95_latency_ms": 10000,
            },
        }
        result = self.decider.decide(profile, "search", runtime_stats)

        assert len(result) == 1
        # vlm_only should win due to massive runtime performance advantage
        assert result[0].strategy == "vlm_only"

    def test_required_tools_returns_correct_tools(self) -> None:
        """_required_tools maps strategies to correct tool lists."""
        for strategy, expected_tools in _TOOL_MAP.items():
            tools = StrategyDecider._required_tools(strategy)
            assert tools == expected_tools
            # Ensure it returns a copy, not the original list
            assert tools is not _TOOL_MAP[strategy]

    def test_required_tools_unknown_strategy_fallback(self) -> None:
        """Unknown strategy returns default ['playwright', 'cdp']."""
        tools = StrategyDecider._required_tools("nonexistent_strategy")
        assert tools == ["playwright", "cdp"]

    def test_multiple_content_types_produce_multiple_assignments(self) -> None:
        """Each content_type produces one StrategyAssignment."""
        contents = [
            ContentPattern(page_type="home", url_pattern="/", dom_readable=True),
            ContentPattern(page_type="gallery", url_pattern="/gallery", dom_readable=False),
            ContentPattern(page_type="detail", url_pattern="/product/*", dom_readable=True),
        ]
        profile = _make_profile(
            content_types=contents,
            text_node_ratio=0.5,
            aria_coverage=0.4,
        )
        result = self.decider.decide(profile, "purchase")

        assert len(result) == 3
        page_types = [a.page_type for a in result]
        assert "home" in page_types
        assert "gallery" in page_types
        assert "detail" in page_types
        # Each should have a valid strategy and tools
        for assignment in result:
            assert assignment.strategy in STRATEGIES
            assert len(assignment.tools_needed) > 0

    def test_high_image_density_boosts_hybrid(self) -> None:
        """High image_density gives bonus to objdet_dom_hybrid and grid_vlm."""
        content = ContentPattern(
            page_type="media",
            url_pattern="/media",
            dom_readable=False,
        )
        profile = _make_profile(
            content_types=[content],
            image_density="high",
            text_node_ratio=0.1,
            aria_coverage=0.05,
        )
        result = self.decider.decide(profile, "browse")

        assert len(result) == 1
        # objdet_dom_hybrid gets +0.8, grid_vlm gets +0.4 from high image density
        assert result[0].strategy in ("objdet_dom_hybrid", "grid_vlm")


# ═══════════════════════════════════════════════════════════
# DSLGenerator Tests
# ═══════════════════════════════════════════════════════════


class TestDSLGenerator:
    """Tests for DSLGenerator.generate()."""

    def setup_method(self) -> None:
        self.generator = DSLGenerator()

    @pytest.mark.asyncio
    async def test_generate_valid_json_from_llm(self) -> None:
        """LLM returns valid JSON -> parsed into DSL dict."""
        dsl_json = json.dumps({
            "domain": "shop.com",
            "strategy": "dom_only",
            "task_type": "search",
            "steps": [
                {"action": "goto", "selector": None, "verify": "url_changed"},
                {"action": "fill", "selector": "#search", "value": "shoes", "verify": "value_set"},
            ],
        })
        llm = FakeLLMRouter(response=dsl_json)
        profile = _make_profile(domain="shop.com")
        assignments = [
            StrategyAssignment(page_type="home", url_pattern="/", strategy="dom_only"),
        ]

        result = await self.generator.generate(profile, assignments, "search", llm)

        assert result["domain"] == "shop.com"
        assert result["strategy"] == "dom_only"
        assert result["task_type"] == "search"
        assert len(result["steps"]) == 2
        assert result["steps"][0]["action"] == "goto"
        assert llm.calls[0]["alias"] == "fast"

    @pytest.mark.asyncio
    async def test_generate_invalid_json_wraps_raw(self) -> None:
        """LLM returns non-JSON -> wrapped in fallback DSL with _raw key."""
        llm = FakeLLMRouter(response="This is not valid JSON at all!!!")
        profile = _make_profile(domain="broken.com")
        assignments = [
            StrategyAssignment(page_type="home", url_pattern="/", strategy="vlm_only"),
        ]

        result = await self.generator.generate(profile, assignments, "navigate", llm)

        assert result["domain"] == "broken.com"
        assert result["strategy"] == "vlm_only"
        assert result["task_type"] == "navigate"
        assert result["steps"] == []
        assert result["_raw"] == "This is not valid JSON at all!!!"

    @pytest.mark.asyncio
    async def test_generate_fills_missing_required_keys(self) -> None:
        """LLM returns JSON missing some required keys -> filled via setdefault."""
        partial_dsl = json.dumps({
            "steps": [{"action": "click", "selector": ".btn"}],
        })
        llm = FakeLLMRouter(response=partial_dsl)
        profile = _make_profile(domain="partial.com")
        assignments = [
            StrategyAssignment(page_type="home", url_pattern="/", strategy="dom_only"),
        ]

        result = await self.generator.generate(profile, assignments, "purchase", llm)

        # Missing keys filled by setdefault
        assert result["domain"] == "partial.com"
        assert result["strategy"] == "dom_only"
        assert result["task_type"] == "purchase"
        assert len(result["steps"]) == 1

    @pytest.mark.asyncio
    async def test_generate_empty_assignments_fallback(self) -> None:
        """Empty assignments list -> strategy defaults to 'dom_only'."""
        llm = FakeLLMRouter(response="not json")
        profile = _make_profile(domain="empty.com")

        result = await self.generator.generate(profile, [], "search", llm)

        assert result["strategy"] == "dom_only"

    def test_build_context_formatting(self) -> None:
        """_build_context produces profile_summary and strategy_summary strings."""
        profile = _make_profile(
            domain="ctx.com",
            purpose="news",
            framework="react",
            is_spa=True,
            content_types=[
                ContentPattern(page_type="article", url_pattern="/article/*", dynamic_content=True),
            ],
            obstacles=[
                ObstaclePattern(
                    type="cookie_consent",
                    trigger="page_load",
                    dismiss_method="click_close",
                ),
            ],
        )
        assignments = [
            StrategyAssignment(
                page_type="article",
                url_pattern="/article/*",
                strategy="dom_only",
                tools_needed=["playwright", "cdp"],
            ),
        ]

        ctx = DSLGenerator._build_context(profile, assignments)

        assert "profile_summary" in ctx
        assert "strategy_summary" in ctx
        assert "ctx.com" in ctx["profile_summary"]
        assert "news" in ctx["profile_summary"]
        assert "react" in ctx["profile_summary"]
        assert "SPA: True" in ctx["profile_summary"]
        assert "cookie_consent" in ctx["profile_summary"]
        assert "article" in ctx["profile_summary"]
        assert "article" in ctx["strategy_summary"]
        assert "dom_only" in ctx["strategy_summary"]

    def test_system_prompt_includes_domain_and_site_info(self) -> None:
        """_system_prompt includes domain, purpose, framework, canvas info."""
        profile = _make_profile(
            domain="sys.com",
            purpose="saas",
            framework="angular",
            canvas_has=True,
        )

        prompt = DSLGenerator._system_prompt(profile)

        assert "sys.com" in prompt
        assert "saas" in prompt
        assert "angular" in prompt
        assert "present (VLM required)" in prompt
        assert "web automation workflow DSL generator" in prompt

    def test_system_prompt_no_canvas(self) -> None:
        """_system_prompt shows 'none' when no canvas."""
        profile = _make_profile(domain="nocanvas.com")

        prompt = DSLGenerator._system_prompt(profile)

        assert "Canvas: none" in prompt


# ═══════════════════════════════════════════════════════════
# PromptGenerator Tests
# ═══════════════════════════════════════════════════════════


class TestPromptGenerator:
    """Tests for PromptGenerator.generate()."""

    def setup_method(self) -> None:
        self.gen = PromptGenerator()

    def test_generate_returns_all_four_prompt_keys(self) -> None:
        """generate() always returns extract, navigate, verify, fallback."""
        profile = _make_profile(domain="four.com")
        result = self.gen.generate(profile, "search", "dom_only")

        assert set(result.keys()) == {"extract", "navigate", "verify", "fallback"}
        for key in ("extract", "navigate", "verify", "fallback"):
            assert isinstance(result[key], str)
            assert len(result[key]) > 0

    def test_extract_prompt_includes_key_selectors(self) -> None:
        """Extract prompt contains key_selectors from content patterns."""
        content = ContentPattern(
            page_type="home",
            url_pattern="/",
            key_selectors={"search_box": "#search-input", "nav_menu": "nav.main"},
        )
        profile = _make_profile(domain="selectors.com", content_types=[content])
        result = self.gen.generate(profile, "search", "dom_only")

        assert 'search_box: "#search-input"' in result["extract"]
        assert 'nav_menu: "nav.main"' in result["extract"]

    def test_navigate_prompt_includes_search_info(self) -> None:
        """Navigate prompt includes search section when search_functionality present."""
        search = SearchConfig(
            input_selector="#q",
            submit_method="enter",
            autocomplete=True,
        )
        profile = _make_profile(
            domain="nav.com",
            search_functionality=search,
        )
        result = self.gen.generate(profile, "search", "dom_only")

        assert "search:" in result["navigate"]
        assert "input_selector: #q" in result["navigate"]
        assert "submit_method: enter" in result["navigate"]
        assert "autocomplete: True" in result["navigate"]

    def test_navigate_prompt_no_search(self) -> None:
        """Navigate prompt omits search section when no search_functionality."""
        profile = _make_profile(domain="nosearch.com", search_functionality=None)
        result = self.gen.generate(profile, "browse", "dom_only")

        assert "input_selector:" not in result["navigate"]

    def test_verify_prompt_includes_spa_detection(self) -> None:
        """Verify prompt mentions SPA status."""
        profile = _make_profile(domain="spa.com", is_spa=True)
        result = self.gen.generate(profile, "navigate", "dom_only")

        assert "SPA: True" in result["verify"]
        assert "MutationObserver" in result["verify"]

    def test_verify_prompt_dynamic_content_detection(self) -> None:
        """Verify prompt detects dynamic_content from content_types."""
        content = ContentPattern(page_type="home", url_pattern="/", dynamic_content=True)
        profile = _make_profile(domain="dynamic.com", content_types=[content])
        result = self.gen.generate(profile, "search", "dom_only")

        assert "Dynamic content: True" in result["verify"]

    def test_fallback_prompt_has_vision_note_for_vision_strategies(self) -> None:
        """Fallback prompt includes vision grounding note for vlm/grid strategies."""
        profile = _make_profile(domain="vis.com")

        for strategy in ("grid_vlm", "vlm_only", "objdet_dom_hybrid"):
            result = self.gen.generate(profile, "search", strategy)
            assert "vision grounding" in result["fallback"]

    def test_fallback_prompt_no_vision_note_for_dom_only(self) -> None:
        """Fallback prompt omits vision note for dom_only strategy."""
        profile = _make_profile(domain="dom.com")
        result = self.gen.generate(profile, "search", "dom_only")

        assert "vision grounding" not in result["fallback"]

    def test_empty_obstacles_handled(self) -> None:
        """No obstacles -> obstacle section shows '(none)'."""
        profile = _make_profile(domain="clean.com", obstacles=[])
        result = self.gen.generate(profile, "search", "dom_only")

        assert "(none)" in result["extract"]

    def test_empty_key_selectors_handled(self) -> None:
        """No key_selectors -> selector section shows '(none)'."""
        content = ContentPattern(page_type="home", url_pattern="/", key_selectors={})
        profile = _make_profile(domain="nosel.com", content_types=[content])
        result = self.gen.generate(profile, "search", "dom_only")

        # key_selectors section shows (none) because dict is empty
        assert "(none)" in result["extract"]

    def test_obstacles_formatted_in_extract(self) -> None:
        """Obstacles are properly formatted in extract prompt."""
        obstacles = [
            ObstaclePattern(
                type="popup",
                trigger="page_load",
                dismiss_method="click_close",
                selector="#close-btn",
            ),
        ]
        profile = _make_profile(domain="obs.com", obstacles=obstacles)
        result = self.gen.generate(profile, "search", "dom_only")

        assert "popup" in result["extract"]
        assert "page_load" in result["extract"]
        assert "click_close" in result["extract"]
        assert "#close-btn" in result["extract"]


# ═══════════════════════════════════════════════════════════
# CodeValidator Tests
# ═══════════════════════════════════════════════════════════


class TestCodeValidator:
    """Tests for CodeValidator.validate()."""

    def setup_method(self) -> None:
        self.validator = CodeValidator()

    @pytest.mark.asyncio
    async def test_valid_dsl_passes_schema_check(self) -> None:
        """Valid DSL with all required keys and non-empty steps passes."""
        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "valid.com",
                "strategy": "dom_only",
                "steps": [{"action": "click", "selector": ".btn"}],
            },
        )
        profile = _make_profile(domain="valid.com")
        result = await self.validator.validate(bundle, profile)

        assert result.dsl_ok is True
        assert result.macro_ok is True
        assert result.overall is True
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_missing_required_keys_errors(self) -> None:
        """DSL missing required keys -> dsl_ok=False with error message."""
        bundle = GeneratedBundle(
            workflow_dsl={
                "steps": [{"action": "click"}],
                # missing "domain" and "strategy"
            },
        )
        profile = _make_profile()
        result = await self.validator.validate(bundle, profile)

        assert result.dsl_ok is False
        assert any("missing required keys" in e for e in result.errors)
        # Should mention both missing keys
        assert any("domain" in e for e in result.errors)
        assert any("strategy" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_empty_steps_error(self) -> None:
        """DSL with empty steps list -> dsl_ok=False."""
        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "empty.com",
                "strategy": "dom_only",
                "steps": [],
            },
        )
        profile = _make_profile()
        result = await self.validator.validate(bundle, profile)

        assert result.dsl_ok is False
        assert any("empty" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_python_macro_syntax_error_fails_lint(self) -> None:
        """Python macro with syntax error -> macro_ok=False."""
        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "lint.com",
                "strategy": "dom_only",
                "steps": [{"action": "click"}],
            },
            python_macro="def broken(\n    this is not valid python!!!",
        )
        profile = _make_profile()
        result = await self.validator.validate(bundle, profile)

        assert result.macro_ok is False
        assert any("syntax error" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_valid_python_macro_passes_lint(self) -> None:
        """Valid Python macro passes the lint check."""
        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "good.com",
                "strategy": "dom_only",
                "steps": [{"action": "click"}],
            },
            python_macro="async def run(page):\n    await page.click('.btn')\n",
        )
        profile = _make_profile()
        result = await self.validator.validate(bundle, profile)

        assert result.macro_ok is True

    @pytest.mark.asyncio
    async def test_no_macro_passes_lint(self) -> None:
        """No python_macro (None) passes lint check."""
        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "nomacro.com",
                "strategy": "dom_only",
                "steps": [{"action": "goto"}],
            },
            python_macro=None,
        )
        profile = _make_profile()
        result = await self.validator.validate(bundle, profile)

        assert result.macro_ok is True

    @pytest.mark.asyncio
    async def test_full_validate_accumulates_all_errors(self) -> None:
        """Multiple failures accumulate in errors list."""
        bundle = GeneratedBundle(
            workflow_dsl={
                # missing "domain" and "strategy" -> schema fail
                "steps": [],  # also empty steps
            },
            python_macro="invalid syntax {{{{",
        )
        profile = _make_profile()
        result = await self.validator.validate(bundle, profile)

        # DSL schema check catches missing keys first, stops before empty check
        # But macro lint still runs independently
        assert result.dsl_ok is False
        assert result.macro_ok is False
        assert len(result.errors) >= 2

    @pytest.mark.asyncio
    async def test_non_dict_dsl_fails(self) -> None:
        """workflow_dsl that is not a dict -> error."""
        bundle = GeneratedBundle()
        # Force a non-dict value
        bundle.workflow_dsl = "not a dict"  # type: ignore[assignment]
        profile = _make_profile()
        result = await self.validator.validate(bundle, profile)

        assert result.dsl_ok is False
        assert any("not a dict" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_steps_not_list_fails(self) -> None:
        """DSL with steps that is not a list -> error."""
        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "badsteps.com",
                "strategy": "dom_only",
                "steps": "not a list",
            },
        )
        profile = _make_profile()
        result = await self.validator.validate(bundle, profile)

        assert result.dsl_ok is False
        assert any("must be a list" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_placeholder_stages_pass(self) -> None:
        """Placeholder stages (selector, HAR, canary) return True."""
        bundle = GeneratedBundle(
            workflow_dsl={
                "domain": "placeholder.com",
                "strategy": "dom_only",
                "steps": [{"action": "goto"}],
            },
        )
        profile = _make_profile()
        result = await self.validator.validate(bundle, profile)

        assert result.selector_ok is True
        assert result.har_replay_ok is True
        assert result.canary_ok is True
        assert result.trace_ok is True


# ═══════════════════════════════════════════════════════════
# CodeGenAgent Tests
# ═══════════════════════════════════════════════════════════


class TestCodeGenAgent:
    """Tests for CodeGenAgent.generate_bundle()."""

    def _make_valid_dsl(self, domain: str = "test.com") -> str:
        """Return valid DSL JSON string."""
        return json.dumps({
            "domain": domain,
            "strategy": "dom_only",
            "task_type": "search",
            "steps": [
                {"action": "goto", "selector": None, "verify": "url_changed"},
                {"action": "fill", "selector": "#q", "value": "test", "verify": "value_set"},
            ],
        })

    @pytest.mark.asyncio
    async def test_happy_path_valid_bundle(self) -> None:
        """Full pipeline produces a validated bundle."""
        from src.codegen.agent import CodeGenAgent

        llm = FakeLLMRouter(response=self._make_valid_dsl("happy.com"))
        kb = FakeKBManager()
        profile = _make_profile(
            domain="happy.com",
            content_types=[
                ContentPattern(page_type="home", url_pattern="/", dom_readable=True),
            ],
            text_node_ratio=0.5,
            aria_coverage=0.4,
        )

        agent = CodeGenAgent()
        bundle = await agent.generate_bundle(
            "happy.com", profile, "search", kb, llm,
        )

        assert isinstance(bundle, GeneratedBundle)
        assert bundle.strategy in STRATEGIES
        assert len(bundle.workflow_dsl.get("steps", [])) == 2
        assert "extract" in bundle.prompts
        assert "navigate" in bundle.prompts
        assert "verify" in bundle.prompts
        assert "fallback" in bundle.prompts
        assert len(bundle.dependencies) > 0

    @pytest.mark.asyncio
    async def test_validation_failure_retries(self) -> None:
        """Validation failure on first attempt triggers retry."""
        from src.codegen.agent import CodeGenAgent

        call_count = 0

        class RetryLLM(FakeLLMRouter):
            async def complete(self, alias: str, messages: Any, **kw: Any) -> str:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # First attempt: invalid JSON -> empty steps -> validation fail
                    return "not valid json"
                # Second attempt: valid DSL
                return json.dumps({
                    "domain": "retry.com",
                    "strategy": "dom_only",
                    "task_type": "search",
                    "steps": [{"action": "click", "selector": ".btn"}],
                })

        llm = RetryLLM()
        kb = FakeKBManager()
        profile = _make_profile(domain="retry.com")

        agent = CodeGenAgent()
        bundle = await agent.generate_bundle(
            "retry.com", profile, "search", kb, llm,
        )

        # Should have called LLM twice (retry)
        assert call_count == 2
        # Final bundle should have version 2 (second attempt)
        assert bundle.version == 2

    @pytest.mark.asyncio
    async def test_kb_save_on_completion(self) -> None:
        """Bundle artifacts saved to KB after generation."""
        from src.codegen.agent import CodeGenAgent

        llm = FakeLLMRouter(response=self._make_valid_dsl("save.com"))
        kb = FakeKBManager()
        profile = _make_profile(
            domain="save.com",
            content_types=[
                ContentPattern(page_type="home", url_pattern="/docs", dom_readable=True),
            ],
            text_node_ratio=0.5,
            aria_coverage=0.4,
        )

        agent = CodeGenAgent()
        await agent.generate_bundle("save.com", profile, "search", kb, llm)

        # Pattern meta saved
        assert len(kb.saved_pattern_meta) == 1
        assert kb.saved_pattern_meta[0][0] == "save.com"
        assert kb.saved_pattern_meta[0][2] == "search"

        # Workflow saved
        assert len(kb.saved_workflows) == 1
        assert kb.saved_workflows[0][0] == "save.com"

        # Prompts saved
        assert len(kb.saved_prompts) == 1
        assert kb.saved_prompts[0][0] == "save.com"
        assert set(kb.saved_prompts[0][2].keys()) == {
            "extract", "navigate", "verify", "fallback",
        }

    @pytest.mark.asyncio
    async def test_dependency_dedup(self) -> None:
        """Dependencies collected from assignments are deduplicated."""
        from src.codegen.agent import CodeGenAgent

        llm = FakeLLMRouter(response=self._make_valid_dsl("dedup.com"))
        kb = FakeKBManager()
        profile = _make_profile(
            domain="dedup.com",
            content_types=[
                ContentPattern(page_type="home", url_pattern="/", dom_readable=True),
                ContentPattern(page_type="list", url_pattern="/list", dom_readable=True),
            ],
            text_node_ratio=0.5,
            aria_coverage=0.4,
        )

        agent = CodeGenAgent()
        bundle = await agent.generate_bundle(
            "dedup.com", profile, "search", kb, llm,
        )

        # No duplicate tools in dependencies
        assert len(bundle.dependencies) == len(set(bundle.dependencies))
        # playwright should appear exactly once
        assert bundle.dependencies.count("playwright") <= 1

    @pytest.mark.asyncio
    async def test_primary_url_pattern_extraction(self) -> None:
        """Primary URL pattern is extracted from first assignment."""
        from src.codegen.agent import CodeGenAgent

        llm = FakeLLMRouter(response=self._make_valid_dsl("url.com"))
        kb = FakeKBManager()
        profile = _make_profile(
            domain="url.com",
            content_types=[
                ContentPattern(page_type="product", url_pattern="/product/*", dom_readable=True),
                ContentPattern(page_type="home", url_pattern="/", dom_readable=True),
            ],
            text_node_ratio=0.5,
            aria_coverage=0.4,
        )

        agent = CodeGenAgent()
        await agent.generate_bundle("url.com", profile, "purchase", kb, llm)

        # URL pattern in KB save comes from first assignment
        assert len(kb.saved_pattern_meta) == 1
        url_pattern = kb.saved_pattern_meta[0][1]
        # Should be the first content_type's url_pattern
        assert url_pattern == "/product/*"

    @pytest.mark.asyncio
    async def test_kb_save_failure_does_not_crash(self) -> None:
        """KB save failure is caught and logged, does not raise."""
        from src.codegen.agent import CodeGenAgent

        llm = FakeLLMRouter(response=self._make_valid_dsl("fail-kb.com"))
        kb = FailingKBManager()
        profile = _make_profile(
            domain="fail-kb.com",
            content_types=[
                ContentPattern(page_type="home", url_pattern="/", dom_readable=True),
            ],
            text_node_ratio=0.5,
            aria_coverage=0.4,
        )

        agent = CodeGenAgent()
        # Should not raise even though KB save fails
        bundle = await agent.generate_bundle(
            "fail-kb.com", profile, "search", kb, llm,
        )
        assert isinstance(bundle, GeneratedBundle)

    @pytest.mark.asyncio
    async def test_custom_injected_components(self) -> None:
        """Agent accepts injected strategy_decider, dsl_gen, prompt_gen, validator."""
        from src.codegen.agent import CodeGenAgent

        decider = StrategyDecider()
        dsl_gen = DSLGenerator()
        prompt_gen = PromptGenerator()
        validator = CodeValidator()

        agent = CodeGenAgent(
            strategy_decider=decider,
            dsl_generator=dsl_gen,
            prompt_generator=prompt_gen,
            validator=validator,
        )

        assert agent._strategy_decider is decider
        assert agent._dsl_generator is dsl_gen
        assert agent._prompt_generator is prompt_gen
        assert agent._validator is validator

    @pytest.mark.asyncio
    async def test_bundle_includes_macro_in_kb_save(self) -> None:
        """When bundle has python_macro, it is saved to KB."""
        from src.codegen.agent import CodeGenAgent

        dsl_response = json.dumps({
            "domain": "macro.com",
            "strategy": "dom_only",
            "task_type": "search",
            "steps": [{"action": "click"}],
        })
        llm = FakeLLMRouter(response=dsl_response)
        kb = FakeKBManager()
        profile = _make_profile(
            domain="macro.com",
            content_types=[
                ContentPattern(page_type="home", url_pattern="/", dom_readable=True),
            ],
            text_node_ratio=0.5,
            aria_coverage=0.4,
        )

        # Create agent with a custom validator that modifies the bundle
        class MacroValidator(CodeValidator):
            async def validate(
                self, bundle: GeneratedBundle, profile: SiteProfile,
            ) -> ValidationResult:
                # Inject a macro into the bundle for testing
                bundle.python_macro = "async def run(page): pass"
                return await super().validate(bundle, profile)

        agent = CodeGenAgent(validator=MacroValidator())
        await agent.generate_bundle("macro.com", profile, "search", kb, llm)

        # Macro should have been saved
        assert len(kb.saved_macros) == 1
        assert kb.saved_macros[0][0] == "macro.com"
        assert "async def run" in kb.saved_macros[0][2]


# ═══════════════════════════════════════════════════════════
# StrategyDecider Edge Cases
# ═══════════════════════════════════════════════════════════


class TestStrategyDeciderEdgeCases:
    """Additional edge cases for StrategyDecider."""

    def setup_method(self) -> None:
        self.decider = StrategyDecider()

    def test_canvas_has_canvas_but_not_vision_only(self) -> None:
        """Canvas present but not vision_only -> hybrid/vlm get smaller boosts."""
        content = ContentPattern(page_type="mixed", url_pattern="/mixed")
        profile = _make_profile(
            content_types=[content],
            canvas_has=True,
            canvas_vision_only=False,
            text_node_ratio=0.1,
            aria_coverage=0.05,
        )
        result = self.decider.decide(profile, "navigate")

        assert len(result) == 1
        # has_canvas gives +0.6 to objdet_dom_hybrid, +0.4 to vlm_only
        # but NOT the +2.0 from requires_vision_only
        assert result[0].strategy in ("objdet_dom_hybrid", "vlm_only")

    def test_all_strategies_present_in_module(self) -> None:
        """STRATEGIES list contains exactly the 5 expected strategies."""
        assert len(STRATEGIES) == 5
        expected = {
            "dom_only",
            "dom_with_objdet_backup",
            "objdet_dom_hybrid",
            "grid_vlm",
            "vlm_only",
        }
        assert set(STRATEGIES) == expected

    def test_tool_map_covers_all_strategies(self) -> None:
        """_TOOL_MAP has entries for all STRATEGIES."""
        for s in STRATEGIES:
            assert s in _TOOL_MAP
            assert len(_TOOL_MAP[s]) > 0
            # All strategies require playwright
            assert "playwright" in _TOOL_MAP[s]
