"""Unit tests for v4 runtime system (Phase 3).

Covers BundleExecutor, ResultVerifier, and RuntimeWorkflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.models.bundle import GeneratedBundle
from src.models.failure import FailureType
from src.runtime.executor import BundleExecutor
from src.runtime.verifier import (
    ExpectedOutcome,
    ResultVerifier,
)
from src.runtime.workflow import RuntimeWorkflow

# ── Mock Objects ──


class FakeElement:
    """Fake DOM element returned by query_selector."""

    def __init__(self, text: str = "found") -> None:
        self.text = text

    async def text_content(self) -> str:
        return self.text


class FakePage:
    """Fake Playwright page implementing PageLike protocol."""

    def __init__(
        self,
        *,
        current_url: str = "https://example.com",
        screenshot_bytes: bytes = b"fake-png-bytes",
        query_result: Any = None,
        evaluate_return: Any = None,
        evaluate_side_effects: list[Any] | None = None,
        goto_error: Exception | None = None,
        click_error: Exception | None = None,
        fill_error: Exception | None = None,
        query_selector_side_effects: list[Any] | None = None,
        wait_for_selector_error: Exception | None = None,
    ) -> None:
        self._url = current_url
        self._screenshot_bytes = screenshot_bytes
        self._query_result = query_result
        self._evaluate_return = evaluate_return
        self._evaluate_side_effects = evaluate_side_effects
        self._evaluate_call_idx = 0
        self._goto_error = goto_error
        self._click_error = click_error
        self._fill_error = fill_error
        self._query_selector_side_effects = query_selector_side_effects
        self._query_call_idx = 0
        self._wait_for_selector_error = wait_for_selector_error

        # Call tracking
        self.goto_calls: list[tuple[str, dict[str, Any]]] = []
        self.click_calls: list[tuple[str, dict[str, Any]]] = []
        self.fill_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.hover_calls: list[tuple[str, dict[str, Any]]] = []
        self.press_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.select_option_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.type_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.screenshot_calls: int = 0
        self.wait_for_timeout_calls: list[float] = []
        self.evaluate_calls: list[str] = []
        self.query_selector_calls: list[str] = []
        self.query_selector_all_calls: list[str] = []
        self.wait_for_selector_calls: list[tuple[str, dict[str, Any]]] = []

    @property
    def url(self) -> str:
        return self._url

    async def goto(self, url: str, **kwargs: Any) -> Any:
        self.goto_calls.append((url, kwargs))
        if self._goto_error:
            raise self._goto_error
        self._url = url
        return None

    async def click(self, selector: str, **kwargs: Any) -> None:
        self.click_calls.append((selector, kwargs))
        if self._click_error:
            raise self._click_error

    async def fill(self, selector: str, value: str, **kwargs: Any) -> None:
        self.fill_calls.append((selector, value, kwargs))
        if self._fill_error:
            raise self._fill_error

    async def hover(self, selector: str, **kwargs: Any) -> None:
        self.hover_calls.append((selector, kwargs))

    async def press(self, selector: str, key: str, **kwargs: Any) -> None:
        self.press_calls.append((selector, key, kwargs))

    async def select_option(
        self, selector: str, value: str, **kwargs: Any
    ) -> Any:
        self.select_option_calls.append((selector, value, kwargs))
        return None

    async def type(self, selector: str, text: str, **kwargs: Any) -> None:
        self.type_calls.append((selector, text, kwargs))

    async def screenshot(self, **kwargs: Any) -> bytes:
        self.screenshot_calls += 1
        return self._screenshot_bytes

    async def wait_for_timeout(self, timeout: float) -> None:
        self.wait_for_timeout_calls.append(timeout)

    async def wait_for_selector(self, selector: str, **kwargs: Any) -> Any:
        self.wait_for_selector_calls.append((selector, kwargs))
        if self._wait_for_selector_error:
            raise self._wait_for_selector_error
        return self._query_result

    async def query_selector(self, selector: str) -> Any:
        self.query_selector_calls.append(selector)
        if self._query_selector_side_effects is not None:
            idx = self._query_call_idx
            self._query_call_idx += 1
            val = self._query_selector_side_effects[
                idx % len(self._query_selector_side_effects)
            ]
            if isinstance(val, Exception):
                raise val
            return val
        return self._query_result

    async def query_selector_all(self, selector: str) -> list[Any]:
        self.query_selector_all_calls.append(selector)
        return []

    async def evaluate(self, expression: str) -> Any:
        self.evaluate_calls.append(expression)
        if self._evaluate_side_effects is not None:
            idx = self._evaluate_call_idx
            self._evaluate_call_idx += 1
            val = self._evaluate_side_effects[
                idx % len(self._evaluate_side_effects)
            ]
            if isinstance(val, Exception):
                raise val
            return val
        return self._evaluate_return


class FakeBrowser:
    """Fake browser implementing BrowserLike protocol."""

    def __init__(self, page: FakePage | None = None) -> None:
        self.page = page or FakePage()

    async def get_page(self) -> FakePage:
        return self.page


@dataclass
class FakeCacheLookupResult:
    """Fake CacheLookupResult for KB mock."""

    hit: bool = False
    stage: str = "cold"
    reason: str = ""
    profile: Any = None
    workflow: dict[str, Any] | None = None
    prompts: dict[str, str] | None = None


class FakeKBManager:
    """Fake KBManager for RuntimeWorkflow tests."""

    def __init__(
        self,
        lookup_result: FakeCacheLookupResult | None = None,
    ) -> None:
        self._lookup_result = lookup_result or FakeCacheLookupResult()
        self.appended_runs: list[tuple[str, dict[str, Any]]] = []

    def lookup(self, domain: str, url: str) -> FakeCacheLookupResult:
        return self._lookup_result

    def append_run(self, domain: str, record: dict[str, Any]) -> None:
        self.appended_runs.append((domain, record))


class FakeMaturity:
    """Fake MaturityState for tracking record_run calls."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []

    def record_run(self, *, success: bool, llm_calls: int) -> None:
        self.runs.append({"success": success, "llm_calls": llm_calls})


