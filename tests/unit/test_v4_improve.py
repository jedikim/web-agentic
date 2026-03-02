"""Unit tests for v4 Phase 4 (Improve) modules.

Covers FailureAnalyzer, SelfImprover, ChangeDetector, PromptOptimizer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.improve.change_detector import (
    THRESHOLD_PATCH,
    THRESHOLD_RECON,
    ChangeDetector,
    _hash_ax_tree,
)
from src.improve.failure_analyzer import AnalysisContext, FailureAnalyzer
from src.improve.prompt_optimizer import (
    PromptOptimizer,
    _compute_success_rate,
    _summarize_failures,
)
from src.improve.self_improver import SelfImprover, _parse_json_safe
from src.models.failure import FailureEvidence, FailureType, RemediationAction
from src.models.site_profile import (
    ContentPattern,
    NavigationStructure,
    SearchConfig,
    SiteProfile,
)

# ── Mocks ──


class MockLLM:
    """Fake LLM router that returns a configurable response string."""

    def __init__(self, response: str = "{}") -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        task_type: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        self.calls.append({
            "task_type": task_type,
            "messages": messages,
            **kwargs,
        })
        return self._response

    def resolve_model(self, alias: str) -> str:
        return f"mock-model/{alias}"


class MockKB:
    """Fake KBManager with in-memory storage.

    Implements: load_profile, save_profile, load_workflow, save_workflow,
    load_prompts, save_prompts, append_run, lookup, base_dir.
    """

    def __init__(self, tmp_path: Path | None = None) -> None:
        self._profiles: dict[str, SiteProfile] = {}
        self._workflows: dict[str, dict[str, Any]] = {}
        self._prompts: dict[str, dict[str, str]] = {}
        self._runs: list[dict[str, Any]] = []
        self._workflow_versions: dict[str, int] = {}
        self._prompt_versions: dict[str, int] = {}
        self._base = tmp_path or Path("/tmp/mock_kb")

    @property
    def base_dir(self) -> Path:
        return self._base

    def load_profile(self, domain: str) -> SiteProfile | None:
        return self._profiles.get(domain)

    def save_profile(self, profile: SiteProfile) -> int:
        self._profiles[profile.domain] = profile
        return profile.recon_version

    def load_workflow(
        self, domain: str, url_pattern: str
    ) -> dict[str, Any] | None:
        key = f"{domain}::{url_pattern}"
        return self._workflows.get(key)

    def save_workflow(
        self,
        domain: str,
        url_pattern: str,
        dsl: dict[str, Any],
        version: int | None = None,
    ) -> int:
        key = f"{domain}::{url_pattern}"
        self._workflows[key] = dsl
        if version is not None:
            self._workflow_versions[key] = version
            return version
        current = self._workflow_versions.get(key, 0) + 1
        self._workflow_versions[key] = current
        return current

    def load_prompts(
        self, domain: str, url_pattern: str
    ) -> dict[str, str] | None:
        key = f"{domain}::{url_pattern}"
        return self._prompts.get(key)

    def save_prompts(
        self,
        domain: str,
        url_pattern: str,
        prompts: dict[str, str],
        version: int | None = None,
    ) -> int:
        key = f"{domain}::{url_pattern}"
        self._prompts[key] = prompts
        if version is not None:
            self._prompt_versions[key] = version
            return version
        current = self._prompt_versions.get(key, 0) + 1
        self._prompt_versions[key] = current
        return current

    def append_run(self, domain: str, record: dict[str, Any]) -> None:
        self._runs.append({"domain": domain, **record})

    def lookup(self, domain: str, url: str) -> dict[str, Any]:
        profile = self.load_profile(domain)
        return {"hit": profile is not None, "profile": profile}


class MockBrowser:
    """Fake browser implementing the IBrowser protocol for ChangeDetector."""

    def __init__(
        self,
        *,
        query_results: dict[str, list[Any]] | None = None,
        evaluate_return: Any = None,
        ax_snapshot: dict[str, Any] | None = None,
        current_url: str = "https://example.com",
    ) -> None:
        self._query_results = query_results or {}
        self._evaluate_return = evaluate_return
        self._ax_snapshot = ax_snapshot or {"role": "page", "children": []}
        self._url = current_url

    async def query_selector_all(self, selector: str) -> list[Any]:
        return self._query_results.get(selector, [])

    async def evaluate(self, expression: str) -> Any:
        return self._evaluate_return

    async def accessibility_snapshot(self) -> dict[str, Any]:
        return self._ax_snapshot

    async def url(self) -> str:
        return self._url


# ── Helper exception classes for Level 1 Playwright mapping ──


class TimeoutError(Exception):  # noqa: A001
    """Playwright-like TimeoutError (shadows builtin intentionally)."""
    pass


class TargetClosedError(Exception):
    """Playwright-like TargetClosedError."""
    pass


class BrowserClosedError(Exception):
    """Playwright-like BrowserClosedError."""
    pass


# ========================================================================
# FailureAnalyzer Tests
# ========================================================================


class TestFailureAnalyzer:
    """Tests for the 4-level failure classification."""

    @pytest.mark.asyncio
    async def test_level1_playwright_timeout_error(self) -> None:
        """Level 1: Playwright error class name 'TimeoutError' maps to TIMEOUT."""
        analyzer = FailureAnalyzer(llm_router=None)
        error = TimeoutError("Page load timed out")

        result = await analyzer.analyze(error)

        assert result.failure_type == FailureType.TIMEOUT
        assert result.error_message == "Page load timed out"
        assert result.remediation == RemediationAction.ADD_WAIT

    @pytest.mark.asyncio
    async def test_level1_playwright_target_closed(self) -> None:
        """Level 1: 'TargetClosedError' maps to NAVIGATION_FAILED."""
        analyzer = FailureAnalyzer(llm_router=None)
        error = TargetClosedError("Target page closed")

        result = await analyzer.analyze(error)

        assert result.failure_type == FailureType.NAVIGATION_FAILED
        assert result.remediation == RemediationAction.CHANGE_STRATEGY

    @pytest.mark.asyncio
    async def test_level2_verification_code(self) -> None:
        """Level 2: Verification code 'selector_not_found' maps correctly."""
        analyzer = FailureAnalyzer(llm_router=None)
        ctx = AnalysisContext(
            url="https://shop.com/cart",
            verification_code="selector_not_found",
            selector="#add-to-cart",
        )
        # Use a string error (no class name match for L1)
        result = await analyzer.analyze("element missing from page", ctx)

        assert result.failure_type == FailureType.SELECTOR_NOT_FOUND
        assert result.selector == "#add-to-cart"
        assert result.url == "https://shop.com/cart"
        assert result.remediation == RemediationAction.FIX_SELECTOR

    @pytest.mark.asyncio
    async def test_level3_string_pattern_captcha(self) -> None:
        """Level 3: Regex pattern match for 'captcha' in error message."""
        analyzer = FailureAnalyzer(llm_router=None)
        result = await analyzer.analyze("reCAPTCHA challenge detected on page")

        assert result.failure_type == FailureType.CAPTCHA
        assert result.remediation == RemediationAction.HUMAN_HANDOFF

    @pytest.mark.asyncio
    async def test_level3_string_pattern_cookie_consent(self) -> None:
        """Level 3: 'cookie consent banner' matches OBSTACLE_BLOCKED."""
        analyzer = FailureAnalyzer(llm_router=None)
        result = await analyzer.analyze("cookie consent banner is blocking interaction")

        assert result.failure_type == FailureType.OBSTACLE_BLOCKED
        assert result.remediation == RemediationAction.FIX_OBSTACLE

    @pytest.mark.asyncio
    async def test_level4_llm_classification(self) -> None:
        """Level 4: When L1-L3 all fail, LLM classifies the failure."""
        llm = MockLLM(
            response='{"failure_type": "strategy_mismatch", "reason": "SPA routing"}'
        )
        analyzer = FailureAnalyzer(llm_router=llm)  # type: ignore[arg-type]

        # An error message that doesn't match any L1/L2/L3 patterns
        result = await analyzer.analyze(
            "unexpected page state after interaction",
            AnalysisContext(url="https://spa.app/dashboard"),
        )

        assert result.failure_type == FailureType.STRATEGY_MISMATCH
        assert len(llm.calls) == 1
        assert llm.calls[0]["task_type"] == "fast"

    @pytest.mark.asyncio
    async def test_fallback_unknown_when_no_llm(self) -> None:
        """Fallback to UNKNOWN when all levels fail and no LLM provided."""
        analyzer = FailureAnalyzer(llm_router=None)

        # Error message that won't match any pattern
        result = await analyzer.analyze("some completely novel error xyz123")

        assert result.failure_type == FailureType.UNKNOWN
        assert result.remediation == RemediationAction.HUMAN_HANDOFF

    @pytest.mark.asyncio
    async def test_llm_json_parse_error_falls_to_unknown(self) -> None:
        """LLM returns unparseable JSON -> falls back to UNKNOWN."""
        llm = MockLLM(response="this is not JSON at all")
        analyzer = FailureAnalyzer(llm_router=llm)  # type: ignore[arg-type]

        result = await analyzer.analyze("some completely novel error xyz123")

        assert result.failure_type == FailureType.UNKNOWN
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_context_with_missing_optional_fields(self) -> None:
        """AnalysisContext with only url set — no crash, no KeyError."""
        analyzer = FailureAnalyzer(llm_router=None)
        ctx = AnalysisContext(url="https://example.com")

        # A pattern match error to confirm basic flow works
        result = await analyzer.analyze(
            "waiting for selector #missing",
            ctx,
        )

        assert result.failure_type == FailureType.SELECTOR_NOT_FOUND
        assert result.url == "https://example.com"
        assert result.selector is None
        assert result.screenshot_path is None
        assert result.dom_snapshot is None
        assert result.extra == {}


# ========================================================================
# SelfImprover Tests
# ========================================================================


class TestSelfImprover:
    """Tests for remediation dispatch and patching."""

    def _make_evidence(
        self,
        ft: FailureType,
        remediation: RemediationAction,
        selector: str | None = None,
        url: str = "https://shop.com/products",
        error_msg: str = "test error",
        extra: dict[str, Any] | None = None,
    ) -> FailureEvidence:
        return FailureEvidence(
            failure_type=ft,
            error_message=error_msg,
            selector=selector,
            url=url,
            remediation=remediation,
            extra=extra or {},
        )

    @pytest.mark.asyncio
    async def test_dispatch_fix_selector(self) -> None:
        """FIX_SELECTOR dispatches to _fix_selector."""
        llm = MockLLM(
            response='{"new_selector": ".btn-add-cart", "reason": "class changed"}'
        )
        kb = MockKB()
        kb.save_workflow("shop.com", "/products*", {
            "steps": [
                {"selector": "#old-btn", "action": "click"},
            ],
        })

        ev = self._make_evidence(
            FailureType.SELECTOR_NOT_FOUND,
            RemediationAction.FIX_SELECTOR,
            selector="#old-btn",
        )
        improver = SelfImprover()
        result = await improver.improve(ev, "shop.com", "/products*", kb, llm)  # type: ignore[arg-type]

        assert result.action_taken == "fix_selector"
        assert result.new_version is not None
        assert ".btn-add-cart" in result.detail
        assert len(result.patches) == 1
        # Verify the workflow was patched
        wf = kb.load_workflow("shop.com", "/products*")
        assert wf is not None
        assert wf["steps"][0]["selector"] == ".btn-add-cart"

    @pytest.mark.asyncio
    async def test_dispatch_fix_obstacle(self) -> None:
        """FIX_OBSTACLE dispatches to _fix_obstacle, prepends step."""
        llm = MockLLM(
            response=(
                '{"dismiss_code": "page.click(\\"#close\\")",'
                ' "obstacle_type": "popup", "reason": "dismiss popup"}'
            )
        )
        kb = MockKB()
        kb.save_workflow("shop.com", "/products*", {
            "steps": [{"selector": "#search", "action": "click"}],
        })

        ev = self._make_evidence(
            FailureType.OBSTACLE_BLOCKED,
            RemediationAction.FIX_OBSTACLE,
            extra={"obstacle_type": "popup"},
        )
        improver = SelfImprover()
        result = await improver.improve(ev, "shop.com", "/products*", kb, llm)  # type: ignore[arg-type]

        assert result.action_taken == "fix_obstacle"
        assert result.new_version is not None
        wf = kb.load_workflow("shop.com", "/products*")
        assert wf is not None
        # Obstacle dismissal inserted as first step
        assert wf["steps"][0]["action"] == "run_code"
        assert wf["steps"][0]["auto_generated"] is True
        assert wf["steps"][1]["selector"] == "#search"

    @pytest.mark.asyncio
    async def test_dispatch_full_recon(self) -> None:
        """FULL_RECON returns needs_recon=True without LLM call."""
        llm = MockLLM()
        kb = MockKB()

        ev = self._make_evidence(
            FailureType.SITE_CHANGED,
            RemediationAction.FULL_RECON,
            error_msg="layout changed significantly",
        )
        improver = SelfImprover()
        result = await improver.improve(ev, "shop.com", "/products*", kb, llm)  # type: ignore[arg-type]

        assert result.needs_recon is True
        assert result.action_taken == "full_recon"
        # No LLM call needed
        assert len(llm.calls) == 0

    @pytest.mark.asyncio
    async def test_dispatch_human_handoff(self) -> None:
        """HUMAN_HANDOFF returns needs_human=True without LLM call."""
        llm = MockLLM()
        kb = MockKB()

        ev = self._make_evidence(
            FailureType.CAPTCHA,
            RemediationAction.HUMAN_HANDOFF,
            error_msg="reCAPTCHA detected",
        )
        improver = SelfImprover()
        result = await improver.improve(ev, "shop.com", "/", kb, llm)  # type: ignore[arg-type]

        assert result.needs_human is True
        assert result.action_taken == "human_handoff"
        assert "captcha" in result.detail.lower()
        assert len(llm.calls) == 0

    @pytest.mark.asyncio
    async def test_selector_fix_saves_new_version(self) -> None:
        """Selector fix: LLM returns new selector, workflow is versioned."""
        llm = MockLLM(
            response='{"new_selector": "button.submit", "reason": "DOM updated"}'
        )
        kb = MockKB()
        # Pre-populate workflow at version 1
        kb.save_workflow("test.com", "/form", {
            "steps": [
                {"selector": "#old-submit", "action": "click"},
                {"selector": "#name", "action": "type", "value": "test"},
            ],
        })

        ev = self._make_evidence(
            FailureType.SELECTOR_NOT_FOUND,
            RemediationAction.FIX_SELECTOR,
            selector="#old-submit",
        )
        improver = SelfImprover()
        result = await improver.improve(ev, "test.com", "/form", kb, llm)  # type: ignore[arg-type]

        assert result.new_version is not None
        assert result.new_version >= 1
        wf = kb.load_workflow("test.com", "/form")
        assert wf is not None
        # Only the matching step selector was changed
        assert wf["steps"][0]["selector"] == "button.submit"
        assert wf["steps"][1]["selector"] == "#name"  # untouched

    @pytest.mark.asyncio
    async def test_add_wait_inserts_step(self) -> None:
        """ADD_WAIT: inserts wait step at the LLM-recommended index."""
        llm = MockLLM(
            response=(
                '{"wait_ms": 5000, "wait_for": ".loading-spinner",'
                ' "insert_before_step": 1, "reason": "slow load"}'
            )
        )
        kb = MockKB()
        kb.save_workflow("test.com", "/products", {
            "steps": [
                {"selector": "#search", "action": "click"},
                {"selector": "#result", "action": "click"},
            ],
        })

        ev = self._make_evidence(
            FailureType.TIMEOUT,
            RemediationAction.ADD_WAIT,
            error_msg="timeout 30000ms exceeded",
        )
        improver = SelfImprover()
        result = await improver.improve(ev, "test.com", "/products", kb, llm)  # type: ignore[arg-type]

        assert result.action_taken == "add_wait"
        assert result.new_version is not None
        wf = kb.load_workflow("test.com", "/products")
        assert wf is not None
        # Wait step inserted at index 1
        assert len(wf["steps"]) == 3
        assert wf["steps"][1]["action"] == "wait"
        assert wf["steps"][1]["wait_ms"] == 5000
        assert wf["steps"][1]["wait_for"] == ".loading-spinner"
        assert wf["steps"][1]["auto_generated"] is True

    @pytest.mark.asyncio
    async def test_change_strategy_updates_workflow(self) -> None:
        """CHANGE_STRATEGY: LLM recommends a new strategy, saved in workflow."""
        llm = MockLLM(
            response='{"new_strategy": "dom_with_objdet_backup", "reason": "dynamic content"}'
        )
        kb = MockKB()
        kb.save_workflow("test.com", "/dynamic", {
            "strategy": "dom_only",
            "steps": [],
        })

        ev = self._make_evidence(
            FailureType.NAVIGATION_FAILED,
            RemediationAction.CHANGE_STRATEGY,
        )
        improver = SelfImprover()
        result = await improver.improve(ev, "test.com", "/dynamic", kb, llm)  # type: ignore[arg-type]

        assert result.action_taken == "change_strategy"
        assert "dom_with_objdet_backup" in result.detail
        wf = kb.load_workflow("test.com", "/dynamic")
        assert wf is not None
        assert wf["strategy"] == "dom_with_objdet_backup"

    def test_parse_json_safe_with_markdown_fences(self) -> None:
        """_parse_json_safe strips markdown fences before parsing."""
        raw = '```json\n{"key": "value"}\n```'
        result = _parse_json_safe(raw)
        assert result == {"key": "value"}

    def test_parse_json_safe_without_fences(self) -> None:
        """_parse_json_safe handles plain JSON."""
        raw = '{"key": "value"}'
        result = _parse_json_safe(raw)
        assert result == {"key": "value"}

    def test_parse_json_safe_invalid_json(self) -> None:
        """_parse_json_safe returns empty dict on invalid JSON."""
        result = _parse_json_safe("this is not json")
        assert result == {}


# ========================================================================
# ChangeDetector Tests
# ========================================================================


class TestChangeDetector:
    """Tests for 3-signal site change detection."""

    def _make_profile(
        self,
        *,
        ax_hash: str | None = None,
        menu_selector: str = "",
        search_selector: str = "",
        content_selectors: dict[str, str] | None = None,
        api_schema_fingerprint: dict[str, str] | None = None,
        api_endpoints: list[Any] | None = None,
    ) -> SiteProfile:
        profile = SiteProfile(domain="test.com")
        profile.ax_hash = ax_hash
        profile.navigation = NavigationStructure(menu_selector=menu_selector)
        if search_selector:
            profile.search_functionality = SearchConfig(
                input_selector=search_selector,
            )
        if content_selectors:
            profile.content_types = [
                ContentPattern(key_selectors=content_selectors),
            ]
        if api_schema_fingerprint is not None:
            profile.api_schema_fingerprint = api_schema_fingerprint
        if api_endpoints is not None:
            from src.models.site_profile import APIEndpoint
            profile.api_endpoints = [
                APIEndpoint(**ep) if isinstance(ep, dict) else ep
                for ep in api_endpoints
            ]
        return profile

    @pytest.mark.asyncio
    async def test_no_profile_returns_recon(self) -> None:
        """No profile in KB -> score=1.0, action='recon'."""
        kb = MockKB()
        browser = MockBrowser()
        detector = ChangeDetector()

        result = await detector.detect("unknown.com", browser, kb)  # type: ignore[arg-type]

        assert result.score == 1.0
        assert result.action == "recon"
        assert result.needs_recon is True
        assert len(result.signal_details) == 1
        assert result.signal_details[0].name == "no_profile"

    @pytest.mark.asyncio
    async def test_all_selectors_alive(self, tmp_path: Path) -> None:
        """All selectors alive -> low score, action='none'."""
        profile = self._make_profile(
            ax_hash=None,
            menu_selector="nav.main",
            search_selector="#search",
            content_selectors={"title": "h1.title", "price": ".price"},
        )
        # Compute the current ax_hash to force exact match
        ax_data = {"role": "page", "children": []}
        profile.ax_hash = _hash_ax_tree(ax_data)

        kb = MockKB(tmp_path)
        kb._profiles["test.com"] = profile

        # All selectors return non-empty lists
        browser = MockBrowser(
            query_results={
                "nav.main": ["<nav>"],
                "#search": ["<input>"],
                "h1.title": ["<h1>"],
                ".price": ["<span>"],
            },
            ax_snapshot=ax_data,
        )
        detector = ChangeDetector()
        result = await detector.detect("test.com", browser, kb)  # type: ignore[arg-type]

        assert result.score < THRESHOLD_PATCH
        assert result.action == "none"
        assert result.needs_recon is False
        assert result.needs_patch is False

    @pytest.mark.asyncio
    async def test_all_selectors_dead(self, tmp_path: Path) -> None:
        """All selectors dead -> high score, action='recon'."""
        ax_data_stored = {"role": "page", "children": [{"role": "button"}]}
        ax_data_current = {"role": "page", "children": [{"role": "link"}, {"role": "img"}]}
        profile = self._make_profile(
            ax_hash=_hash_ax_tree(ax_data_stored),
            menu_selector="nav.main",
            search_selector="#search",
            content_selectors={"title": "h1.title"},
        )

        kb = MockKB(tmp_path)
        kb._profiles["test.com"] = profile

        # All selectors return empty lists (dead)
        browser = MockBrowser(
            query_results={},
            ax_snapshot=ax_data_current,
        )
        detector = ChangeDetector()
        result = await detector.detect("test.com", browser, kb)  # type: ignore[arg-type]

        assert result.score >= THRESHOLD_RECON
        assert result.action == "recon"

    @pytest.mark.asyncio
    async def test_partial_selector_death(self, tmp_path: Path) -> None:
        """Some selectors dead, some alive -> medium score, action='patch'."""
        ax_data = {"role": "page"}
        profile = self._make_profile(
            ax_hash=_hash_ax_tree(ax_data),  # same hash -> ax raw=0.0
            menu_selector="nav.main",
            search_selector="#search",
            content_selectors={
                "title": "h1.title",
                "price": ".price",
            },
        )

        kb = MockKB(tmp_path)
        kb._profiles["test.com"] = profile

        # 2 out of 4 selectors alive, 2 dead
        browser = MockBrowser(
            query_results={
                "nav.main": ["<nav>"],
                "#search": ["<input>"],
                # "h1.title" and ".price" missing -> dead
            },
            ax_snapshot=ax_data,
        )
        detector = ChangeDetector()
        result = await detector.detect("test.com", browser, kb)  # type: ignore[arg-type]

        # 2 dead / 4 total = 0.5 raw -> 0.5 * 0.5 (weight) = 0.25
        # + ax_tree: 0.0 * 0.3 = 0.0
        # + api: 0.0 * 0.2 = 0.0
        # combined = 0.25 -> >= THRESHOLD_PATCH (0.20), < THRESHOLD_RECON (0.45)
        assert THRESHOLD_PATCH <= result.score < THRESHOLD_RECON
        assert result.action == "patch"
        assert result.needs_patch is True

    @pytest.mark.asyncio
    async def test_ax_tree_hash_match(self, tmp_path: Path) -> None:
        """AX tree hash matches stored -> raw=0.0."""
        ax_data = {"role": "page", "children": [{"role": "heading", "name": "Title"}]}
        profile = self._make_profile(ax_hash=_hash_ax_tree(ax_data))

        kb = MockKB(tmp_path)
        kb._profiles["test.com"] = profile

        browser = MockBrowser(ax_snapshot=ax_data)
        detector = ChangeDetector()
        result = await detector.detect("test.com", browser, kb)  # type: ignore[arg-type]

        # Find the ax_tree_diff signal
        ax_signal = next(
            s for s in result.signal_details if s.name == "ax_tree_diff"
        )
        assert ax_signal.raw_score == 0.0
        assert ax_signal.weighted_score == 0.0

    @pytest.mark.asyncio
    async def test_ax_tree_hash_mismatch(self, tmp_path: Path) -> None:
        """AX tree hash differs from stored -> raw=1.0."""
        stored_ax = {"role": "page", "children": [{"role": "button"}]}
        current_ax = {"role": "page", "children": [{"role": "link"}, {"role": "img"}]}
        profile = self._make_profile(ax_hash=_hash_ax_tree(stored_ax))

        kb = MockKB(tmp_path)
        kb._profiles["test.com"] = profile

        browser = MockBrowser(ax_snapshot=current_ax)
        detector = ChangeDetector()
        result = await detector.detect("test.com", browser, kb)  # type: ignore[arg-type]

        ax_signal = next(
            s for s in result.signal_details if s.name == "ax_tree_diff"
        )
        assert ax_signal.raw_score == 1.0
        assert ax_signal.weighted_score == pytest.approx(0.3)  # 1.0 * 0.3

    @pytest.mark.asyncio
    async def test_no_stored_ax_hash(self, tmp_path: Path) -> None:
        """No stored ax_hash -> raw=0.3 (minor uncertainty penalty)."""
        profile = self._make_profile(ax_hash=None)

        kb = MockKB(tmp_path)
        kb._profiles["test.com"] = profile

        browser = MockBrowser()
        detector = ChangeDetector()
        result = await detector.detect("test.com", browser, kb)  # type: ignore[arg-type]

        ax_signal = next(
            s for s in result.signal_details if s.name == "ax_tree_diff"
        )
        assert ax_signal.raw_score == pytest.approx(0.3)
        assert ax_signal.weighted_score == pytest.approx(0.3 * 0.3)  # 0.09

    @pytest.mark.asyncio
    async def test_combined_3_signal_weighted_score(self, tmp_path: Path) -> None:
        """Verify combined score = sum of weighted signal scores."""
        # Scenario: half selectors dead, ax hash mismatch, no API data
        stored_ax = {"old": True}
        current_ax = {"new": True}
        profile = self._make_profile(
            ax_hash=_hash_ax_tree(stored_ax),
            menu_selector="nav.main",
            search_selector="#search",
        )

        kb = MockKB(tmp_path)
        kb._profiles["test.com"] = profile

        # 1 out of 2 selectors dead
        browser = MockBrowser(
            query_results={"nav.main": ["<nav>"]},  # #search is dead
            ax_snapshot=current_ax,
        )
        detector = ChangeDetector()
        result = await detector.detect("test.com", browser, kb)  # type: ignore[arg-type]

        # Verify: combined = sum of all weighted_scores
        expected_combined = sum(s.weighted_score for s in result.signal_details)
        assert result.score == pytest.approx(
            min(1.0, max(0.0, expected_combined))
        )

        # Selector: 1/2 dead = 0.5 raw * 0.5 weight = 0.25
        sel_signal = next(
            s for s in result.signal_details if s.name == "selector_survival"
        )
        assert sel_signal.raw_score == pytest.approx(0.5)
        assert sel_signal.weighted_score == pytest.approx(0.25)

        # AX: mismatch = 1.0 raw * 0.3 weight = 0.3
        ax_signal = next(
            s for s in result.signal_details if s.name == "ax_tree_diff"
        )
        assert ax_signal.raw_score == 1.0
        assert ax_signal.weighted_score == pytest.approx(0.3)


# ========================================================================
# PromptOptimizer Tests
# ========================================================================


class TestPromptOptimizer:
    """Tests for prompt optimization via heuristic LLM refinement."""

    def _write_runs_jsonl(
        self, kb: MockKB, domain: str, runs: list[dict[str, Any]]
    ) -> None:
        """Write run records to KB's runs.jsonl file."""
        history_dir = kb.base_dir / domain / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        runs_file = history_dir / "runs.jsonl"
        with runs_file.open("w") as f:
            for r in runs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    @pytest.mark.asyncio
    async def test_insufficient_runs_skip(self, tmp_path: Path) -> None:
        """Fewer than min_runs -> method='skip', optimized=False."""
        kb = MockKB(tmp_path)
        llm = MockLLM()
        # Write only 5 runs (below default _MIN_RUNS=25)
        self._write_runs_jsonl(kb, "test.com", [
            {"success": True, "task": f"task-{i}"} for i in range(5)
        ])

        optimizer = PromptOptimizer(min_runs=25)
        result = await optimizer.optimize("test.com", "/search*", kb, llm)  # type: ignore[arg-type]

        assert result.optimized is False
        assert result.method == "skip"
        assert "5 runs" in result.detail
        assert "25" in result.detail
        assert len(llm.calls) == 0

    @pytest.mark.asyncio
    async def test_heuristic_optimization_success(self, tmp_path: Path) -> None:
        """Heuristic optimization: LLM returns improved prompt -> saved."""
        kb = MockKB(tmp_path)
        kb.save_prompts("test.com", "/search*", {"task": "original prompt"})

        llm = MockLLM(response=json.dumps({
            "improved_prompt": "Better prompt with clearer steps",
            "changes": ["Added explicit wait", "Clearer selectors"],
            "expected_improvement": "20% fewer timeouts",
        }))

        # Write 30 runs (above threshold)
        runs = [
            {"success": i % 3 != 0, "task": f"search task {i}",
             "failure_type": "timeout" if i % 3 == 0 else ""}
            for i in range(30)
        ]
        self._write_runs_jsonl(kb, "test.com", runs)

        optimizer = PromptOptimizer(min_runs=25)
        result = await optimizer.optimize("test.com", "/search*", kb, llm)  # type: ignore[arg-type]

        assert result.optimized is True
        assert result.method == "heuristic"
        assert result.new_prompt_version is not None
        assert len(llm.calls) == 1
        # Verify the prompt was saved
        saved_prompts = kb.load_prompts("test.com", "/search*")
        assert saved_prompts is not None
        assert saved_prompts["task"] == "Better prompt with clearer steps"

    @pytest.mark.asyncio
    async def test_heuristic_optimization_llm_parse_failure(
        self, tmp_path: Path
    ) -> None:
        """Heuristic: LLM returns garbage -> optimized=False."""
        kb = MockKB(tmp_path)
        llm = MockLLM(response="I can't help with that.")

        runs = [{"success": True, "task": f"task-{i}"} for i in range(30)]
        self._write_runs_jsonl(kb, "test.com", runs)

        optimizer = PromptOptimizer(min_runs=25)
        result = await optimizer.optimize("test.com", "/search*", kb, llm)  # type: ignore[arg-type]

        assert result.optimized is False
        assert result.method == "heuristic"
        assert "did not produce" in result.detail

    def test_success_rate_calculation(self) -> None:
        """_compute_success_rate correctly counts successes."""
        runs = [
            {"success": True},
            {"success": True},
            {"success": False},
            {"success": True},
            {"success": False},
        ]
        rate = _compute_success_rate(runs)
        assert rate == pytest.approx(0.6)

    def test_success_rate_empty(self) -> None:
        """_compute_success_rate with empty list returns 0.0."""
        assert _compute_success_rate([]) == 0.0

    def test_failure_summary_aggregation(self) -> None:
        """_summarize_failures counts failure types and sorts by frequency."""
        failures = [
            {"failure_type": "timeout"},
            {"failure_type": "selector_not_found"},
            {"failure_type": "timeout"},
            {"failure_type": "timeout"},
            {"failure_type": "selector_not_found"},
            {"failure_type": "obstacle_blocked"},
        ]
        summary = _summarize_failures(failures)

        assert "timeout=3" in summary
        assert "selector_not_found=2" in summary
        assert "obstacle_blocked=1" in summary
        # timeout should appear first (highest count)
        assert summary.index("timeout") < summary.index("selector_not_found")

    @pytest.mark.asyncio
    async def test_run_history_loading_empty_directory(
        self, tmp_path: Path
    ) -> None:
        """No runs.jsonl file -> empty list, optimizer skips."""
        kb = MockKB(tmp_path)
        llm = MockLLM()

        # Don't create the history directory at all
        optimizer = PromptOptimizer(min_runs=25)
        result = await optimizer.optimize("empty.com", "/", kb, llm)  # type: ignore[arg-type]

        assert result.optimized is False
        assert result.method == "skip"
        assert "0 runs" in result.detail
