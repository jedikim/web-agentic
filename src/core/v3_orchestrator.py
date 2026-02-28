"""v3 Orchestrator — main execution loop.

Two paths:
- Cached: execute directly → verify result → done (LLM 0 calls)
- Uncached: VLM screen check → obstacle removal → DOM extract →
  TextMatcher filter → Actor select → execute → verify → cache

Retry: 2 consecutive failures → replan from current screen.
Max replan: 2 times.
"""

from __future__ import annotations

import logging
from typing import Protocol
from urllib.parse import urlparse

from src.core.browser import Browser
from src.core.cache import Cache
from src.core.types import Action, CacheEntry, StepPlan

logger = logging.getLogger(__name__)

FILTER_SCORE_THRESHOLD = 0.5
MAX_RETRY_PER_STEP = 3
MAX_REPLAN = 2


class IPlanner(Protocol):
    """Planner interface for orchestrator."""

    async def check_screen(self, screenshot: bytes) -> object: ...
    async def plan(self, task: str, screenshot: bytes) -> list[StepPlan]: ...


class IExtractor(Protocol):
    """DOM extractor interface."""

    async def extract(self, browser: Browser) -> list: ...  # type: ignore[type-arg]


class IFilter(Protocol):
    """Element filter interface."""

    def filter(self, nodes: list, keyword_weights: dict[str, float]) -> list: ...  # type: ignore[type-arg]


class IActor(Protocol):
    """Actor interface."""

    async def decide(self, step: StepPlan, candidates: list, browser: Browser) -> Action: ...  # type: ignore[type-arg]


class IExecutor(Protocol):
    """Action executor interface."""

    async def execute_action(self, action: Action, browser: Browser) -> None: ...


class IVerifier(Protocol):
    """Result verifier interface."""

    async def verify_result(
        self,
        pre_screenshot: bytes,
        post_screenshot: bytes,
        action: Action | None,
        step_or_cache: CacheEntry | StepPlan,
        browser: Browser,
        pre_url: str,
    ) -> str: ...