# ── Helper ──


def _make_bundle(steps: list[dict[str, Any]], version: int = 1) -> GeneratedBundle:
    """Build a GeneratedBundle from step list."""
    return GeneratedBundle(
        workflow_dsl={"steps": steps, "version": version},
        strategy="dom_only",
        version=version,
    )


# ════════════════════════════════════════════════════════════════════
# BundleExecutor Tests
# ════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_execute_empty_steps_succeeds() -> None:
    """Empty steps list returns success=True immediately."""
    executor = BundleExecutor()
    bundle = _make_bundle([])
    browser = FakeBrowser()

    result = await executor.execute(bundle, browser, "empty task")

    assert result.success is True
    assert result.total_steps == 0
    assert result.steps_completed == 0
    assert result.error is None


@pytest.mark.asyncio
async def test_execute_goto_action() -> None:
    """Goto action calls page.goto with the value URL."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "goto", "value": "https://target.com/page"},
    ])
    page = FakePage()
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "goto task")

    assert result.success is True
    assert result.steps_completed == 1
    assert len(page.goto_calls) == 1
    assert page.goto_calls[0][0] == "https://target.com/page"
    assert page.goto_calls[0][1].get("wait_until") == "domcontentloaded"


@pytest.mark.asyncio
async def test_execute_click_action_with_selector_resolution() -> None:
    """Click action resolves selector and calls page.click."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "click", "selector": "#btn-submit"},
    ])
    page = FakePage(query_result=FakeElement())
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "click task")

    assert result.success is True
    assert result.steps_completed == 1
    assert len(page.click_calls) == 1
    assert page.click_calls[0][0] == "#btn-submit"


@pytest.mark.asyncio
async def test_execute_fill_action() -> None:
    """Fill action resolves selector and calls page.fill with value."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "fill", "selector": "input#email", "value": "test@example.com"},
    ])
    page = FakePage(query_result=FakeElement())
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "fill task")

    assert result.success is True
    assert len(page.fill_calls) == 1
    assert page.fill_calls[0][0] == "input#email"
    assert page.fill_calls[0][1] == "test@example.com"


@pytest.mark.asyncio
async def test_execute_screenshot_action_captures_bytes() -> None:
    """Screenshot action captures bytes and appends to result.screenshots."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "screenshot"},
    ])
    page = FakePage(screenshot_bytes=b"screenshot-data-123")
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "screenshot task")

    assert result.success is True
    assert len(result.screenshots) == 1
    assert result.screenshots[0] == b"screenshot-data-123"
    assert page.screenshot_calls == 1


