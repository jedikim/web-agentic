# LLM-First Orchestrator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a working LLM-First web automation engine and prove it on Naver Shopping (headful, real browser).

**Architecture:** New `LLMFirstOrchestrator` that inverts the flow to L→Cache→L+E→X→V. Reuses existing Executor, Extractor, Verifier, LLMPlanner modules. New SelectorCache wraps PatternDB. New `run_live.py` script drives headful E2E runs.

**Tech Stack:** Python 3.11+, Playwright (async, headful), Gemini Flash API, SQLite (PatternDB), pytest-asyncio

---

### Task 1: SelectorCache — thin PatternDB wrapper

**Files:**
- Create: `src/core/selector_cache.py`
- Test: `tests/unit/test_selector_cache.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_selector_cache.py
"""Tests for SelectorCache — thin wrapper over PatternDB."""
import pytest

from src.core.selector_cache import CacheHit, SelectorCache


@pytest.fixture
async def cache(tmp_path):
    c = SelectorCache(db_path=str(tmp_path / "test_cache.db"))
    await c.init()
    return c


@pytest.mark.asyncio
async def test_lookup_miss(cache):
    result = await cache.lookup("검색", "shopping.naver.com")
    assert result is None


@pytest.mark.asyncio
async def test_save_and_lookup(cache):
    await cache.save("검색", "shopping.naver.com", "#search-input", "type")
    hit = await cache.lookup("검색", "shopping.naver.com")
    assert hit is not None
    assert isinstance(hit, CacheHit)
    assert hit.selector == "#search-input"
    assert hit.method == "type"


@pytest.mark.asyncio
async def test_invalidate(cache):
    await cache.save("검색", "shopping.naver.com", "#search-input", "type")
    await cache.invalidate("검색", "shopping.naver.com")
    result = await cache.lookup("검색", "shopping.naver.com")
    # After invalidation, should not return the entry (fail_count increased)
    # PatternDB doesn't delete, it tracks failures. For cache purposes,
    # a pattern with more failures than successes should not be returned.
    assert result is None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_selector_cache.py -v`
Expected: FAIL (import error)

**Step 3: Write minimal implementation**

```python
# src/core/selector_cache.py
"""SelectorCache — thin wrapper over PatternDB for LLM-First caching.

Caches successful selectors so repeated runs skip LLM calls.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.learning.pattern_db import PatternDB

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheHit:
    """A cached selector lookup result."""
    selector: str
    method: str
    confidence: float


class SelectorCache:
    """Thin wrapper over PatternDB providing cache semantics.

    Args:
        db_path: SQLite database path.
        min_success: Minimum success count to trust a cached entry.
    """

    def __init__(
        self,
        db_path: str | Path = "data/patterns.db",
        min_success: int = 1,
    ) -> None:
        self._db = PatternDB(db_path)
        self._min_success = min_success

    async def init(self) -> None:
        """Initialize the underlying database."""
        await self._db.init_db()

    async def lookup(self, intent: str, site: str) -> CacheHit | None:
        """Look up a cached selector for the given intent and site.

        Returns None if no entry exists or the entry has too many failures.
        """
        pattern = await self._db.get_pattern(intent, site)
        if pattern is None:
            return None
        # Don't trust entries with more failures than successes
        if pattern.fail_count >= pattern.success_count:
            return None
        if pattern.success_count < self._min_success:
            return None
        ratio = pattern.success_count / max(pattern.success_count + pattern.fail_count, 1)
        return CacheHit(
            selector=pattern.selector,
            method=pattern.method,
            confidence=ratio,
        )

    async def save(
        self, intent: str, site: str, selector: str, method: str
    ) -> None:
        """Record a successful selector usage."""
        await self._db.record_success(intent, site, selector, method)
        logger.debug("Cached: %s @ %s -> %s (%s)", intent, site, selector, method)

    async def invalidate(self, intent: str, site: str) -> None:
        """Record a failure, reducing trust in cached entries."""
        pattern = await self._db.get_pattern(intent, site)
        if pattern is not None:
            await self._db.record_failure(intent, site, pattern.selector, pattern.method)
            logger.debug("Invalidated cache: %s @ %s", intent, site)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_selector_cache.py -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add src/core/selector_cache.py tests/unit/test_selector_cache.py
git commit -m "feat: add SelectorCache wrapping PatternDB for LLM-First caching"
```

