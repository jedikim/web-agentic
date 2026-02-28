"""v3 Orchestrator — main execution loop.

Two paths:
- Cached: execute directly → verify result → done (LLM 0 calls)
- Uncached: VLM screen check → obstacle removal → DOM extract →
  TextMatcher filter → Actor select → execute → verify → cache

Retry: 2 consecutive failures → replan from current screen.
Max replan: 2 times.

Safety: total timeout (120s) and API call budget (30 calls) prevent runaway.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

from src.core.browser import Browser
from src.core.cache import Cache
from src.core.types import Action, CacheEntry, StepPlan

logger = logging.getLogger(__name__)

# Cost estimates per API call (Gemini Flash)
_VLM_COST_EST = 0.0005  # VLM call with image
_LLM_COST_EST = 0.0002  # Text-only LLM call
_VLM_TOKENS_EST = 500
_LLM_TOKENS_EST = 200


@dataclass
class V3StepOutcome:
    """Result of a single step for API reporting.

    Attributes:
        step_id: Step identifier (description).
        success: Whether the step succeeded.
        method: Resolution method (cache/selector/viewport).
        latency_ms: Step execution time.
        cost_usd: Estimated cost (0 for cached).
    """

    step_id: str = ""
    success: bool = False
    method: str = "v3"
    tokens_used: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0


@dataclass
class V3RunResult:
    """Result of a full v3 automation run.

    Compatible with the API layer's expected RunResult shape.

    Attributes:
        success: Overall success.
        step_results: Per-step outcomes for API reporting.
        screenshots: Screenshot file paths (currently empty).
        total_tokens: Total tokens consumed (estimated).
        total_cost_usd: Total estimated cost.
        result_summary: Human-readable summary.
    """

    success: bool = False
    step_results: list[V3StepOutcome] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    result_summary: str = ""

FILTER_SCORE_THRESHOLD = 0.5
MAX_RETRY_PER_STEP = 2
MAX_REPLAN = 2
MAX_API_CALLS = 30
DEFAULT_TIMEOUT_S = 180.0


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


class _BudgetExceededError(Exception):
    """Raised when API call budget or timeout is exceeded."""


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
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_api_calls: int = MAX_API_CALLS,
    ) -> None:
        self.planner = planner
        self.extractor = extractor
        self.filter = element_filter
        self.actor = actor
        self.executor = executor
        self.cache = cache
        self.verifier = verifier
        self._timeout_s = timeout_s
        self._max_api_calls = max_api_calls

        # Runtime counters (reset per run)
        self._run_start: float = 0.0
        self._api_calls: int = 0
        self._total_tokens: int = 0
        self._total_cost: float = 0.0

    def _check_budget(self) -> None:
        """Raise if timeout or API call budget exceeded."""
        elapsed = time.monotonic() - self._run_start
        if elapsed > self._timeout_s:
            raise _BudgetExceededError(
                f"Timeout: {elapsed:.0f}s > {self._timeout_s:.0f}s"
            )
        if self._api_calls >= self._max_api_calls:
            raise _BudgetExceededError(
                f"API budget: {self._api_calls} >= {self._max_api_calls}"
            )

    def _track_vlm_call(self) -> None:
        """Track a VLM API call."""
        self._api_calls += 1
        self._total_tokens += _VLM_TOKENS_EST
        self._total_cost += _VLM_COST_EST

    def _track_llm_call(self) -> None:
        """Track a text LLM API call."""
        self._api_calls += 1
        self._total_tokens += _LLM_TOKENS_EST
        self._total_cost += _LLM_COST_EST

    async def run(self, task: str, browser: Browser) -> bool:
        """Execute a task end-to-end.

        Args:
            task: Natural language task description.
            browser: Browser instance.

        Returns:
            True if all steps succeeded.
        """
        self._run_start = time.monotonic()
        self._api_calls = 0
        self._total_tokens = 0
        self._total_cost = 0.0

        logger.info("▶ v3 run: %s", task)

        try:
            screenshot = await browser.screenshot()
            self._check_budget()

            logger.info("Planning task...")
            steps = await self.planner.plan(task, screenshot)
            self._track_vlm_call()

            if not steps:
                logger.warning("Planner returned no steps for task: %s", task)
                return False

            logger.info(
                "Plan: %d steps — %s",
                len(steps),
                " → ".join(s.target_description for s in steps),
            )

            return await self._run_loop(task, steps, browser)

        except _BudgetExceededError as exc:
            logger.error("Budget exceeded: %s", exc)
            return False

    async def run_with_result(
        self,
        task: str,
        browser: Browser,
        attachments: list[dict[str, Any]] | None = None,
    ) -> V3RunResult:
        """Execute a task and return a rich result for API reporting.

        Same logic as run() but tracks step outcomes for the API layer.

        Args:
            task: Natural language task description.
            browser: Browser instance.
            attachments: Optional attachments (unused, for API compat).

        Returns:
            V3RunResult with per-step outcomes and totals.
        """
        self._run_start = time.monotonic()
        self._api_calls = 0
        self._total_tokens = 0
        self._total_cost = 0.0
        step_outcomes: list[V3StepOutcome] = []

        logger.info("▶ v3 run_with_result: %s", task)

        try:
            screenshot = await browser.screenshot()
            self._check_budget()

            logger.info("Planning task...")
            steps = await self.planner.plan(task, screenshot)
            self._track_vlm_call()

            if not steps:
                logger.warning("Planner returned no steps")
                return V3RunResult(
                    success=False,
                    result_summary="Planner returned no steps",
                )

            logger.info(
                "Plan: %d steps — %s",
                len(steps),
                " → ".join(s.target_description for s in steps),
            )

            replan_count = 0
            consecutive_failures = 0
            i = 0

            while i < len(steps):
                self._check_budget()
                step_start = time.monotonic()

                logger.info(
                    "Step %d/%d: [%s] %s",
                    i + 1, len(steps),
                    steps[i].action_type,
                    steps[i].target_description,
                )

                success = await self._execute_step(steps[i], browser)
                step_ms = (time.monotonic() - step_start) * 1000

                step_outcomes.append(V3StepOutcome(
                    step_id=steps[i].target_description,
                    success=success,
                    method="cache" if success else "v3",
                    latency_ms=step_ms,
                    tokens_used=_VLM_TOKENS_EST,
                    cost_usd=_VLM_COST_EST if not success else 0.0,
                ))

                if success:
                    logger.info(
                        "  ✓ Step %d OK (%.0fms)", i + 1, step_ms,
                    )
                    consecutive_failures = 0
                    i += 1
                    continue

                consecutive_failures += 1
                logger.warning(
                    "  ✗ Step %d FAIL (attempt %d, %.0fms)",
                    i + 1, consecutive_failures, step_ms,
                )

                if consecutive_failures >= 2:
                    if replan_count < MAX_REPLAN:
                        replan_count += 1
                        logger.info(
                            "Replanning (%d/%d)...", replan_count, MAX_REPLAN,
                        )
                        self._check_budget()
                        screenshot = await browser.screenshot()
                        remaining = " → ".join(
                            s.target_description for s in steps[i:]
                        )
                        steps = await self.planner.plan(
                            f"{task} (남은 작업: {remaining})", screenshot,
                        )
                        self._track_vlm_call()

                        if not steps:
                            logger.warning("Replan returned no steps")
                            break
                        logger.info(
                            "New plan: %d steps — %s",
                            len(steps),
                            " → ".join(s.target_description for s in steps),
                        )
                        i = 0
                        consecutive_failures = 0
                        continue
                    logger.error("Max replans exceeded, giving up")
                    break

        except _BudgetExceededError as exc:
            logger.error("Budget exceeded: %s", exc)

        all_ok = all(o.success for o in step_outcomes) and len(step_outcomes) > 0
        total_ms = (time.monotonic() - self._run_start) * 1000

        result = V3RunResult(
            success=all_ok,
            step_results=step_outcomes,
            total_tokens=self._total_tokens,
            total_cost_usd=self._total_cost,
            result_summary=(
                f"{'성공' if all_ok else '실패'}: "
                f"{sum(1 for o in step_outcomes if o.success)}"
                f"/{len(step_outcomes)} steps "
                f"({total_ms:.0f}ms, "
                f"API:{self._api_calls}, "
                f"${self._total_cost:.4f})"
            ),
        )
        logger.info("▶ Result: %s", result.result_summary)
        return result

    async def _run_loop(
        self, task: str, steps: list[StepPlan], browser: Browser,
    ) -> bool:
        """Main execution loop with replan support."""
        replan_count = 0
        consecutive_failures = 0
        i = 0

        while i < len(steps):
            self._check_budget()

            logger.info(
                "Step %d/%d: [%s] %s",
                i + 1, len(steps),
                steps[i].action_type,
                steps[i].target_description,
            )

            success = await self._execute_step(steps[i], browser)

            if success:
                logger.info("  ✓ Step %d OK", i + 1)
                consecutive_failures = 0
                i += 1
                continue

            consecutive_failures += 1
            logger.warning(
                "  ✗ Step %d FAIL (attempt %d)", i + 1, consecutive_failures,
            )

            if consecutive_failures >= 2:
                if replan_count < MAX_REPLAN:
                    replan_count += 1
                    logger.info(
                        "Replanning (%d/%d)...", replan_count, MAX_REPLAN,
                    )
                    self._check_budget()
                    screenshot = await browser.screenshot()
                    remaining = " → ".join(
                        s.target_description for s in steps[i:]
                    )
                    steps = await self.planner.plan(
                        f"{task} (남은 작업: {remaining})", screenshot,
                    )
                    self._track_vlm_call()

                    if not steps:
                        return False
                    logger.info(
                        "New plan: %d steps — %s",
                        len(steps),
                        " → ".join(s.target_description for s in steps),
                    )
                    i = 0
                    consecutive_failures = 0
                    continue
                logger.error("Max replans exceeded")
                return False

        return True

    async def _execute_step(self, step: StepPlan, browser: Browser) -> bool:
        """Execute a single step with cache check and full pipeline fallback."""
        domain = self._get_domain(browser.url)
        pre_screenshot = await browser.screenshot()

        # === Cached path: try directly ===
        cached = await self.cache.lookup(domain, browser.url, step.target_description)
        if cached:
            logger.info("  Cache hit: %s", cached.selector or "viewport")
            result = await self._try_cached(cached, browser, pre_screenshot)
            if result == "ok":
                logger.info("  Cache execution OK")
                return True
            logger.info("  Cache execution %s, falling through to pipeline", result)

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
        except Exception as exc:
            logger.debug("  Cache execute error: %s", exc)
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

        # 1. Ensure clean screen (only once, NOT on retries)
        self._check_budget()
        await self._ensure_clean_screen(browser)

        # 2. DOM extract + TextMatcher filter
        nodes = await self.extractor.extract(browser)
        logger.info("  DOM: %d interactive nodes", len(nodes))

        candidates = self.filter.filter(nodes, step.keyword_weights)
        top_score = candidates[0].score if candidates else 0.0
        logger.info(
            "  Filter: %d candidates (top=%.2f, kw=%s)",
            len(candidates),
            top_score,
            list(step.keyword_weights.keys())[:5],
        )

        if top_score >= FILTER_SCORE_THRESHOLD:
            self._check_budget()
            action = await self.actor.decide(step, candidates, browser)
            self._track_llm_call()
            logger.info(
                "  Actor selected: %s [%s] val=%s",
                action.selector or "viewport",
                action.action_type,
                action.value[:30] if action.value else None,
            )
        else:
            logger.info(
                "  No strong candidate (%.2f < %.2f), using planner coords",
                top_score, FILTER_SCORE_THRESHOLD,
            )
            action = Action(
                selector=None,
                action_type=step.action_type,
                value=step.value,
                viewport_xy=step.target_viewport_xy,
            )

        # 3. Execute + verify with retry (NO re-check_screen on retry)
        pre_url = browser.url

        for attempt in range(MAX_RETRY_PER_STEP):
            self._check_budget()
            pre_screenshot = await browser.screenshot()

            try:
                await self.executor.execute_action(action, browser)
                logger.info("  Execute OK (attempt %d)", attempt + 1)
            except Exception as exc:
                logger.warning("  Execute error (attempt %d): %s", attempt + 1, exc)
                if attempt < MAX_RETRY_PER_STEP - 1:
                    # Re-extract and try different element
                    nodes = await self.extractor.extract(browser)
                    candidates = self.filter.filter(nodes, step.keyword_weights)
                    if candidates:
                        self._check_budget()
                        action = await self.actor.decide(step, candidates, browser)
                        self._track_llm_call()
                        logger.info("  Retry: new action %s", action.selector)
                    continue
                return False

            await browser.wait(500)
            post_screenshot = await browser.screenshot()

            result = await self.verifier.verify_result(
                pre_screenshot, post_screenshot, action, step, browser,
                pre_url=pre_url,
            )
            logger.info(
                "  Verify: %s (url_changed=%s)",
                result, browser.url != pre_url,
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
                logger.info("  Retrying (attempt %d)...", attempt + 2)
                # Re-extract for next attempt
                nodes = await self.extractor.extract(browser)
                candidates = self.filter.filter(nodes, step.keyword_weights)
                if candidates:
                    self._check_budget()
                    action = await self.actor.decide(step, candidates, browser)
                    self._track_llm_call()
                    logger.info("  Retry: new action %s", action.selector)
                pre_url = browser.url

        return False

    async def _ensure_clean_screen(self, browser: Browser) -> bytes:
        """Remove obstacles (popups, ads) from screen. Max 3 attempts."""
        for attempt in range(3):
            self._check_budget()
            screenshot = await browser.screenshot()
            screen_state = await self.planner.check_screen(screenshot)
            self._track_vlm_call()

            has_obstacle = getattr(screen_state, "has_obstacle", False)
            obstacle_type = getattr(screen_state, "obstacle_type", None)

            if not has_obstacle:
                if attempt == 0:
                    logger.info("  Screen clean")
                else:
                    logger.info("  Screen clean (after %d obstacles)", attempt)
                return screenshot

            logger.info(
                "  Obstacle detected: %s (attempt %d/3)",
                obstacle_type or "unknown", attempt + 1,
            )

            close_xy = getattr(screen_state, "obstacle_close_xy", None)
            if close_xy:
                size = await browser.get_viewport_size()
                x = int(close_xy[0] * size["width"])
                y = int(close_xy[1] * size["height"])
                logger.info("  Closing obstacle at (%d, %d)", x, y)
                await browser.mouse_click(x, y)
                await browser.wait(500)
            else:
                logger.info("  Pressing Escape to dismiss obstacle")
                await browser.key_press("Escape")
                await browser.wait(500)

        logger.warning("  Could not clear all obstacles after 3 attempts")
        return await browser.screenshot()

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            return urlparse(url).netloc
        except Exception:
            return ""