@pytest.mark.asyncio
async def test_execute_scroll_down() -> None:
    """Scroll down evaluates positive window.scrollBy."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "scroll", "value": "down", "pixels": 800},
    ])
    page = FakePage()
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "scroll down")

    assert result.success is True
    assert len(page.evaluate_calls) == 1
    assert "scrollBy(0, 800)" in page.evaluate_calls[0]


@pytest.mark.asyncio
async def test_execute_scroll_up() -> None:
    """Scroll up evaluates negative window.scrollBy."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "scroll", "value": "up", "pixels": 300},
    ])
    page = FakePage()
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "scroll up")

    assert result.success is True
    assert len(page.evaluate_calls) == 1
    assert "scrollBy(0, -300)" in page.evaluate_calls[0]


@pytest.mark.asyncio
async def test_execute_wait_action_with_custom_ms() -> None:
    """Wait action calls wait_for_timeout with custom milliseconds."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "wait", "value": "5000"},
    ])
    page = FakePage()
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "wait task")

    assert result.success is True
    assert len(page.wait_for_timeout_calls) == 1
    assert page.wait_for_timeout_calls[0] == 5000.0


@pytest.mark.asyncio
async def test_execute_unknown_action_skipped() -> None:
    """Unknown action is skipped with a warning, execution continues."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "teleport", "selector": "#nowhere"},
        {"action": "goto", "value": "https://example.com"},
    ])
    page = FakePage()
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "unknown action")

    assert result.success is True
    # Only goto step counts as completed (step index 1)
    assert result.steps_completed == 2
    # goto was actually called
    assert len(page.goto_calls) == 1


@pytest.mark.asyncio
async def test_selector_resolution_primary_found() -> None:
    """Primary selector found on first query_selector check."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {
            "action": "click",
            "selector": "#primary-btn",
            "fallback_selectors": [".fallback-btn"],
        },
    ])
    page = FakePage(query_result=FakeElement())
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "primary found")

    assert result.success is True
    # Click called with primary selector
    assert page.click_calls[0][0] == "#primary-btn"


@pytest.mark.asyncio
async def test_selector_resolution_fallback_found() -> None:
    """Primary missing, fallback selector resolves successfully."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {
            "action": "click",
            "selector": "#missing-primary",
            "fallback_selectors": [".fallback-btn"],
        },
    ])
    # Primary returns None, fallback returns element
    page = FakePage(
        query_selector_side_effects=[None, FakeElement()],
        wait_for_selector_error=TimeoutError("primary timeout"),
    )
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "fallback found")

    assert result.success is True
    # Click called with fallback selector
    assert page.click_calls[0][0] == ".fallback-btn"


@pytest.mark.asyncio
async def test_selector_resolution_all_missing_raises() -> None:
    """All selectors missing raises RuntimeError with failure evidence."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {
            "action": "click",
            "selector": "#gone",
            "fallback_selectors": [".also-gone"],
        },
    ])
    # Both query_selector return None, wait_for_selector also fails
    page = FakePage(
        query_selector_side_effects=[None, None],
        wait_for_selector_error=TimeoutError("all missing"),
    )
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "all missing")

    assert result.success is False
    assert result.error is not None
    assert "not found" in result.error.lower() or "Selector" in result.error
    assert result.failure_evidence is not None
    assert result.failure_evidence.failure_type == FailureType.SELECTOR_NOT_FOUND


@pytest.mark.asyncio
async def test_step_exception_populates_failure_evidence() -> None:
    """Exception during step execution populates failure_evidence on result."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "click", "selector": "#crash"},
    ])
    page = FakePage(
        query_result=FakeElement(),
        click_error=RuntimeError("Element not interactable"),
    )
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "crash task")

    assert result.success is False
    assert result.failure_evidence is not None
    assert result.failure_evidence.error_message == "Element not interactable"
    assert result.failure_evidence.url == "https://example.com"
    assert result.failure_evidence.selector == "#crash"
    assert result.error is not None
    assert "Step 0" in result.error