class V3Orchestrator:
    """Main orchestrator for v3 pipeline.

    Usage:
        orch = V3Orchestrator(
            planner=planner, extractor=extractor, filter=element_filter,
            actor=actor, executor=executor, cache=cache, verifier=verifier,
        )
        success = await orch.run("등산복 검색", browser)
    """

    def __init__(
        self,
        planner: IPlanner,
        extractor: IExtractor,
        element_filter: IFilter,
        actor: IActor,
        executor: IExecutor,
        cache: Cache,
        verifier: IVerifier,
    ) -> None:
        self.planner = planner
        self.extractor = extractor
        self.filter = element_filter
        self.actor = actor
        self.executor = executor
        self.cache = cache
        self.verifier = verifier

    async def run(self, task: str, browser: Browser) -> bool:
        """Execute a task end-to-end.

        Args:
            task: Natural language task description.
            browser: Browser instance.

        Returns:
            True if all steps succeeded.
        """
        screenshot = await browser.screenshot()
        steps = await self.planner.plan(task, screenshot)

        if not steps:
            logger.warning("Planner returned no steps for task: %s", task)
            return False

        replan_count = 0
        consecutive_failures = 0
        i = 0

        while i < len(steps):
            success = await self._execute_step(steps[i], browser)

            if success:
                consecutive_failures = 0
                i += 1
                continue

            consecutive_failures += 1

            # 2 consecutive failures at same step → replan from current screen
            if consecutive_failures >= 2:
                if replan_count < MAX_REPLAN:
                    replan_count += 1
                    screenshot = await browser.screenshot()
                    remaining = " → ".join(s.target_description for s in steps[i:])
                    steps = await self.planner.plan(
                        f"{task} (남은 작업: {remaining})", screenshot,
                    )
                    if not steps:
                        return False
                    i = 0
                    consecutive_failures = 0
                    continue
                return False  # replan count exceeded

        return True

    async def _execute_step(self, step: StepPlan, browser: Browser) -> bool:
        """Execute a single step with cache check and full pipeline fallback."""
        domain = self._get_domain(browser.url)
        pre_screenshot = await browser.screenshot()

        # === Cached path: try directly ===
        cached = await self.cache.lookup(domain, browser.url, step.target_description)
        if cached:
            result = await self._try_cached(cached, browser, pre_screenshot)
            if result == "ok":
                return True
            # "failed" or "wrong" → fall through to full pipeline

        # === Uncached path: full pipeline ===
        return await self._full_pipeline(step, browser, domain)

    async def _try_cached(
        self, cached: CacheEntry, browser: Browser, pre_screenshot: bytes,
    ) -> str:
        """Execute from cache and verify result."""
        action = Action(
            selector=cached.selector,
            action_type=cached.action_type,
            value=cached.value,
            viewport_xy=cached.viewport_xy,
            viewport_bbox=cached.viewport_bbox,
        )

        pre_url = browser.url

        try:
            await self.executor.execute_action(action, browser)
        except Exception:
            return "failed"

        await browser.wait(500)
        post_screenshot = await browser.screenshot()

        result = await self.verifier.verify_result(
            pre_screenshot, post_screenshot, action, cached, browser,
            pre_url=pre_url,
        )

        if result == "ok":
            await self.cache.record_success(cached)

        return result

    async def _full_pipeline(
        self, step: StepPlan, browser: Browser, domain: str,
    ) -> bool:
        """Full uncached pipeline: screen check → extract → filter → act → verify."""

        # 1. Ensure clean screen (remove obstacles)
        await self._ensure_clean_screen(browser)

        # 2. DOM extract + TextMatcher filter
        nodes = await self.extractor.extract(browser)
        candidates = self.filter.filter(nodes, step.keyword_weights)
        top_score = candidates[0].score if candidates else 0.0

        if top_score >= FILTER_SCORE_THRESHOLD:
            action = await self.actor.decide(step, candidates, browser)
        else:
            action = Action(
                selector=None,
                action_type=step.action_type,
                value=step.value,
                viewport_xy=step.target_viewport_xy,
            )

        # 3. Execute + verify with retry
        pre_url = browser.url

        for attempt in range(MAX_RETRY_PER_STEP):
            pre_screenshot = await browser.screenshot()

            try:
                await self.executor.execute_action(action, browser)
            except Exception:
                if attempt < MAX_RETRY_PER_STEP - 1:
                    # Re-extract and try different element
                    nodes = await self.extractor.extract(browser)
                    candidates = self.filter.filter(nodes, step.keyword_weights)
                    if candidates:
                        action = await self.actor.decide(step, candidates, browser)
                    continue
                return False

            await browser.wait(500)
            post_screenshot = await browser.screenshot()

            result = await self.verifier.verify_result(
                pre_screenshot, post_screenshot, action, step, browser,
                pre_url=pre_url,
            )

            if result == "ok":
                # Store in cache
                await self.cache.store(CacheEntry(
                    domain=domain,
                    url_pattern=browser.url,
                    task_type=step.target_description,
                    selector=action.selector,
                    action_type=action.action_type,
                    value=action.value,
                    keyword_weights=step.keyword_weights,
                    viewport_xy=action.viewport_xy,
                    viewport_bbox=action.viewport_bbox,
                    expected_result=step.expected_result,
                    success_count=1,
                    last_success=None,
                ))
                return True

            if attempt < MAX_RETRY_PER_STEP - 1:
                # Re-extract for next attempt
                nodes = await self.extractor.extract(browser)
                candidates = self.filter.filter(nodes, step.keyword_weights)
                if candidates:
                    action = await self.actor.decide(step, candidates, browser)
                pre_url = browser.url

        return False

    async def _ensure_clean_screen(self, browser: Browser) -> bytes:
        """Remove obstacles (popups, ads) from screen. Max 3 attempts."""
        for _ in range(3):
            screenshot = await browser.screenshot()
            screen_state = await self.planner.check_screen(screenshot)

            if not getattr(screen_state, "has_obstacle", False):
                return screenshot

            close_xy = getattr(screen_state, "obstacle_close_xy", None)
            if close_xy:
                size = await browser.get_viewport_size()
                x = int(close_xy[0] * size["width"])
                y = int(close_xy[1] * size["height"])
                await browser.mouse_click(x, y)
                await browser.wait(500)
            else:
                await browser.key_press("Escape")
                await browser.wait(500)

        return await browser.screenshot()

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            return urlparse(url).netloc
        except Exception:
            return ""