---

### Task 2: Page-aware plan prompt for LLM

**Files:**
- Modify: `src/ai/prompt_manager.py` (add `plan_steps_with_context` prompt)
- Modify: `src/ai/llm_planner.py` (add `plan_with_context()` method)
- Test: `tests/unit/test_llm_planner.py` (add test for new method)

**Step 1: Write the failing test**

```python
# Add to tests/unit/test_llm_planner.py

@pytest.mark.asyncio
async def test_plan_with_context_calls_gemini(monkeypatch):
    """plan_with_context passes page URL/title to prompt."""
    captured_prompts = []

    async def mock_call(self, prompt, model):
        captured_prompts.append(prompt)
        return '{"steps": [{"step_id": "s1", "intent": "click search", "node_type": "action"}]}', 100

    monkeypatch.setattr(LLMPlanner, "_call_gemini", mock_call)
    planner = LLMPlanner(PromptManager(), api_key="fake")
    steps = await planner.plan_with_context(
        instruction="노트북 검색",
        page_url="https://shopping.naver.com",
        page_title="네이버쇼핑",
        visible_text_snippet="검색 쇼핑하우 럭셔리 ...",
    )
    assert len(steps) == 1
    assert "shopping.naver.com" in captured_prompts[0]
    assert "네이버쇼핑" in captured_prompts[0]
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_llm_planner.py::test_plan_with_context_calls_gemini -v`
Expected: FAIL (AttributeError: plan_with_context)

**Step 3: Implement**

Add to `src/ai/prompt_manager.py` `_BUILTIN_PROMPTS`:

```python
"plan_steps_with_context": {
    "v1": (
        "You are a web automation assistant. You are currently viewing a web page.\n\n"
        "Current page:\n"
        "- URL: $page_url\n"
        "- Title: $page_title\n"
        "- Visible text (excerpt): $visible_text\n\n"
        "User's task: $instruction\n\n"
        "Decompose this task into concrete browser automation steps. "
        "Consider what you see on the current page to decide the next actions.\n\n"
        "Each step must specify:\n"
        '- "step_id": unique string (e.g. "step_1")\n'
        '- "intent": what this step does in natural language\n'
        '- "action": one of "goto", "click", "type", "press_key", "scroll", "wait"\n'
        '- "selector": CSS selector if known, or null\n'
        '- "arguments": array of strings (URL for goto, text for type, key for press_key)\n'
        '- "verify": optional verification after action, e.g. {"type": "url_contains", "value": "query="}\n\n'
        "Return JSON:\n"
        '{"confidence": 0.9, "steps": [...]}\n\n'
        "Constraints:\n"
        "- Output MUST be valid JSON only.\n"
        "- Each step = one atomic browser action.\n"
        "- For search: type into search input, then press Enter or click search button.\n"
        "- Be specific about what element to interact with."
    ),
},
```

Add to `src/ai/llm_planner.py`:

```python
async def plan_with_context(
    self,
    instruction: str,
    page_url: str = "",
    page_title: str = "",
    visible_text_snippet: str = "",
) -> list[StepDefinition]:
    """Plan with current page context for better LLM decisions."""
    prompt = self.prompt_manager.get_prompt(
        "plan_steps_with_context",
        instruction=instruction,
        page_url=page_url,
        page_title=page_title,
        visible_text=visible_text_snippet[:500],
    )

    response_text, tokens = await self._call_gemini(prompt, self.tier1_model)
    self.usage.record(self.tier1_model, tokens)

    try:
        steps, confidence = self._parse_plan_response(response_text)
        if confidence >= 0.7:
            return steps
    except (json.JSONDecodeError, KeyError, ValueError):
        pass

    # Tier 2 escalation
    self.usage.escalations += 1
    response_text, tokens = await self._call_gemini(prompt, self.tier2_model)
    self.usage.record(self.tier2_model, tokens)
    steps, _ = self._parse_plan_response(response_text)
    return steps
```

**Step 4: Run tests**

Run: `python -m pytest tests/unit/test_llm_planner.py -v`
Expected: all pass

**Step 5: Commit**

```bash
git add src/ai/prompt_manager.py src/ai/llm_planner.py tests/unit/test_llm_planner.py
git commit -m "feat: add page-context-aware plan prompt for LLM-First flow"
```