@pytest.mark.asyncio
async def test_execution_duration_tracking() -> None:
    """Duration is tracked in milliseconds for both success and failure."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "goto", "value": "https://example.com"},
    ])
    browser = FakeBrowser()

    result = await executor.execute(bundle, browser, "duration task")

    assert result.success is True
    assert result.duration_ms >= 0.0


# ════════════════════════════════════════════════════════════════════
# ResultVerifier Tests
# ════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_url_check_regex_match_passed() -> None:
    """URL regex pattern matches current page URL."""
    verifier = ResultVerifier()
    expected = ExpectedOutcome(url_pattern=r"example\.com/results\?q=")
    page = FakePage(current_url="https://example.com/results?q=shoes")
    browser = FakeBrowser(page)

    result = await verifier.verify(expected, browser)

    assert result.passed is True
    assert len(result.checks) == 1
    assert result.checks[0].mode == "url"
    assert result.checks[0].passed is True


@pytest.mark.asyncio
async def test_url_check_no_match_failed() -> None:
    """URL pattern does not match current URL."""
    verifier = ResultVerifier()
    expected = ExpectedOutcome(url_pattern=r"checkout\.example\.com")
    page = FakePage(current_url="https://example.com/cart")
    browser = FakeBrowser(page)

    result = await verifier.verify(expected, browser)

    assert result.passed is False
    assert len(result.checks) == 1
    assert result.checks[0].mode == "url"
    assert result.checks[0].passed is False
    assert "does not match" in result.checks[0].detail


@pytest.mark.asyncio
async def test_dom_check_selector_found_no_text() -> None:
    """DOM selector exists, no text check required — passes."""
    verifier = ResultVerifier()
    expected = ExpectedOutcome(dom_selector=".result-list")
    page = FakePage(query_result=FakeElement())
    browser = FakeBrowser(page)

    result = await verifier.verify(expected, browser)

    assert result.passed is True
    assert len(result.checks) == 1
    assert result.checks[0].mode == "dom"
    assert result.checks[0].passed is True
    assert result.checks[0].actual == "(found)"


@pytest.mark.asyncio
async def test_dom_check_selector_found_text_matches() -> None:
    """DOM selector found and text content matches expected."""
    verifier = ResultVerifier()
    expected = ExpectedOutcome(
        dom_selector=".title",
        dom_text="Welcome",
    )
    page = FakePage(
        query_result=FakeElement(),
        evaluate_return="Welcome to our site!",
    )
    browser = FakeBrowser(page)

    result = await verifier.verify(expected, browser)

    assert result.passed is True
    assert result.checks[0].mode == "dom"
    assert result.checks[0].passed is True


@pytest.mark.asyncio
async def test_dom_check_selector_not_found_failed() -> None:
    """DOM selector does not exist on page."""
    verifier = ResultVerifier()
    expected = ExpectedOutcome(dom_selector=".nonexistent")
    page = FakePage(
        query_result=None,
        wait_for_selector_error=TimeoutError("not found"),
    )
    browser = FakeBrowser(page)

    result = await verifier.verify(expected, browser)

    assert result.passed is False
    assert result.checks[0].mode == "dom"
    assert result.checks[0].passed is False
    assert "not found" in result.checks[0].detail


@pytest.mark.asyncio
async def test_network_check_matching_resource_passed() -> None:
    """Network resource matching URL pattern found."""
    verifier = ResultVerifier()
    expected = ExpectedOutcome(network_url_pattern="/api/search")
    page = FakePage(
        evaluate_return=[
            {"url": "https://example.com/api/search?q=test", "status": 200, "duration": 50}
        ],
    )
    browser = FakeBrowser(page)

    result = await verifier.verify(expected, browser)

    assert result.passed is True
    assert result.checks[0].mode == "network"
    assert result.checks[0].passed is True


@pytest.mark.asyncio
async def test_no_checks_specified_passes() -> None:
    """No fields populated in ExpectedOutcome passes by default."""
    verifier = ResultVerifier()
    expected = ExpectedOutcome()
    browser = FakeBrowser()

    result = await verifier.verify(expected, browser)

    assert result.passed is True
    assert result.checks == []
    assert result.reason == "no_checks_specified"


@pytest.mark.asyncio
async def test_multiple_checks_mixed_results() -> None:
    """Multiple checks — one passes, one fails -> overall fails."""
    verifier = ResultVerifier()
    expected = ExpectedOutcome(
        url_pattern=r"example\.com",  # will pass
        dom_selector=".missing-element",  # will fail
    )
    page = FakePage(
        current_url="https://example.com/page",
        query_result=None,
        wait_for_selector_error=TimeoutError("not found"),
    )
    browser = FakeBrowser(page)

    result = await verifier.verify(expected, browser)

    assert result.passed is False
    assert len(result.checks) == 2
    # URL check passed
    url_check = next(c for c in result.checks if c.mode == "url")
    assert url_check.passed is True
    # DOM check failed
    dom_check = next(c for c in result.checks if c.mode == "dom")
    assert dom_check.passed is False
    # Reason includes only the failed check
    assert "dom" in result.reason


# ════════════════════════════════════════════════════════════════════
# RuntimeWorkflow Tests
# ════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_workflow_kb_miss_error_with_stage() -> None:
    """KB miss returns error indicating codegen is required."""
    kb = FakeKBManager(
        lookup_result=FakeCacheLookupResult(
            hit=False, stage="cold", reason="no_profile"
        )
    )
    browser = FakeBrowser()
    workflow = RuntimeWorkflow()

    result = await workflow.run(
        domain="unknown.com",
        url="https://unknown.com/page",
        task="test task",
        browser=browser,
        kb=kb,  # type: ignore[arg-type]
    )

    assert result.success is False
    assert result.stage == "cold"
    assert result.error is not None
    assert "KB miss" in result.error
    assert "codegen" in result.error.lower()


@pytest.mark.asyncio
async def test_workflow_kb_hit_execution_success() -> None:
    """KB hit with valid workflow executes and succeeds."""
    workflow_dsl = {
        "steps": [
            {"action": "goto", "value": "https://shop.com"},
        ],
        "version": 3,
        "strategy": "dom_only",
    }
    kb = FakeKBManager(
        lookup_result=FakeCacheLookupResult(
            hit=True,
            stage="warm",
            reason="workflow_only",
            workflow=workflow_dsl,
        )
    )
    page = FakePage()
    browser = FakeBrowser(page)
    workflow = RuntimeWorkflow()

    result = await workflow.run(
        domain="shop.com",
        url="https://shop.com/products",
        task="navigate to shop",
        browser=browser,
        kb=kb,  # type: ignore[arg-type]
    )

    assert result.success is True
    assert result.stage == "warm"
    assert result.bundle_version == 3
    assert result.execution is not None
    assert result.execution.success is True


@pytest.mark.asyncio
async def test_workflow_execution_failure_with_evidence() -> None:
    """Execution failure propagates error and failure_evidence."""
    workflow_dsl = {
        "steps": [
            {"action": "click", "selector": "#broken"},
        ],
        "version": 1,
        "strategy": "dom_only",
    }
    kb = FakeKBManager(
        lookup_result=FakeCacheLookupResult(
            hit=True,
            stage="warm",
            reason="workflow_only",
            workflow=workflow_dsl,
        )
    )
    # Selector not found
    page = FakePage(
        query_selector_side_effects=[None],
        wait_for_selector_error=TimeoutError("timeout"),
    )
    browser = FakeBrowser(page)
    workflow = RuntimeWorkflow()

    result = await workflow.run(
        domain="broken.com",
        url="https://broken.com/page",
        task="click broken",
        browser=browser,
        kb=kb,  # type: ignore[arg-type]
    )

    assert result.success is False
    assert result.error is not None
    assert result.failure_evidence is not None
    assert result.execution is not None
    assert result.execution.success is False


@pytest.mark.asyncio
async def test_workflow_verification_failure() -> None:
    """Execution succeeds but verification fails returns error."""
    workflow_dsl = {
        "steps": [
            {"action": "goto", "value": "https://shop.com"},
        ],
        "version": 1,
        "strategy": "dom_only",
    }
    kb = FakeKBManager(
        lookup_result=FakeCacheLookupResult(
            hit=True,
            stage="warm",
            reason="workflow_only",
            workflow=workflow_dsl,
        )
    )
    page = FakePage(current_url="https://shop.com")
    browser = FakeBrowser(page)
    expected = ExpectedOutcome(url_pattern=r"checkout\.example\.com")
    workflow = RuntimeWorkflow()

    result = await workflow.run(
        domain="shop.com",
        url="https://shop.com/products",
        task="navigate",
        browser=browser,
        kb=kb,  # type: ignore[arg-type]
        expected=expected,
    )

    assert result.success is False
    assert result.error is not None
    assert "Verification failed" in result.error
    assert result.failure_evidence is not None
    assert result.failure_evidence.failure_type == FailureType.VERIFICATION_FAILED
    assert result.verification is not None
    assert result.verification.passed is False


@pytest.mark.asyncio
async def test_workflow_verification_skipped_when_none() -> None:
    """No expected outcome skips verification -> success."""
    workflow_dsl = {
        "steps": [
            {"action": "goto", "value": "https://shop.com"},
        ],
        "version": 2,
        "strategy": "dom_only",
    }
    kb = FakeKBManager(
        lookup_result=FakeCacheLookupResult(
            hit=True,
            stage="hot",
            reason="full_cache",
            workflow=workflow_dsl,
        )
    )
    browser = FakeBrowser()
    workflow = RuntimeWorkflow()

    result = await workflow.run(
        domain="shop.com",
        url="https://shop.com/",
        task="open shop",
        browser=browser,
        kb=kb,  # type: ignore[arg-type]
        expected=None,
    )

    assert result.success is True
    assert result.verification is None


@pytest.mark.asyncio
async def test_workflow_run_recorded_at_every_exit() -> None:
    """Run is recorded to KB at every exit point (miss, fail, success)."""
    # Test 1: KB miss
    kb_miss = FakeKBManager(
        lookup_result=FakeCacheLookupResult(hit=False, stage="cold", reason="no_profile")
    )
    wf = RuntimeWorkflow()
    await wf.run("d.com", "https://d.com", "t", FakeBrowser(), kb_miss)  # type: ignore[arg-type]
    assert len(kb_miss.appended_runs) == 1
    assert kb_miss.appended_runs[0][0] == "d.com"
    assert kb_miss.appended_runs[0][1]["success"] is False

    # Test 2: Execution success
    kb_hit = FakeKBManager(
        lookup_result=FakeCacheLookupResult(
            hit=True, stage="warm", reason="ok",
            workflow={"steps": [], "version": 1, "strategy": "dom_only"},
        )
    )
    await wf.run("d.com", "https://d.com", "t", FakeBrowser(), kb_hit)  # type: ignore[arg-type]
    assert len(kb_hit.appended_runs) == 1
    assert kb_hit.appended_runs[0][1]["success"] is True

    # Test 3: Execution failure
    kb_fail = FakeKBManager(
        lookup_result=FakeCacheLookupResult(
            hit=True, stage="warm", reason="ok",
            workflow={
                "steps": [{"action": "click", "selector": "#x"}],
                "version": 1,
                "strategy": "dom_only",
            },
        )
    )
    page_fail = FakePage(
        query_selector_side_effects=[None],
        wait_for_selector_error=TimeoutError("gone"),
    )
    await wf.run(
        "d.com", "https://d.com", "t",
        FakeBrowser(page_fail),
        kb_fail,  # type: ignore[arg-type]
    )
    assert len(kb_fail.appended_runs) == 1
    assert kb_fail.appended_runs[0][1]["success"] is False


@pytest.mark.asyncio
async def test_workflow_bundle_version_from_kb() -> None:
    """Bundle version is extracted from KB workflow data."""
    workflow_dsl = {
        "steps": [],
        "version": 7,
        "strategy": "dom_with_objdet_backup",
    }
    kb = FakeKBManager(
        lookup_result=FakeCacheLookupResult(
            hit=True,
            stage="hot",
            reason="full_cache",
            workflow=workflow_dsl,
        )
    )
    wf = RuntimeWorkflow()

    result = await wf.run(
        domain="versioned.com",
        url="https://versioned.com/",
        task="check version",
        browser=FakeBrowser(),
        kb=kb,  # type: ignore[arg-type]
    )

    assert result.success is True
    assert result.bundle_version == 7


@pytest.mark.asyncio
async def test_workflow_maturity_updated_on_success() -> None:
    """MaturityState.record_run called with success=True on success."""
    workflow_dsl = {
        "steps": [{"action": "goto", "value": "https://m.com"}],
        "version": 1,
        "strategy": "dom_only",
    }
    kb = FakeKBManager(
        lookup_result=FakeCacheLookupResult(
            hit=True, stage="warm", reason="ok", workflow=workflow_dsl,
        )
    )
    maturity = FakeMaturity()
    wf = RuntimeWorkflow()

    result = await wf.run(
        domain="m.com",
        url="https://m.com/",
        task="maturity test",
        browser=FakeBrowser(),
        kb=kb,  # type: ignore[arg-type]
        maturity=maturity,  # type: ignore[arg-type]
    )

    assert result.success is True
    assert len(maturity.runs) == 1
    assert maturity.runs[0]["success"] is True
    assert maturity.runs[0]["llm_calls"] == 0


@pytest.mark.asyncio
async def test_workflow_maturity_updated_on_failure() -> None:
    """MaturityState.record_run called with success=False on failure."""
    kb = FakeKBManager(
        lookup_result=FakeCacheLookupResult(
            hit=False, stage="cold", reason="no_profile",
        )
    )
    maturity = FakeMaturity()
    wf = RuntimeWorkflow()

    result = await wf.run(
        domain="cold.com",
        url="https://cold.com/",
        task="cold test",
        browser=FakeBrowser(),
        kb=kb,  # type: ignore[arg-type]
        maturity=maturity,  # type: ignore[arg-type]
    )

    assert result.success is False
    assert len(maturity.runs) == 1
    assert maturity.runs[0]["success"] is False


# ── Executor edge case tests ──


@pytest.mark.asyncio
async def test_execute_goto_uses_selector_as_url_fallback() -> None:
    """Goto action falls back to selector when value is empty."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "goto", "selector": "https://fallback-url.com"},
    ])
    page = FakePage()
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "goto fallback")

    assert result.success is True
    assert page.goto_calls[0][0] == "https://fallback-url.com"


