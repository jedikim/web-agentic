"""LLM-First Orchestrator — LLM drives every decision.

Flow per step:
  1. Cache lookup (free)
  2. Cache miss -> DOM extract -> LLM select -> Execute
  3. Verify -> Screenshot -> Cache save on success
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.core.types import (
    AutomationError,
    ClickOptions,
    ExtractedElement,
    IExecutor,
    IExtractor,
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
            logger.info(
                "  [%s] %s (action=%s, args=%s)",
                s.step_id,
                s.intent,
                s.node_type,
                s.arguments,
            )

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
        """Execute a single step: Cache -> LLM Select -> Execute -> Verify."""
        start = time.perf_counter()
        page = await self._executor.get_page()
        site = urlparse(page.url).hostname or "*"

        action = self._infer_action(step)

        # Handle goto directly (no element selection needed)
        if action == "goto":
            url = step.arguments[0] if step.arguments else step.selector or ""
            logger.info("GOTO: %s", url)
            await self._executor.goto(url)
            await page.wait_for_load_state("domcontentloaded")
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(
                step_id=step.step_id, success=True, method="GOTO", latency_ms=elapsed
            )

        # Handle press_key directly
        if action == "press_key":
            key = step.arguments[0] if step.arguments else "Enter"
            logger.info("PRESS_KEY: %s", key)
            await self._executor.press_key(key)
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(
                step_id=step.step_id, success=True, method="KEY", latency_ms=elapsed
            )

        # Handle wait directly
        if action == "wait":
            ms = int(step.arguments[0]) if step.arguments else 2000
            logger.info("WAIT: %dms", ms)
            await page.wait_for_timeout(ms)
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(
                step_id=step.step_id, success=True, method="WAIT", latency_ms=elapsed
            )

        # Handle scroll directly
        if action == "scroll":
            direction = step.arguments[0] if step.arguments else "down"
            amount = int(step.arguments[1]) if len(step.arguments) > 1 else 300
            logger.info("SCROLL: %s %d", direction, amount)
            await self._executor.scroll(direction, amount)
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(
                step_id=step.step_id,
                success=True,
                method="SCROLL",
                latency_ms=elapsed,
            )

        # For click/type: need element selection
        # 1. Try selector from step definition first
        if step.selector:
            logger.info("Using step selector: %s", step.selector)
            try:
                await self._do_action(step.selector, action, step)
                elapsed = (time.perf_counter() - start) * 1000
                if self._cache is not None:
                    await self._cache.save(step.intent, site, step.selector, action)
                return StepResult(
                    step_id=step.step_id,
                    success=True,
                    method="SELECTOR",
                    latency_ms=elapsed,
                )
            except (AutomationError, Exception) as exc:
                logger.warning("Step selector failed: %s, trying cache/LLM", exc)

        # 2. Cache lookup
        if self._cache is not None:
            hit = await self._cache.lookup(step.intent, site)
            if hit is not None:
                logger.info("Cache HIT: %s -> %s", step.intent, hit.selector)
                try:
                    await self._do_action(hit.selector, action, step)
                    elapsed = (time.perf_counter() - start) * 1000
                    return StepResult(
                        step_id=step.step_id,
                        success=True,
                        method="CACHE",
                        latency_ms=elapsed,
                    )
                except (AutomationError, Exception) as exc:
                    logger.warning(
                        "Cache hit failed (%s), falling through to LLM", exc
                    )
                    await self._cache.invalidate(step.intent, site)

        # 3. DOM extract + LLM select
        clickables = await self._extractor.extract_clickables(page)
        inputs = await self._extractor.extract_inputs(page)
        candidates = clickables + inputs
        # Filter to visible only and deduplicate by eid
        seen_eids: set[str] = set()
        unique_candidates: list[ExtractedElement] = []
        for c in candidates:
            if c.visible and c.eid not in seen_eids:
                seen_eids.add(c.eid)
                unique_candidates.append(c)
        candidates = unique_candidates

        if not candidates:
            logger.warning("No candidates found for: %s", step.intent)
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(
                step_id=step.step_id,
                success=False,
                method="L",
                latency_ms=elapsed,
            )

        logger.info(
            "Extracted %d candidates, asking LLM to select for: %s",
            len(candidates),
            step.intent,
        )
        patch = await self._planner.select(candidates, step.intent)
        selector = patch.target
        logger.info(
            "LLM selected: %s (confidence=%.2f)", selector, patch.confidence
        )

        # 4. Execute
        try:
            await self._do_action(selector, action, step)
        except (AutomationError, Exception) as exc:
            logger.warning("Action failed on LLM-selected element: %s", exc)
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(
                step_id=step.step_id,
                success=False,
                method="L",
                latency_ms=elapsed,
            )

        # 5. Verify (if condition specified)
        if step.verify_condition is not None:
            vr = await self._verifier.verify(step.verify_condition, page)
            if not vr.success:
                logger.warning("Verification failed: %s", vr.message)
                elapsed = (time.perf_counter() - start) * 1000
                return StepResult(
                    step_id=step.step_id,
                    success=False,
                    method="L",
                    latency_ms=elapsed,
                )

        # 6. Cache save on success
        if self._cache is not None:
            await self._cache.save(step.intent, site, selector, action)

        elapsed = (time.perf_counter() - start) * 1000
        return StepResult(
            step_id=step.step_id, success=True, method="L", latency_ms=elapsed
        )

    async def _do_action(
        self, selector: str, action: str, step: StepDefinition
    ) -> None:
        """Dispatch to the appropriate executor method."""
        if action == "type":
            text = step.arguments[0] if step.arguments else ""
            await self._executor.type_text(selector, text)
        elif action == "click":
            await self._executor.click(
                selector, ClickOptions(timeout_ms=step.timeout_ms)
            )
        else:
            await self._executor.click(
                selector, ClickOptions(timeout_ms=step.timeout_ms)
            )

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
        """Infer action type from step intent, node_type, and arguments."""
        # Check node_type first (LLM may set action type here)
        nt = step.node_type.lower()
        if nt in ("goto", "click", "type", "press_key", "scroll", "wait"):
            return nt

        intent_lower = step.intent.lower()
        if any(
            kw in intent_lower
            for kw in ("입력", "type", "검색어", "작성", "write", "fill", "타이핑")
        ):
            return "type"
        if any(
            kw in intent_lower
            for kw in (
                "이동",
                "방문",
                "navigate",
                "goto",
                "go to",
                "open",
                "접속",
            )
        ):
            return "goto"
        if any(
            kw in intent_lower for kw in ("enter", "엔터", "press", "키 입력")
        ):
            return "press_key"
        if any(kw in intent_lower for kw in ("스크롤", "scroll")):
            return "scroll"
        if any(kw in intent_lower for kw in ("대기", "wait")):
            return "wait"
        return "click"