---

### Task 3: LLMFirstOrchestrator

**Files:**
- Create: `src/core/llm_orchestrator.py`
- Test: `tests/unit/test_llm_orchestrator.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_llm_orchestrator.py
"""Tests for LLMFirstOrchestrator — LLM-driven automation loop."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from src.core.llm_orchestrator import LLMFirstOrchestrator, RunResult
from src.core.types import (
    ExtractedElement, PageState, PatchData, StepDefinition,
    VerifyCondition, VerifyResult,
)


@pytest.fixture
def mock_executor():
    ex = AsyncMock()
    page = AsyncMock()
    page.url = "https://shopping.naver.com"
    ex.get_page.return_value = page
    ex.screenshot.return_value = b"fake-png"
    return ex


@pytest.fixture
def mock_extractor():
    ext = AsyncMock()
    ext.extract_state.return_value = PageState(
        url="https://shopping.naver.com",
        title="네이버쇼핑",
        visible_text="검색",
    )
    ext.extract_clickables.return_value = [
        ExtractedElement(eid="#search-input", type="input", text="검색어를 입력해주세요"),
    ]
    ext.extract_inputs.return_value = [
        ExtractedElement(eid="#search-input", type="input", text="검색어를 입력해주세요"),
    ]
    return ext


@pytest.fixture
def mock_planner():
    p = AsyncMock()
    p.plan_with_context.return_value = [
        StepDefinition(step_id="s1", intent="검색창에 노트북 입력", node_type="action",
                       arguments=["노트북"]),
    ]
    p.select.return_value = PatchData(
        patch_type="selector_fix",
        target="#search-input",
        data={"selected_eid": "#search-input"},
        confidence=0.95,
    )
    p.usage = MagicMock(total_tokens=0, total_cost_usd=0.0)
    return p


@pytest.fixture
def mock_verifier():
    v = AsyncMock()
    v.verify.return_value = VerifyResult(success=True, message="OK")
    return v


@pytest.fixture
def mock_cache():
    c = AsyncMock()
    c.lookup.return_value = None  # cache miss
    return c


@pytest.mark.asyncio
async def test_run_single_step_success(
    mock_executor, mock_extractor, mock_planner, mock_verifier, mock_cache, tmp_path
):
    orch = LLMFirstOrchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        planner=mock_planner,
        verifier=mock_verifier,
        cache=mock_cache,
        screenshot_dir=tmp_path / "screenshots",
    )
    result = await orch.run("노트북 검색")
    assert result.success
    assert len(result.step_results) == 1
    assert result.step_results[0].success


@pytest.mark.asyncio
async def test_run_uses_cache_on_hit(
    mock_executor, mock_extractor, mock_planner, mock_verifier, tmp_path
):
    from src.core.selector_cache import CacheHit
    cache = AsyncMock()
    cache.lookup.return_value = CacheHit(selector="#cached-btn", method="click", confidence=0.95)

    orch = LLMFirstOrchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        planner=mock_planner,
        verifier=mock_verifier,
        cache=cache,
        screenshot_dir=tmp_path / "screenshots",
    )
    result = await orch.run("노트북 검색")
    assert result.success
    # LLM select should NOT be called (cache hit)
    mock_planner.select.assert_not_called()


@pytest.mark.asyncio
async def test_screenshots_saved(
    mock_executor, mock_extractor, mock_planner, mock_verifier, mock_cache, tmp_path
):
    ss_dir = tmp_path / "screenshots"
    orch = LLMFirstOrchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        planner=mock_planner,
        verifier=mock_verifier,
        cache=mock_cache,
        screenshot_dir=ss_dir,
    )
    result = await orch.run("노트북 검색")
    assert ss_dir.exists()
    # At least one screenshot saved
    pngs = list(ss_dir.glob("*.png"))
    assert len(pngs) >= 1
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_llm_orchestrator.py -v`
Expected: FAIL (import error)

**Step 3: Write implementation**