@pytest.mark.asyncio
async def test_execute_wait_default_ms() -> None:
    """Wait action without value uses default 2000ms."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "wait"},
    ])
    page = FakePage()
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "default wait")

    assert result.success is True
    assert page.wait_for_timeout_calls[0] == 2000.0


@pytest.mark.asyncio
async def test_execute_hover_action() -> None:
    """Hover action calls page.hover with resolved selector."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "hover", "selector": ".menu-item"},
    ])
    page = FakePage(query_result=FakeElement())
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "hover task")

    assert result.success is True
    assert len(page.hover_calls) == 1
    assert page.hover_calls[0][0] == ".menu-item"


@pytest.mark.asyncio
async def test_execute_select_action() -> None:
    """Select action calls page.select_option."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "select", "selector": "select#color", "value": "red"},
    ])
    page = FakePage(query_result=FakeElement())
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "select task")

    assert result.success is True
    assert len(page.select_option_calls) == 1
    assert page.select_option_calls[0][0] == "select#color"
    assert page.select_option_calls[0][1] == "red"


@pytest.mark.asyncio
async def test_execute_press_action() -> None:
    """Press action calls page.press with key value."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "press", "selector": "input#search", "value": "Enter"},
    ])
    page = FakePage(query_result=FakeElement())
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "press task")

    assert result.success is True
    assert len(page.press_calls) == 1
    assert page.press_calls[0][0] == "input#search"
    assert page.press_calls[0][1] == "Enter"


