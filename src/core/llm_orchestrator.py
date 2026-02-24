"""LLM-First Orchestrator — LLM drives every decision.

Flow per step:
  1. Cache lookup (free)
  2. Cache miss -> DOM extract -> LLM select -> Execute
  3. Verify -> Screenshot -> Cache save on success
  4. On failure: FallbackRouter classifies → exponential backoff → escalation
  5. On consecutive failures: replan remaining steps
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.core.checkpoint import CheckpointConfig, CheckpointDecision, evaluate_checkpoint
from src.core.types import (
    AutomationError,
    ClickOptions,
    ExtractedElement,
    FailureCode,
    IExecutor,
    IExtractor,
    IProgressCallback,
    IVerifier,
    PageState,
    ProgressEvent,
    ProgressInfo,
    StepContext,
    StepDefinition,
    StepResult,
)
from src.vision.batch_vision_pipeline import BatchVisionPipeline

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Result of a full automation run."""

    success: bool
    step_results: list[StepResult] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    planned_steps: list[StepDefinition] = field(default_factory=list)


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

    MAX_CAPTCHA_ATTEMPTS = 3

    # Keywords that hint the step involves batch visual items.
    _BATCH_KEYWORDS: tuple[str, ...] = (
        "product", "item", "listing", "cheapest", "compare",
        "상품", "제품", "목록", "검색결과", "가장 싼", "비교",
    )

    def __init__(
        self,
        executor: IExecutor,
        extractor: IExtractor,
        planner: Any,  # LLMPlanner with plan_with_context + solve_captcha
        verifier: IVerifier,
        cache: Any | None = None,  # SelectorCache
        screenshot_dir: Path | str = "data/screenshots",
        yolo_detector: Any | None = None,  # IYOLODetector
        vlm_client: Any | None = None,  # VLMClient with analyze_captcha
        max_cost_per_run: float = 0.05,
        batch_vision: BatchVisionPipeline | None = None,
        progress_callback: IProgressCallback | None = None,
        fallback_router: Any | None = None,  # FallbackRouter
        backoff_base_ms: int = 500,
        backoff_max_ms: int = 10_000,
        jitter_ratio: float = 0.3,
        max_consecutive_failures: int = 3,
        enable_replanning: bool = True,
        checkpoint_config: CheckpointConfig | None = None,
        adaptive_controller: Any | None = None,
        pause_event: asyncio.Event | None = None,
        cancel_flag: Any | None = None,  # object with .cancel_flag bool attribute
    ) -> None:
        self._executor = executor
        self._extractor = extractor
        self._planner = planner
        self._verifier = verifier
        self._cache = cache
        self._screenshot_dir = Path(screenshot_dir)
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._yolo = yolo_detector
        self._vlm = vlm_client
        self._max_cost_per_run = max_cost_per_run
        self._batch_vision = batch_vision
        self._progress_callback = progress_callback
        self._router = fallback_router
        self._backoff_base_ms = backoff_base_ms
        self._backoff_max_ms = backoff_max_ms
        self._jitter_ratio = jitter_ratio
        self._max_consecutive_failures = max_consecutive_failures
        self._enable_replanning = enable_replanning
        self._checkpoint_config = checkpoint_config
        self._adaptive = adaptive_controller
        self._pause_event = pause_event
        self._cancel_state = cancel_flag
        self._cost_at_run_start = 0.0

    def _emit(self, info: ProgressInfo) -> None:
        """Emit a progress event if callback is set."""
        if self._progress_callback is not None:
            self._progress_callback.on_progress(info)

    async def run(
        self,
        intent: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> RunResult:
        """Execute a user intent end-to-end.

        1. Check for CAPTCHA, solve if present
        2. Get current page context
        3. LLM decomposes intent into steps
        4. Execute each step with cache-first strategy
        5. Screenshot after every step, check for CAPTCHA after each

        Args:
            intent: Natural language instruction.
            attachments: Optional list of attachment dicts with
                filename, mime_type, and base64_data keys (for multimodal).
        """
        page = await self._executor.get_page()
        page_state = await self._extractor.extract_state(page)

        self._emit(ProgressInfo(
            event=ProgressEvent.RUN_STARTED,
            message=intent,
        ))

        # Check for CAPTCHA before starting
        if page_state.has_captcha:
            logger.warning("CAPTCHA detected before task start!")
            solved = await self._handle_captcha(page)
            if not solved:
                return RunResult(success=False)
            # Re-read page state after CAPTCHA
            page_state = await self._extractor.extract_state(page)

        # Step 0: Adaptive cache — reuse steps from previous successful runs
        site = urlparse(page_state.url).hostname or "*"
        if self._adaptive is not None:
            cached_steps = await self._adaptive.get_cached_steps(site, intent)
            if cached_steps is not None:
                logger.info("Adaptive cache HIT for %s @ %s", intent, site)
                # Convert raw dicts back to StepDefinition objects
                steps = [
                    StepDefinition(**s) if isinstance(s, dict) else s
                    for s in cached_steps
                ]
                result = RunResult(success=True, planned_steps=list(steps))
                self._cost_at_run_start = self._planner.usage.total_cost_usd
                # Execute cached steps (fall through to step-execution loop)
                return await self._execute_cached_steps(
                    steps, result, page, page_state, intent, site,
                )

        # Step 1: LLM plans the steps
        logger.info("Planning: %s", intent)
        steps = await self._planner.plan_with_context(
            instruction=intent,
            page_url=page_state.url,
            page_title=page_state.title,
            visible_text_snippet=page_state.visible_text[:500],
            attachments=attachments,
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

        result = RunResult(success=True, planned_steps=list(steps))
        self._cost_at_run_start = self._planner.usage.total_cost_usd
        consecutive_failures = 0

        # Step 2: Execute each step
        i = 0
        while i < len(steps):
            # Chat automation: check pause/cancel
            if self._pause_event is not None:
                await self._pause_event.wait()
            if self._cancel_state is not None and self._cancel_state.cancel_flag:
                logger.info("Run canceled by user")
                result.success = False
                break

            step = steps[i]
            logger.info("--- Step %d/%d: %s ---", i + 1, len(steps), step.intent)
            self._emit(ProgressInfo(
                event=ProgressEvent.STEP_STARTED,
                step_id=step.step_id,
                step_index=i,
                total_steps=len(steps),
                message=step.intent,
            ))
            step_result = await self._execute_step_with_retry(step, page_state)
            result.step_results.append(step_result)

            self._emit(ProgressInfo(
                event=(
                    ProgressEvent.STEP_COMPLETED
                    if step_result.success
                    else ProgressEvent.STEP_FAILED
                ),
                step_id=step.step_id,
                step_index=i,
                total_steps=len(steps),
                method=step_result.method,
                message=step.intent,
                result=step_result,
            ))

            # Screenshot after every step
            ss_path = await self._take_screenshot(f"step_{i + 1}_{step.step_id}")
            if ss_path:
                result.screenshots.append(ss_path)

            result.total_tokens += step_result.tokens_used
            result.total_cost_usd += step_result.cost_usd

            # Per-run cost guard
            run_cost = self._planner.usage.total_cost_usd - self._cost_at_run_start
            if run_cost > self._max_cost_per_run:
                logger.warning(
                    "Per-run cost $%.4f > limit $%.4f, stopping",
                    run_cost, self._max_cost_per_run,
                )
                result.success = False
                break

            if not step_result.success:
                consecutive_failures += 1
                logger.warning(
                    "Step %d failed (%d consecutive): %s",
                    i + 1, consecutive_failures, step.intent,
                )

                # Circuit breaker
                if consecutive_failures >= self._max_consecutive_failures:
                    logger.error(
                        "Circuit breaker: %d consecutive failures, aborting",
                        consecutive_failures,
                    )
                    result.success = False
                    break

                # Replanning: ask LLM to replan remaining steps
                if self._enable_replanning and i + 1 < len(steps):
                    remaining_intents = [s.intent for s in steps[i + 1:]]
                    try:
                        current_page_state = await self._extractor.extract_state(page)
                        new_steps = await self._planner.plan_with_context(
                            instruction=" → ".join(remaining_intents),
                            page_url=current_page_state.url,
                            page_title=current_page_state.title,
                            visible_text_snippet=current_page_state.visible_text[:500],
                        )
                        logger.info(
                            "Replanned: %d remaining steps → %d new steps",
                            len(remaining_intents), len(new_steps),
                        )
                        steps = list(steps[:i + 1]) + list(new_steps)
                        i += 1
                        continue
                    except Exception as exc:
                        logger.warning("Replanning failed: %s", exc)

                result.success = False
                break
            else:
                consecutive_failures = 0

            # Jittered wait between steps for page to settle
            await self._jittered_wait(500)

            # Wait for any navigation to settle before extracting state
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass  # Page may not have navigated

            # Refresh page state for next step's context
            try:
                page_state = await self._extractor.extract_state(page)
            except Exception as exc:
                logger.warning("State extraction failed (navigation?): %s", exc)
                await self._jittered_wait(2000)
                page_state = await self._extractor.extract_state(page)

            # Check for CAPTCHA after each step
            if page_state.has_captcha:
                logger.warning("CAPTCHA detected after step %d!", i + 1)
                solved = await self._handle_captcha(page)
                if not solved:
                    result.success = False
                    break
                page_state = await self._extractor.extract_state(page)

            i += 1

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

        self._emit(ProgressInfo(
            event=ProgressEvent.RUN_COMPLETED,
            total_steps=len(result.step_results),
            message="success" if result.success else "failed",
        ))

        # Record execution for adaptive caching
        if self._adaptive is not None:
            run_site = urlparse(page_state.url).hostname or "*"
            step_dicts = [
                {"step_id": s.step_id, "intent": s.intent,
                 "node_type": s.node_type, "selector": s.selector,
                 "arguments": s.arguments}
                for s in steps
            ]
            await self._adaptive.record_execution(
                run_site, intent, step_dicts, result.total_cost_usd, result.success,
            )

        return result

    async def _execute_cached_steps(
        self,
        steps: list[StepDefinition],
        result: RunResult,
        page: Any,
        page_state: PageState,
        intent: str,
        site: str,
    ) -> RunResult:
        """Execute steps from adaptive cache (same loop as run but skips planning)."""
        consecutive_failures = 0

        i = 0
        while i < len(steps):
            step = steps[i]
            logger.info("--- Cached Step %d/%d: %s ---", i + 1, len(steps), step.intent)
            self._emit(ProgressInfo(
                event=ProgressEvent.STEP_STARTED,
                step_id=step.step_id,
                step_index=i,
                total_steps=len(steps),
                message=step.intent,
            ))
            step_result = await self._execute_step_with_retry(step, page_state)
            result.step_results.append(step_result)

            self._emit(ProgressInfo(
                event=(
                    ProgressEvent.STEP_COMPLETED
                    if step_result.success
                    else ProgressEvent.STEP_FAILED
                ),
                step_id=step.step_id,
                step_index=i,
                total_steps=len(steps),
                method=step_result.method,
                message=step.intent,
                result=step_result,
            ))

            ss_path = await self._take_screenshot(f"step_{i + 1}_{step.step_id}")
            if ss_path:
                result.screenshots.append(ss_path)

            result.total_tokens += step_result.tokens_used
            result.total_cost_usd += step_result.cost_usd

            if not step_result.success:
                consecutive_failures += 1
                if consecutive_failures >= self._max_consecutive_failures:
                    result.success = False
                    break
                result.success = False
                break
            else:
                consecutive_failures = 0

            await self._jittered_wait(500)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            try:
                page_state = await self._extractor.extract_state(page)
            except Exception:
                await self._jittered_wait(2000)
                page_state = await self._extractor.extract_state(page)

            i += 1

        usage = self._planner.usage
        result.total_tokens = usage.total_tokens
        result.total_cost_usd = usage.total_cost_usd

        self._emit(ProgressInfo(
            event=ProgressEvent.RUN_COMPLETED,
            total_steps=len(result.step_results),
            message="success" if result.success else "failed",
        ))

        # Record result back
        if self._adaptive is not None:
            step_dicts = [
                {"step_id": s.step_id, "intent": s.intent,
                 "node_type": s.node_type, "selector": s.selector,
                 "arguments": s.arguments}
                for s in steps
            ]
            await self._adaptive.record_execution(
                site, intent, step_dicts, result.total_cost_usd, result.success,
            )

        return result

    async def _handle_captcha(self, page: Any) -> bool:
        """Detect and solve CAPTCHA using YOLO → VLM → LLM pipeline.

        Flow:
            1. Screenshot the current page
            2. YOLO26: try to understand the CAPTCHA visually (detect elements)
            3. VLM: if YOLO insufficient, analyze screenshot to describe CAPTCHA
            4. LLM: solve the CAPTCHA using the analysis (always LLM for solving)
            5. Find input, type answer, submit
            6. Verify CAPTCHA is gone

        Returns:
            True if CAPTCHA was solved, False if failed (needs human handoff).
        """
        for attempt in range(self.MAX_CAPTCHA_ATTEMPTS):
            logger.info("=== CAPTCHA solving attempt %d/%d ===", attempt + 1, self.MAX_CAPTCHA_ATTEMPTS)

            screenshot = await self._executor.screenshot()
            ss_path = await self._take_screenshot(f"captcha_attempt_{attempt + 1}")

            # --- Step 1: YOLO analysis (파악) ---
            yolo_description = ""
            if self._yolo is not None:
                try:
                    logger.info("YOLO26: analyzing CAPTCHA screenshot...")
                    detections = await self._yolo.detect(screenshot)
                    if detections:
                        labels = [d.label for d in detections]
                        yolo_description = (
                            f"YOLO detected {len(detections)} objects: "
                            + ", ".join(f"{d.label}(conf={d.confidence:.2f})" for d in detections[:10])
                        )
                        logger.info("YOLO result: %s", yolo_description)
                    else:
                        logger.info("YOLO: no objects detected, escalating to VLM")
                except Exception as exc:
                    logger.warning("YOLO analysis failed: %s, escalating to VLM", exc)

            # --- Step 2: VLM analysis (파악 — if YOLO insufficient) ---
            captcha_info: dict[str, str] = {}
            if self._vlm is not None:
                try:
                    logger.info("VLM: analyzing CAPTCHA screenshot...")
                    captcha_info = await self._vlm.analyze_captcha(screenshot)
                    if yolo_description:
                        captcha_info["yolo_context"] = yolo_description
                    logger.info(
                        "VLM result: type=%s, question=%s",
                        captcha_info.get("captcha_type"),
                        captcha_info.get("question"),
                    )
                except Exception as exc:
                    logger.warning("VLM analysis failed: %s", exc)
            elif not captcha_info:
                # No VLM available — use YOLO description as fallback context
                captcha_info = {
                    "captcha_type": "unknown",
                    "image_description": yolo_description or "Could not analyze",
                    "question": "",
                }

            if not captcha_info.get("question") and not captcha_info.get("image_description"):
                logger.warning("Cannot analyze CAPTCHA — no VLM or YOLO available")
                return False

            # --- Step 3: LLM solve (풀기 — always LLM) ---
            try:
                logger.info("LLM: solving CAPTCHA...")
                answer = await self._planner.solve_captcha(captcha_info)
                logger.info("LLM answer: %s", answer)
            except Exception as exc:
                logger.warning("LLM solve failed: %s", exc)
                continue

            if not answer:
                logger.warning("LLM returned empty answer")
                continue

            # --- Step 4: Execute solution based on CAPTCHA type ---
            captcha_type = captcha_info.get("captcha_type", "").lower()
            try:
                if "checkbox" in captcha_type or "recaptcha" in captcha_type:
                    # reCAPTCHA checkbox — need to click the checkbox in iframe
                    logger.info("CAPTCHA type: checkbox/reCAPTCHA — attempting iframe click")
                    solved_checkbox = await self._solve_recaptcha_checkbox(page)
                    if not solved_checkbox:
                        logger.warning("reCAPTCHA checkbox click failed")
                        continue
                else:
                    # Text-input CAPTCHA — type answer and submit
                    inputs = await self._extractor.extract_inputs(page)
                    visible_inputs = [i for i in inputs if i.visible]

                    if not visible_inputs:
                        logger.warning("No visible input fields found for CAPTCHA answer")
                        continue

                    captcha_input = visible_inputs[0]
                    logger.info("Typing CAPTCHA answer '%s' into %s", answer, captcha_input.eid)
                    await self._executor.type_text(captcha_input.eid, answer)

                    # Find and click submit button
                    clickables = await self._extractor.extract_clickables(page)
                    submit_candidates = [
                        c for c in clickables
                        if c.visible and c.text and any(
                            kw in (c.text or "").lower()
                            for kw in ("confirm", "submit", "확인", "제출", "입력", "verify")
                        )
                    ]

                    if submit_candidates:
                        submit_btn = submit_candidates[0]
                        logger.info("Clicking submit: %s (%s)", submit_btn.eid, submit_btn.text)
                        await self._executor.click(
                            submit_btn.eid, ClickOptions(timeout_ms=5000)
                        )
                    else:
                        logger.info("No submit button found, pressing Enter")
                        await self._executor.press_key("Enter")

                # Wait for page to process
                await page.wait_for_timeout(3000)
                await self._take_screenshot(f"captcha_after_{attempt + 1}")

            except Exception as exc:
                logger.warning("CAPTCHA solve execution failed: %s", exc)
                continue

            # --- Step 5: Verify CAPTCHA is gone ---
            try:
                page_state = await self._extractor.extract_state(page)
                if not page_state.has_captcha:
                    logger.info("CAPTCHA solved successfully!")
                    return True
                logger.warning("CAPTCHA still present after attempt %d", attempt + 1)
            except Exception as exc:
                logger.warning("CAPTCHA verification failed: %s", exc)

        logger.error("CAPTCHA solving failed after %d attempts — needs human handoff", self.MAX_CAPTCHA_ATTEMPTS)
        return False

    async def _solve_recaptcha_checkbox(self, page: Any) -> bool:
        """Try to click a reCAPTCHA v2 'I'm not a robot' checkbox.

        reCAPTCHA v2 loads inside an iframe. We need to find the iframe
        and click the checkbox inside it.

        Returns:
            True if checkbox was clicked, False otherwise.
        """
        try:
            # reCAPTCHA iframe typically has src containing "recaptcha"
            frames = page.frames
            for frame in frames:
                if "recaptcha" in (frame.url or ""):
                    logger.info("Found reCAPTCHA iframe: %s", frame.url)
                    # Click the checkbox
                    checkbox = frame.locator("#recaptcha-anchor")
                    if await checkbox.count() > 0:
                        await checkbox.click(timeout=5000)
                        logger.info("Clicked reCAPTCHA checkbox")
                        await page.wait_for_timeout(3000)
                        return True

            # Fallback: try clicking checkbox-like elements directly
            selectors = [
                "iframe[src*='recaptcha']",
                ".g-recaptcha",
                "[class*='recaptcha']",
                "#recaptcha",
            ]
            for sel in selectors:
                try:
                    el = page.locator(sel)
                    if await el.count() > 0:
                        bbox = await el.bounding_box()
                        if bbox:
                            # Click center of the reCAPTCHA widget
                            await page.mouse.click(
                                bbox["x"] + 30, bbox["y"] + 30
                            )
                            logger.info("Clicked reCAPTCHA via selector: %s", sel)
                            await page.wait_for_timeout(3000)
                            return True
                except Exception:
                    continue

            logger.warning("Could not find reCAPTCHA checkbox to click")
            return False
        except Exception as exc:
            logger.warning("reCAPTCHA checkbox click failed: %s", exc)
            return False

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
            # Normalize common key names to Playwright format
            key_map = {"enter": "Enter", "tab": "Tab", "escape": "Escape", "space": " ",
                       "backspace": "Backspace", "delete": "Delete", "arrowdown": "ArrowDown",
                       "arrowup": "ArrowUp", "arrowleft": "ArrowLeft", "arrowright": "ArrowRight"}
            key = key_map.get(key.lower(), key)
            logger.info("PRESS_KEY: %s", key)
            try:
                await self._executor.press_key(key)
            except Exception as exc:
                logger.warning("press_key failed: %s", exc)
                elapsed = (time.perf_counter() - start) * 1000
                return StepResult(step_id=step.step_id, success=False, method="KEY", latency_ms=elapsed)
            # Wait for navigation after key press
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
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
        # For "type" action, only extract inputs; for "click", both
        if action == "type":
            candidates = await self._extractor.extract_inputs(page)
        else:
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

        # --- Batch Vision shortcut ---
        if self._batch_vision and self._should_use_batch_vision(step, candidates):
            logger.info("Batch vision pipeline for: %s", step.intent)
            return await self._execute_step_with_batch_vision(
                step, candidates, start,
            )

        # Limit candidates to reduce LLM token cost
        # Prefer elements with meaningful text
        candidates_with_text = [c for c in candidates if c.text and len(c.text.strip()) > 0]
        candidates_no_text = [c for c in candidates if not c.text or len(c.text.strip()) == 0]
        limited = candidates_with_text[:40] + candidates_no_text[:10]
        candidates = limited[:50]

        logger.info(
            "Extracted %d candidates (limited), asking LLM to select for: %s",
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

    async def _execute_step_with_retry(
        self,
        step: StepDefinition,
        page_state: PageState,
    ) -> StepResult:
        """Execute a step with retry loop and FallbackRouter escalation.

        On failure:
        1. Classify error via FallbackRouter
        2. Apply exponential backoff with jitter
        3. Escalate strategy if available
        4. Return best result (or last failure)

        Args:
            step: The step to execute.
            page_state: Current page state for context.
        """
        max_attempts = step.max_attempts
        last_result: StepResult | None = None

        for attempt in range(max_attempts):
            result = await self._execute_step(step)

            if result.success:
                # Checkpoint evaluation: gate progression based on confidence
                if self._checkpoint_config is not None:
                    confidence = 0.9 if result.method == "CACHE" else 0.75
                    cp_result = evaluate_checkpoint(
                        confidence=confidence,
                        config=self._checkpoint_config,
                    )
                    if cp_result.decision == CheckpointDecision.NOT_GO:
                        logger.warning(
                            "Checkpoint NOT_GO: %s", cp_result.reason,
                        )
                        result = StepResult(
                            step_id=step.step_id,
                            success=False,
                            method=result.method,
                            latency_ms=result.latency_ms,
                        )
                        last_result = result
                        continue
                    # ASK_USER: proceed as GO (no handoff wiring yet)

                if self._router is not None and last_result is not None:
                    # Record successful recovery
                    fc = result.failure_code or FailureCode.SELECTOR_NOT_FOUND
                    self._router.record_outcome(fc, recovered=True)
                return result

            last_result = result

            # No router → no retry logic
            if self._router is None:
                return result

            # Classify the failure
            ctx = StepContext(
                step=step,
                page_state=page_state,
                attempt=attempt,
            )
            # Build an exception from the failure code for classification
            exc = AutomationError(
                f"Step {step.step_id} failed (attempt {attempt + 1})"
            )
            if result.failure_code is not None:
                exc.failure_code = result.failure_code

            failure_code = self._router.classify(exc, ctx)

            # Check if there are remaining attempts and escalation is possible
            if attempt + 1 >= max_attempts:
                self._router.record_outcome(failure_code, recovered=False)
                return result

            # Get escalation plan for next attempt
            chain = self._router.get_escalation_chain(failure_code)
            plan_idx = min(attempt, len(chain) - 1)
            plan = chain[plan_idx]

            # Immediate-handoff failures stop retrying
            if plan.strategy == "human_handoff" and plan_idx == 0:
                self._router.record_outcome(failure_code, recovered=False)
                return result

            logger.info(
                "Retry attempt %d/%d: strategy=%s, tier=%d",
                attempt + 1, max_attempts, plan.strategy, plan.tier,
            )

            # Apply backoff
            delay_ms = self._backoff_delay(attempt)
            await self._jittered_wait(delay_ms)

            # Execute recovery strategy (scroll if suggested)
            if plan.params.get("scroll"):
                try:
                    await self._executor.scroll("down", 300)
                except Exception:
                    pass

        # All attempts exhausted
        if self._router is not None and last_result is not None:
            self._router.record_outcome(
                last_result.failure_code or FailureCode.SELECTOR_NOT_FOUND,
                recovered=False,
            )
        return last_result or StepResult(
            step_id=step.step_id, success=False, method="RETRY_EXHAUSTED",
        )

    def _backoff_delay(self, attempt: int) -> int:
        """Calculate exponential backoff delay with cap.

        Args:
            attempt: Zero-based attempt index.

        Returns:
            Delay in milliseconds.
        """
        delay = self._backoff_base_ms * (2 ** attempt)
        return min(delay, self._backoff_max_ms)

    async def _jittered_wait(self, base_ms: int) -> None:
        """Wait for *base_ms* ± jitter ratio.

        Args:
            base_ms: Base wait time in milliseconds.
        """
        import asyncio
        low = base_ms * (1 - self._jitter_ratio)
        high = base_ms * (1 + self._jitter_ratio)
        ms = random.uniform(low, high)
        await asyncio.sleep(ms / 1000)

    @property
    def fallback_stats(self) -> dict[str, Any]:
        """Return FallbackRouter statistics (empty dict if no router)."""
        if self._router is not None:
            return self._router.get_stats()
        return {}

    def _should_use_batch_vision(
        self,
        step: StepDefinition,
        candidates: list[ExtractedElement],
    ) -> bool:
        """Decide whether to route through the batch vision pipeline.

        Returns True when ALL of:
        1. ``_batch_vision`` is configured.
        2. The step intent or node_type suggests a batch/visual selection.
        3. There are ≥ 3 similarly-sized candidates (height ±20%).
        """
        if self._batch_vision is None:
            return False

        # Explicit LLM planner hint.
        if step.node_type == "batch_select":
            return True

        # Keyword check.
        intent_lower = step.intent.lower()
        has_keyword = any(kw in intent_lower for kw in self._BATCH_KEYWORDS)
        if not has_keyword:
            return False

        # Size similarity check — at least 3 elements with similar heights.
        if len(candidates) < 3:
            return False

        heights = [c.bbox[3] for c in candidates if c.bbox[3] > 0]
        if len(heights) < 3:
            return False

        median_h = sorted(heights)[len(heights) // 2]
        if median_h == 0:
            return False

        similar = sum(1 for h in heights if abs(h - median_h) / median_h <= 0.20)
        return similar >= 3

    async def _execute_step_with_batch_vision(
        self,
        step: StepDefinition,
        candidates: list[ExtractedElement],
        start_time: float,
    ) -> StepResult:
        """Execute a step using the batch vision pipeline.

        1. Screenshot the current page.
        2. Build item bboxes from candidates.
        3. Run ``batch_vision.process_batch()``.
        4. Select the best item (highest confidence + relevant).
        5. Click the item's page_bbox centre.
        6. Verify if condition is specified.
        """
        assert self._batch_vision is not None
        page = await self._executor.get_page()

        try:
            screenshot = await self._executor.screenshot()

            item_bboxes = [c.bbox for c in candidates if c.bbox[2] > 0 and c.bbox[3] > 0]
            if not item_bboxes:
                logger.warning("No valid bboxes for batch vision")
                elapsed = (time.perf_counter() - start_time) * 1000
                return StepResult(
                    step_id=step.step_id, success=False, method="BV", latency_ms=elapsed,
                )

            # Get screenshot dimensions.
            import io as _io

            from PIL import Image as _PILImage
            img = _PILImage.open(_io.BytesIO(screenshot))
            ss_size = img.size  # (w, h)

            result = await self._batch_vision.process_batch(
                screenshot=screenshot,
                item_bboxes=item_bboxes,
                intent=step.intent,
                screenshot_size=ss_size,
            )

            if not result.items:
                logger.warning("Batch vision returned no items")
                elapsed = (time.perf_counter() - start_time) * 1000
                return StepResult(
                    step_id=step.step_id, success=False, method="BV", latency_ms=elapsed,
                )

            # Pick the best: prefer relevant VLM items, then highest confidence.
            relevant_items = [
                it for it in result.items
                if it.extra.get("relevant", True)  # YOLO items default True
            ]
            pool = relevant_items if relevant_items else result.items
            best = max(pool, key=lambda it: it.confidence)

            # Click the centre of the best item's page bbox.
            bx, by, bw, bh = best.page_bbox
            cx = bx + bw // 2
            cy = by + bh // 2
            logger.info(
                "Batch vision selected cell %d (%s, conf=%.2f), clicking (%d, %d)",
                best.cell_index, best.label, best.confidence, cx, cy,
            )
            await page.mouse.click(cx, cy)

            # Verify if condition specified.
            if step.verify_condition is not None:
                vr = await self._verifier.verify(step.verify_condition, page)
                if not vr.success:
                    logger.warning("Batch vision verification failed: %s", vr.message)
                    elapsed = (time.perf_counter() - start_time) * 1000
                    return StepResult(
                        step_id=step.step_id, success=False, method="BV", latency_ms=elapsed,
                    )

            elapsed = (time.perf_counter() - start_time) * 1000
            return StepResult(
                step_id=step.step_id, success=True, method="BV", latency_ms=elapsed,
            )

        except Exception as exc:
            logger.warning("Batch vision pipeline failed: %s, falling back to LLM", exc)
            elapsed = (time.perf_counter() - start_time) * 1000
            return StepResult(
                step_id=step.step_id, success=False, method="BV", latency_ms=elapsed,
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