```python
# src/core/llm_orchestrator.py
"""LLM-First Orchestrator — LLM drives every decision.

Flow per step:
  1. Cache lookup (free)
  2. Cache miss → DOM extract → LLM select → Execute
  3. Verify → Screenshot → Cache save on success
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.core.types import (
    ClickOptions,
    ExtractedElement,
    IExecutor,
    IExtractor,
    ILLMPlanner,
    IVerifier,
    PageState,
    StepDefinition,
    StepResult,
    VerifyCondition,
    VerifyResult,
    WaitCondition,
)

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Result of a full automation run."""
    success: bool
    step_results: list[StepResult] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0


class LLMFirstOrchestrator:
    """LLM-First orchestrator: LLM plans, selects elements, drives execution.

    Args:
        executor: Playwright browser wrapper.
        extractor: DOM extraction module.
        planner: LLM planner (must have plan_with_context and select).
        verifier: Post-action verification.
        cache: SelectorCache for caching successful selectors.
        screenshot_dir: Directory to save step screenshots.
    """

    def __init__(
        self,
        executor: IExecutor,
        extractor: IExtractor,
        planner: Any,  # LLMPlanner with plan_with_context
        verifier: IVerifier,
        cache: Any | None = None,  # SelectorCache
        screenshot_dir: Path | str = "data/screenshots",
    ) -> None:
        self._executor = executor
        self._extractor = extractor
        self._planner = planner
        self._verifier = verifier
        self._cache = cache
        self._screenshot_dir = Path(screenshot_dir)
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)

    async def run(self, intent: str) -> RunResult:
        """Execute a user intent end-to-end.

        1. Get current page context
        2. LLM decomposes intent into steps
        3. Execute each step with cache-first strategy
        4. Screenshot after every step
        """
        page = await self._executor.get_page()
        page_state = await self._extractor.extract_state(page)

        # Step 1: LLM plans the steps
        logger.info("Planning: %s", intent)
        steps = await self._planner.plan_with_context(
            instruction=intent,
            page_url=page_state.url,
            page_title=page_state.title,
            visible_text_snippet=page_state.visible_text[:500],
        )
        logger.info("Plan: %d steps", len(steps))
        for s in steps:
            logger.info("  [%s] %s (action=%s, args=%s)", s.step_id, s.intent, s.node_type, s.arguments)

        result = RunResult(success=True)

        # Step 2: Execute each step
        for i, step in enumerate(steps):
            logger.info("--- Step %d/%d: %s ---", i + 1, len(steps), step.intent)
            step_result = await self._execute_step(step)
            result.step_results.append(step_result)

            # Screenshot after every step
            ss_path = await self._take_screenshot(f"step_{i + 1}_{step.step_id}")
            if ss_path:
                result.screenshots.append(ss_path)

            result.total_tokens += step_result.tokens_used
            result.total_cost_usd += step_result.cost_usd

            if not step_result.success:
                logger.warning("Step %d failed: %s", i + 1, step.intent)
                result.success = False
                break

            # Small wait between steps for page to settle
            await page.wait_for_timeout(500)

            # Refresh page state for next step's context
            page_state = await self._extractor.extract_state(page)

        # Final summary
        usage = self._planner.usage
        result.total_tokens = usage.total_tokens
        result.total_cost_usd = usage.total_cost_usd
        logger.info(
            "Run complete: success=%s, steps=%d/%d, tokens=%d, cost=$%.4f",
            result.success,
            sum(1 for r in result.step_results if r.success),
            len(result.step_results),
            result.total_tokens,
            result.total_cost_usd,
        )
        return result

    async def _execute_step(self, step: StepDefinition) -> StepResult:
        """Execute a single step: Cache → LLM Select → Execute → Verify."""
        start = time.perf_counter()
        page = await self._executor.get_page()
        site = urlparse(page.url).hostname or "*"

        action = step.node_type if step.node_type != "action" else self._infer_action(step)

        # Handle goto directly (no element selection needed)
        if action == "goto":
            url = step.arguments[0] if step.arguments else step.selector or ""
            await self._executor.goto(url)
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(step_id=step.step_id, success=True, method="GOTO", latency_ms=elapsed)

        # Handle press_key directly
        if action == "press_key":
            key = step.arguments[0] if step.arguments else "Enter"
            await self._executor.press_key(key)
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(step_id=step.step_id, success=True, method="KEY", latency_ms=elapsed)

        # Handle wait directly
        if action == "wait":
            ms = int(step.arguments[0]) if step.arguments else 2000
            await page.wait_for_timeout(ms)
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(step_id=step.step_id, success=True, method="WAIT", latency_ms=elapsed)

        # Handle scroll directly
        if action == "scroll":
            direction = step.arguments[0] if step.arguments else "down"
            amount = int(step.arguments[1]) if len(step.arguments) > 1 else 300
            await self._executor.scroll(direction, amount)
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(step_id=step.step_id, success=True, method="SCROLL", latency_ms=elapsed)

        # For click/type: need element selection
        # 1. Cache lookup
        if self._cache is not None:
            hit = await self._cache.lookup(step.intent, site)
            if hit is not None:
                logger.info("Cache HIT: %s -> %s", step.intent, hit.selector)
                try:
                    await self._do_action(hit.selector, action, step)
                    elapsed = (time.perf_counter() - start) * 1000
                    return StepResult(
                        step_id=step.step_id, success=True, method="CACHE",
                        latency_ms=elapsed,
                    )
                except Exception as exc:
                    logger.warning("Cache hit failed (%s), falling through to LLM", exc)
                    await self._cache.invalidate(step.intent, site)

        # 2. DOM extract + LLM select
        clickables = await self._extractor.extract_clickables(page)
        inputs = await self._extractor.extract_inputs(page)
        candidates = clickables + inputs
        # Filter to visible only
        candidates = [c for c in candidates if c.visible]

        if not candidates:
            logger.warning("No candidates found for: %s", step.intent)
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(step_id=step.step_id, success=False, method="L", latency_ms=elapsed)

        logger.info("Extracted %d candidates, asking LLM to select...", len(candidates))
        patch = await self._planner.select(candidates, step.intent)
        selector = patch.target
        logger.info("LLM selected: %s (confidence=%.2f)", selector, patch.confidence)

        # 3. Execute
        try:
            await self._do_action(selector, action, step)
        except Exception as exc:
            logger.warning("Action failed: %s", exc)
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(step_id=step.step_id, success=False, method="L", latency_ms=elapsed)

        # 4. Verify (if condition specified)
        if step.verify_condition is not None:
            vr = await self._verifier.verify(step.verify_condition, page)
            if not vr.success:
                elapsed = (time.perf_counter() - start) * 1000
                return StepResult(step_id=step.step_id, success=False, method="L", latency_ms=elapsed)

        # 5. Cache save on success
        if self._cache is not None:
            method_str = action or "click"
            await self._cache.save(step.intent, site, selector, method_str)

        elapsed = (time.perf_counter() - start) * 1000
        return StepResult(step_id=step.step_id, success=True, method="L", latency_ms=elapsed)

    async def _do_action(self, selector: str, action: str, step: StepDefinition) -> None:
        """Dispatch to the appropriate executor method."""
        if action == "type":
            text = step.arguments[0] if step.arguments else ""
            await self._executor.type_text(selector, text)
        elif action == "click":
            await self._executor.click(selector, ClickOptions(timeout_ms=step.timeout_ms))
        else:
            await self._executor.click(selector, ClickOptions(timeout_ms=step.timeout_ms))

    async def _take_screenshot(self, label: str) -> str | None:
        """Capture and save a screenshot."""
        try:
            data = await self._executor.screenshot()
            ts = int(time.time() * 1000)
            filename = f"{label}_{ts}.png"
            path = self._screenshot_dir / filename
            path.write_bytes(data)
            logger.info("Screenshot saved: %s", path)
            return str(path)
        except Exception as exc:
            logger.warning("Screenshot failed: %s", exc)
            return None

    @staticmethod
    def _infer_action(step: StepDefinition) -> str:
        """Infer action type from step intent and arguments."""
        intent_lower = step.intent.lower()
        if any(kw in intent_lower for kw in ("입력", "type", "검색어", "작성", "write", "fill")):
            return "type"
        if any(kw in intent_lower for kw in ("이동", "방문", "navigate", "goto", "go to", "open")):
            return "goto"
        if any(kw in intent_lower for kw in ("enter", "엔터", "press")):
            return "press_key"
        if any(kw in intent_lower for kw in ("스크롤", "scroll")):
            return "scroll"
        if any(kw in intent_lower for kw in ("대기", "wait")):
            return "wait"
        return "click"
```