@pytest.mark.asyncio
async def test_execute_press_default_enter() -> None:
    """Press action without value defaults to Enter."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "press", "selector": "input#q"},
    ])
    page = FakePage(query_result=FakeElement())
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "press default")

    assert result.success is True
    assert page.press_calls[0][1] == "Enter"


@pytest.mark.asyncio
async def test_failure_evidence_timeout_classification() -> None:
    """Timeout error classifies as FailureType.TIMEOUT."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "click", "selector": "#slow"},
    ])
    page = FakePage(
        query_result=FakeElement(),
        click_error=TimeoutError("Timeout 10000ms exceeded"),
    )
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "timeout task")

    assert result.success is False
    assert result.failure_evidence is not None
    assert result.failure_evidence.failure_type == FailureType.TIMEOUT


@pytest.mark.asyncio
async def test_failure_evidence_navigation_classification() -> None:
    """Navigation error classifies as FailureType.NAVIGATION_FAILED."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "goto", "value": "https://down.com"},
    ])
    page = FakePage(goto_error=RuntimeError("Navigation to https://down.com failed"))
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "nav failure")

    assert result.success is False
    assert result.failure_evidence is not None
    assert result.failure_evidence.failure_type == FailureType.NAVIGATION_FAILED


@pytest.mark.asyncio
async def test_scroll_default_pixels() -> None:
    """Scroll action uses default 500 pixels when not specified."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "scroll", "value": "down"},
    ])
    page = FakePage()
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "scroll default")

    assert result.success is True
    assert "scrollBy(0, 500)" in page.evaluate_calls[0]


@pytest.mark.asyncio
async def test_multi_step_execution() -> None:
    """Multiple steps execute in order and all complete."""
    executor = BundleExecutor()
    bundle = _make_bundle([
        {"action": "goto", "value": "https://shop.com"},
        {"action": "wait", "value": "1000"},
        {"action": "screenshot"},
        {"action": "scroll", "value": "down"},
    ])
    page = FakePage()
    browser = FakeBrowser(page)

    result = await executor.execute(bundle, browser, "multi step")

    assert result.success is True
    assert result.steps_completed == 4
    assert result.total_steps == 4
    assert len(result.screenshots) == 1
    assert len(page.goto_calls) == 1
    assert len(page.wait_for_timeout_calls) == 1


# ── Verifier edge case tests ──


@pytest.mark.asyncio
async def test_url_check_substring_fallback() -> None:
    """Invalid regex falls back to substring matching."""
    verifier = ResultVerifier()
    # "[" is invalid regex
    expected = ExpectedOutcome(url_pattern="example.com/page[")
    page = FakePage(current_url="https://example.com/page[1]")
    browser = FakeBrowser(page)

    result = await verifier.verify(expected, browser)

    assert result.passed is True
    assert result.checks[0].passed is True


@pytest.mark.asyncio
async def test_dom_text_case_insensitive() -> None:
    """DOM text check is case-insensitive."""
    verifier = ResultVerifier()
    expected = ExpectedOutcome(dom_selector=".msg", dom_text="SUCCESS")
    page = FakePage(
        query_result=FakeElement(),
        evaluate_return="Operation success completed",
    )
    browser = FakeBrowser(page)

    result = await verifier.verify(expected, browser)

    assert result.passed is True