**Step 4: Run tests**

Run: `python -m pytest tests/unit/test_llm_orchestrator.py -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add src/core/llm_orchestrator.py tests/unit/test_llm_orchestrator.py
git commit -m "feat: add LLMFirstOrchestrator with cache-first step execution"
```

---

### Task 4: run_live.py — headful E2E runner script

**Files:**
- Create: `scripts/run_live.py`

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Run the LLM-First orchestrator on a real site with headful browser.

Usage:
    python scripts/run_live.py --intent "네이버 쇼핑에서 노트북 검색해서 인기순 정렬"
    python scripts/run_live.py --intent "네이버 쇼핑에서 노트북 검색" --url https://shopping.naver.com
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai.llm_planner import create_llm_planner
from src.core.executor import create_executor
from src.core.extractor import DOMExtractor
from src.core.llm_orchestrator import LLMFirstOrchestrator
from src.core.selector_cache import SelectorCache
from src.core.verifier import Verifier


async def main(intent: str, url: str | None, headless: bool) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("run_live")

    # Create modules
    executor = await create_executor(headless=headless)
    extractor = DOMExtractor()
    planner = create_llm_planner()
    verifier = Verifier()
    cache = SelectorCache("data/live_cache.db")
    await cache.init()

    screenshot_dir = Path("data/screenshots")

    orch = LLMFirstOrchestrator(
        executor=executor,
        extractor=extractor,
        planner=planner,
        verifier=verifier,
        cache=cache,
        screenshot_dir=screenshot_dir,
    )

    # Navigate to starting URL if provided
    if url:
        log.info("Navigating to: %s", url)
        await executor.goto(url)
        # Wait for page to load
        page = await executor.get_page()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

    try:
        result = await orch.run(intent)

        log.info("=" * 60)
        log.info("RESULT: %s", "SUCCESS" if result.success else "FAILED")
        log.info("Steps: %d total", len(result.step_results))
        for i, sr in enumerate(result.step_results):
            status = "OK" if sr.success else "FAIL"
            log.info("  [%d] %s method=%s latency=%.0fms", i + 1, status, sr.method, sr.latency_ms)
        log.info("Screenshots: %d saved to %s", len(result.screenshots), screenshot_dir)
        log.info("Tokens: %d | Cost: $%.4f", result.total_tokens, result.total_cost_usd)
        log.info("=" * 60)

        # Keep browser open for inspection
        if not headless:
            log.info("Browser open for inspection. Press Ctrl+C to close.")
            try:
                await asyncio.sleep(30)
            except KeyboardInterrupt:
                pass
    finally:
        await executor.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-First live site runner")
    parser.add_argument("--intent", required=True, help="User intent in natural language")
    parser.add_argument("--url", default=None, help="Starting URL (optional)")
    parser.add_argument("--headless", action="store_true", default=False, help="Run headless")
    args = parser.parse_args()

    asyncio.run(main(args.intent, args.url, args.headless))