@pytest.mark.asyncio
async def test_network_check_no_matching_requests() -> None:
    """No matching network requests returns failed."""
    verifier = ResultVerifier()
    expected = ExpectedOutcome(network_url_pattern="/api/checkout")
    page = FakePage(evaluate_return=[])
    browser = FakeBrowser(page)

    result = await verifier.verify(expected, browser)

    assert result.passed is False
    assert result.checks[0].detail is not None
    assert "No network request" in result.checks[0].detail


@pytest.mark.asyncio
async def test_network_check_status_mismatch() -> None:
    """Network request found but status code does not match."""
    verifier = ResultVerifier()
    expected = ExpectedOutcome(
        network_url_pattern="/api/data",
        network_status=200,
    )
    page = FakePage(
        evaluate_return=[
            {"url": "https://example.com/api/data", "status": 500, "duration": 100}
        ],
    )
    browser = FakeBrowser(page)

    result = await verifier.verify(expected, browser)

    assert result.passed is False
    assert "500" in result.checks[0].detail or "500" in result.checks[0].actual


@pytest.mark.asyncio
async def test_network_check_evaluate_error() -> None:
    """Network check handles evaluate exception gracefully."""
    verifier = ResultVerifier()
    expected = ExpectedOutcome(network_url_pattern="/api/test")
    page = FakePage(
        evaluate_side_effects=[RuntimeError("JS error")],
    )
    browser = FakeBrowser(page)

    result = await verifier.verify(expected, browser)

    assert result.passed is False
    assert "error" in result.checks[0].actual.lower()