```

**Step 2: Verify it runs (dry run)**

Run: `python scripts/run_live.py --help`
Expected: Shows argument help

**Step 3: Commit**

```bash
git add scripts/run_live.py
git commit -m "feat: add run_live.py headful E2E runner for LLM-First orchestrator"
```

---

### Task 5: Live E2E test on Naver Shopping

**Step 1: Run the live test (headful)**

```bash
python scripts/run_live.py \
    --intent "네이버 쇼핑에서 노트북 검색해서 인기순 정렬" \
    --url https://shopping.naver.com
```

**Step 2: Observe and debug**

Watch the headful browser. Check:
- Did the LLM generate sensible steps?
- Did it find the search input?
- Did it type "노트북"?
- Did it click search / press Enter?
- Did it find and click "인기순"?
- Are screenshots saved in `data/screenshots/`?

**Step 3: Fix issues found**

Common issues to expect:
- Naver popup (cookies/age verification) blocking interaction → need popup dismissal step
- Search input selector mismatch → LLM may need better DOM context
- Dynamic loading delays → may need longer waits
- Action inference wrong → may need to improve _infer_action or prompt

**Step 4: Re-run until all steps pass**

Iterate: fix → run → check screenshots → fix again.

**Step 5: Run a second time (cache test)**

```bash
python scripts/run_live.py \
    --intent "네이버 쇼핑에서 노트북 검색해서 인기순 정렬" \
    --url https://shopping.naver.com
```

Verify: LLM calls should be fewer (cache hits from first run).

**Step 6: Final commit**

```bash
git add -A
git commit -m "feat: LLM-First orchestrator working E2E on Naver Shopping"
```
