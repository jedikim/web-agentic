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
import contextlib
import json
import logging
import random
import re
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
from src.observability.tracing import trace, update_current_trace
from src.vision.batch_vision_pipeline import BatchVisionPipeline

logger = logging.getLogger(__name__)


def _sanitize_selector(selector: str) -> str:
    """Normalize a CSS selector returned by the LLM.

    Playwright cannot parse selectors containing raw newlines or tabs
    (raises BADSTRING). This collapses all whitespace inside :has-text()
    quoted strings and strips leading/trailing whitespace.
    """
    def _collapse_ws(m: re.Match[str]) -> str:
        prefix = m.group(1)  # :has-text("
        text = m.group(2)    # inner text
        suffix = m.group(3)  # ")
        cleaned = re.sub(r"\s+", " ", text).strip()
        return f"{prefix}{cleaned}{suffix}"

    result = re.sub(
        r'(:has-text\(["\'])(.+?)(["\']\))',
        _collapse_ws,
        selector,
        flags=re.DOTALL,
    )
    return result.strip()


@dataclass
class RunResult:
    """Result of a full automation run."""

    success: bool
    step_results: list[StepResult] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    planned_steps: list[StepDefinition] = field(default_factory=list)
    result_summary: str = ""


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
        max_cost_per_run: float = 0.25,
        batch_vision: BatchVisionPipeline | None = None,
        progress_callback: IProgressCallback | None = None,
        fallback_router: Any | None = None,  # FallbackRouter
        backoff_base_ms: int = 500,
        backoff_max_ms: int = 10_000,
        jitter_ratio: float = 0.3,
        max_consecutive_failures: int = 5,
        max_total_steps: int = 30,
        enable_replanning: bool = True,
        checkpoint_config: CheckpointConfig | None = None,
        adaptive_controller: Any | None = None,
        pause_event: asyncio.Event | None = None,
        cancel_flag: Any | None = None,  # object with .cancel_flag bool attribute
        candidate_filter: Any | None = None,  # CandidateFilterPipeline
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
        self._max_total_steps = max_total_steps
        self._enable_replanning = enable_replanning
        self._checkpoint_config = checkpoint_config
        self._adaptive = adaptive_controller
        self._pause_event = pause_event
        self._cancel_state = cancel_flag
        self._candidate_filter = candidate_filter
        self._cost_at_run_start = 0.0
        self._used_selectors: set[str] = set()  # track used selectors per run
        self._last_hover_selector: str | None = None  # maintain hover state for dropdowns

    def _emit(self, info: ProgressInfo) -> None:
        """Emit a progress event if callback is set."""
        if self._progress_callback is not None:
            self._progress_callback.on_progress(info)

    @trace(name="orchestrator-run")
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
        update_current_trace(
            name=f"run: {intent[:80]}",
            metadata={"url": page_state.url},
        )

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
        total_click_failures = 0  # persists across replans for strategy switching
        total_steps_executed = 0
        previous_action = ""
        self._used_selectors = set()  # reset per run
        self._last_hover_selector = None

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
            step_result = await self._execute_step_with_retry(
                step, page_state, previous_action=previous_action,
            )
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
            total_steps_executed += 1

            # Max total steps guard
            if total_steps_executed >= self._max_total_steps:
                logger.warning(
                    "Max total steps %d reached, stopping",
                    self._max_total_steps,
                )
                break

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
                previous_action = f"FAILED: {step.intent}"
                failed_action = self._infer_action(step)

                # visual_evaluate failure is non-fatal — skip and continue
                # (e.g. missing YOLO deps shouldn't trigger a full replan)
                if failed_action == "visual_evaluate":
                    logger.warning(
                        "visual_evaluate failed, skipping to next step: %s",
                        step.intent,
                    )
                    i += 1
                    continue

                consecutive_failures += 1
                if failed_action in ("click", "hover"):
                    total_click_failures += 1
                logger.warning(
                    "Step %d failed (%d consecutive, %d click fails total): %s",
                    i + 1, consecutive_failures, total_click_failures, step.intent,
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
                        # Include failure context with strong redirect to search
                        strategy_hint = ""
                        if total_click_failures >= 4:
                            strategy_hint = (
                                " Menu/category navigation has failed. "
                                "SWITCH STRATEGY: Use the SEARCH box to search for "
                                "the target category/product name directly. "
                                "Do NOT try clicking sidebar or menu items again."
                            )
                        replan_instruction = (
                            f"[FAILED: '{step.intent}' — this approach does not work.{strategy_hint}] "
                            f"Original task: {intent}. "
                            f"Remaining goals: {' → '.join(remaining_intents)}"
                        )
                        new_steps = await self._planner.plan_with_context(
                            instruction=replan_instruction,
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
                previous_action = f"Completed: {step.intent}"

            # After a successful goto, replan remaining steps with new page context.
            # Steps planned from about:blank have no knowledge of the actual site DOM.
            action = self._infer_action(step)
            if (
                action == "goto"
                and self._enable_replanning
                and i + 1 < len(steps)
            ):
                remaining_intents = [s.intent for s in steps[i + 1:]]
                try:
                    current_page_state = await self._extractor.extract_state(
                        page,
                    )
                    new_steps = await self._planner.plan_with_context(
                        instruction=" → ".join(remaining_intents),
                        page_url=current_page_state.url,
                        page_title=current_page_state.title,
                        visible_text_snippet=current_page_state.visible_text[:500],
                    )
                    logger.info(
                        "Post-goto replan: %d old remaining → %d new steps",
                        len(remaining_intents),
                        len(new_steps),
                    )
                    steps = list(steps[: i + 1]) + list(new_steps)
                    result.planned_steps = list(steps)
                except Exception as exc:
                    logger.warning("Post-goto replan failed: %s", exc)

            # Jittered wait between steps for page to settle
            await self._jittered_wait(500)

            # Wait for any navigation to settle before extracting state
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("domcontentloaded", timeout=5000)

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

        # Goal completion check: if all steps succeeded but task may not
        # be fully done, ask LLM to assess and replan if needed.
        if (
            result.success
            and self._enable_replanning
            and total_steps_executed < self._max_total_steps
        ):
            run_cost = (
                self._planner.usage.total_cost_usd - self._cost_at_run_start
            )
            if run_cost < self._max_cost_per_run:
                try:
                    current_ps = await self._extractor.extract_state(page)
                    completion_prompt = (
                        f"Original task: {intent}\n"
                        f"Current page URL: {current_ps.url}\n"
                        f"Current page title: {current_ps.title}\n"
                        f"Visible text: {current_ps.visible_text[:300]}\n\n"
                        "Has the task been fully completed? "
                        "If NOT, return remaining steps as JSON. "
                        "If YES, return: {\"complete\": true}"
                    )
                    resp, tokens = await self._planner._call_gemini(
                        completion_prompt, self._planner.tier1_model,
                    )
                    self._planner.usage.record(
                        self._planner.tier1_model, tokens,
                    )
                    if '"complete"' not in resp.lower() or '"steps"' in resp:
                        try:
                            extra_steps, _ = self._planner._parse_plan_response(
                                resp,
                            )
                            if extra_steps:
                                logger.info(
                                    "Goal incomplete, %d more steps planned",
                                    len(extra_steps),
                                )
                                steps = list(steps) + list(extra_steps)
                                result.planned_steps = list(steps)
                                # Continue executing the new steps
                                while i < len(steps):
                                    if total_steps_executed >= self._max_total_steps:
                                        break
                                    run_cost = (
                                        self._planner.usage.total_cost_usd
                                        - self._cost_at_run_start
                                    )
                                    if run_cost > self._max_cost_per_run:
                                        break
                                    step = steps[i]
                                    logger.info(
                                        "--- Extra step %d/%d: %s ---",
                                        i + 1, len(steps), step.intent,
                                    )
                                    self._emit(ProgressInfo(
                                        event=ProgressEvent.STEP_STARTED,
                                        step_id=step.step_id,
                                        step_index=i,
                                        total_steps=len(steps),
                                        message=step.intent,
                                    ))
                                    sr = await self._execute_step_with_retry(
                                        step, page_state,
                                        previous_action=previous_action,
                                    )
                                    result.step_results.append(sr)
                                    self._emit(ProgressInfo(
                                        event=(
                                            ProgressEvent.STEP_COMPLETED
                                            if sr.success
                                            else ProgressEvent.STEP_FAILED
                                        ),
                                        step_id=step.step_id,
                                        step_index=i,
                                        total_steps=len(steps),
                                        method=sr.method,
                                        message=step.intent,
                                        result=sr,
                                    ))
                                    ss = await self._take_screenshot(
                                        f"extra_{i + 1}_{step.step_id}",
                                    )
                                    if ss:
                                        result.screenshots.append(ss)
                                    total_steps_executed += 1
                                    if not sr.success:
                                        previous_action = f"FAILED: {step.intent}"
                                        consecutive_failures += 1
                                        if consecutive_failures >= self._max_consecutive_failures:
                                            break
                                    else:
                                        consecutive_failures = 0
                                        previous_action = f"Completed: {step.intent}"
                                    await self._jittered_wait(500)
                                    with contextlib.suppress(Exception):
                                        await page.wait_for_load_state(
                                            "domcontentloaded", timeout=5000,
                                        )
                                    try:
                                        page_state = await self._extractor.extract_state(page)
                                    except Exception:
                                        await self._jittered_wait(2000)
                                        page_state = await self._extractor.extract_state(page)
                                    i += 1
                        except (json.JSONDecodeError, ValueError, KeyError):
                            pass  # LLM said complete or malformed
                except Exception as exc:
                    logger.warning("Goal completion check failed: %s", exc)

        # Final summary — ask LLM to summarize what was accomplished
        result.result_summary = await self._generate_result_summary(
            intent, result, page, page_state,
        )

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
        if result.result_summary:
            logger.info("Result summary: %s", result.result_summary[:200])

        self._emit(ProgressInfo(
            event=ProgressEvent.RUN_COMPLETED,
            total_steps=len(result.step_results),
            message=result.result_summary or ("success" if result.success else "failed"),
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
        previous_action = ""

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
            step_result = await self._execute_step_with_retry(
                step, page_state, previous_action=previous_action,
            )
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
                previous_action = f"FAILED: {step.intent}"
                consecutive_failures += 1
                if consecutive_failures >= self._max_consecutive_failures:
                    result.success = False
                    break
                result.success = False
                break
            else:
                consecutive_failures = 0
                previous_action = f"Completed: {step.intent}"

            await self._jittered_wait(500)
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
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

        Flow (LLM-First):
            1. Screenshot + YOLO/VLM analysis (existing, already generic)
            2. LLM solves the CAPTCHA answer (existing, already generic)
            3. LLM plans the action sequence (NEW — replaces hardcoded branches)
            4. Execute planned actions via generic executor
            5. Verify CAPTCHA is gone

        Returns:
            True if CAPTCHA was solved, False if failed (needs human handoff).
        """
        for attempt in range(self.MAX_CAPTCHA_ATTEMPTS):
            logger.info(
                "=== CAPTCHA solving attempt %d/%d ===",
                attempt + 1, self.MAX_CAPTCHA_ATTEMPTS,
            )

            screenshot = await self._executor.screenshot()
            await self._take_screenshot(f"captcha_attempt_{attempt + 1}")

            # --- Step 1: YOLO analysis (existing, already generic) ---
            yolo_description = ""
            if self._yolo is not None:
                try:
                    logger.info("YOLO26: analyzing CAPTCHA screenshot...")
                    detections = await self._yolo.detect(screenshot)
                    if detections:
                        yolo_description = (
                            f"YOLO detected {len(detections)} objects: "
                            + ", ".join(
                                f"{d.label}(conf={d.confidence:.2f})"
                                for d in detections[:10]
                            )
                        )
                        logger.info("YOLO result: %s", yolo_description)
                    else:
                        logger.info("YOLO: no objects detected, escalating to VLM")
                except Exception as exc:
                    logger.warning("YOLO analysis failed: %s, escalating to VLM", exc)

            # --- Step 2: VLM analysis (existing, already generic) ---
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
                captcha_info = {
                    "captcha_type": "unknown",
                    "image_description": yolo_description or "Could not analyze",
                    "question": "",
                }

            if not captcha_info.get("question") and not captcha_info.get("image_description"):
                logger.warning("Cannot analyze CAPTCHA — no VLM or YOLO available")
                return False

            # --- Step 3: LLM solve answer (existing, already generic) ---
            try:
                logger.info("LLM: solving CAPTCHA...")
                answer = await self._planner.solve_captcha(captcha_info)
                logger.info("LLM answer: %s", answer)
            except Exception as exc:
                logger.warning("LLM solve failed: %s", exc)
                continue

            # --- Step 4: LLM plans action sequence (NEW — replaces hardcoded branches) ---
            try:
                elements = await self._extractor.extract_inputs(page)
                clickables = await self._extractor.extract_clickables(page)
                all_elements = elements + clickables

                action_plan = await self._planner.plan_captcha_action(
                    {**captcha_info, "answer": answer or ""}, all_elements,
                )
                logger.info(
                    "CAPTCHA action plan: %d actions, reasoning=%s",
                    len(action_plan.actions), action_plan.reasoning,
                )

                if not action_plan.actions:
                    logger.warning("LLM returned empty CAPTCHA action plan")
                    continue

                # Execute each planned action
                for act in action_plan.actions:
                    await self._execute_captcha_action(page, act, all_elements)

                # Wait for page to process
                await page.wait_for_timeout(2000)
                await self._take_screenshot(f"captcha_after_{attempt + 1}")

            except Exception as exc:
                logger.warning("CAPTCHA action execution failed: %s", exc)
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

        logger.error(
            "CAPTCHA solving failed after %d attempts — needs human handoff",
            self.MAX_CAPTCHA_ATTEMPTS,
        )
        return False

    async def _execute_captcha_action(
        self,
        page: Any,
        action: Any,
        elements: list[ExtractedElement],
    ) -> None:
        """Execute a single LLM-planned CAPTCHA action.

        Args:
            page: Playwright page instance.
            action: CaptchaAction with action type, target, and value.
            elements: Extracted DOM elements for target matching.
        """
        target_el = self._find_element_by_description(elements, action.target)
        logger.info(
            "CAPTCHA action: %s target=%s value=%s",
            action.action, action.target, action.value,
        )

        if action.action == "click":
            if target_el:
                await self._executor.click(
                    target_el.eid, ClickOptions(timeout_ms=5000),
                )
            else:
                logger.warning("No matching element for click target: %s", action.target)
        elif action.action == "type":
            if target_el:
                await self._executor.type_text(target_el.eid, action.value)
            else:
                logger.warning("No matching element for type target: %s", action.target)
        elif action.action == "press_key":
            key = action.value or "Enter"
            await self._executor.press_key(key)

    @staticmethod
    def _find_element_by_description(
        elements: list[ExtractedElement], description: str,
    ) -> ExtractedElement | None:
        """Find the best matching element by text description.

        Args:
            elements: List of extracted elements.
            description: LLM-provided description of the target element.

        Returns:
            Best matching element or None.
        """
        if not description:
            return None
        desc_lower = description.lower()
        best: ExtractedElement | None = None
        best_score = 0
        for el in elements:
            if not el.visible:
                continue
            # Score by overlap of description words in element text/eid
            el_text = ((el.text or "") + " " + el.eid).lower()
            words = desc_lower.split()
            score = sum(1 for w in words if w in el_text)
            if score > best_score:
                best_score = score
                best = el
        return best

    @staticmethod
    def _build_page_context(page_state: PageState, previous_action: str = "") -> str:
        """Build a short page context string for LLM element selection.

        Args:
            page_state: Current page state snapshot.
            previous_action: Description of the most recent action.

        Returns:
            Multi-line context string, or empty string if no useful info.
        """
        parts: list[str] = ["Page context:"]
        if page_state.url:
            parts.append(f"- URL: {page_state.url}")
        if page_state.title:
            parts.append(f"- Title: {page_state.title}")
        if page_state.visible_text:
            snippet = page_state.visible_text[:200].replace("\n", " ").strip()
            parts.append(f"- Visible text: {snippet}")
        if previous_action:
            parts.append(f"- Previous action: {previous_action}")
        return "\n".join(parts) if len(parts) > 1 else ""

    @trace(name="execute-step")
    async def _execute_step(
        self, step: StepDefinition, page_context: str = "",
    ) -> StepResult:
        """Execute a single step: Cache -> LLM Select -> Execute -> Verify."""
        start = time.perf_counter()
        page = await self._executor.get_page()
        site = urlparse(page.url).hostname or "*"

        action = self._infer_action(step)

        # Clear hover state on actions that move the page or mouse focus.
        # Keep hover state through "wait" and "scroll" — they don't break the dropdown chain.
        if action not in ("click", "hover", "wait", "scroll"):
            self._last_hover_selector = None

        # Handle goto directly (no element selection needed)
        if action == "goto":
            url = step.arguments[0] if step.arguments else step.selector or ""
            logger.info("GOTO: %s", url)
            await self._executor.goto(url)
            await page.wait_for_load_state("domcontentloaded")
            # Also wait for network to settle so JS-heavy sites fully render
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("networkidle", timeout=8000)
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
                return StepResult(
                    step_id=step.step_id, success=False,
                    method="KEY", latency_ms=elapsed,
                )
            # Wait for navigation after key press
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
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
            raw_dir = step.arguments[0] if step.arguments else "down"
            # LLM sometimes generates numbers or unusual values for direction
            direction = raw_dir if raw_dir in ("up", "down", "left", "right") else "down"
            try:
                amount = int(step.arguments[1]) if len(step.arguments) > 1 else 300
            except (ValueError, TypeError):
                amount = 300  # LLM sometimes generates 'window', 'full', etc.
            logger.info("SCROLL: %s %d", direction, amount)
            await self._executor.scroll(direction, amount)
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(
                step_id=step.step_id,
                success=True,
                method="SCROLL",
                latency_ms=elapsed,
            )

        # Handle hover: find element and hover over it (for dropdown menus)
        if action == "hover":
            return await self._execute_hover(step, start, page, page_context=page_context)

        # Handle visual_evaluate: screenshot → YOLO detect → grid → VLM analyze
        if action == "visual_evaluate":
            return await self._execute_visual_evaluate(step, start)

        # For click/type: need element selection
        # 1. Try selector from step definition with SHORT timeout (quick probe)
        #    LLM-generated selectors are often guesses; don't waste 10s waiting.
        if step.selector:
            logger.info("Quick-probing step selector (2s): %s", step.selector)
            probe_step = StepDefinition(
                step_id=step.step_id,
                intent=step.intent,
                selector=step.selector,
                arguments=step.arguments,
                timeout_ms=2000,
                max_attempts=1,
                node_type=step.node_type,
            )
            try:
                await self._do_action(step.selector, action, probe_step)
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
                logger.warning("Step selector failed (quick probe): %s, trying cache/LLM", exc)

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
        # If a hover step just revealed a dropdown, re-hover the parent element
        # to keep the dropdown visible while we extract candidates.
        if self._last_hover_selector is not None and action == "click":
            try:
                logger.info(
                    "Re-hovering %s to keep dropdown visible for extraction",
                    self._last_hover_selector,
                )
                await self._executor.hover(self._last_hover_selector)
                await page.wait_for_timeout(600)
            except Exception as exc:
                logger.warning("Re-hover failed: %s (dropdown may not be visible)", exc)

        # Dropdown/category shortcut: when a click step targets a specific
        # product subcategory, try to find the URL directly from DOM (including
        # hidden links in dynamic flyout layers).
        # Only activate for intents with SPECIFIC category names — not generic
        # "open the category panel" intents.
        _specific_cat_kw = (
            "등산", "의류", "골프", "러닝", "요가", "수영", "캠핑",
            "아웃도어", "트레이닝", "바람막이", "패딩", "레저",
        )
        _intent_lower = step.intent.lower()
        _is_specific_category_click = action == "click" and any(
            kw in _intent_lower for kw in _specific_cat_kw
        )
        if _is_specific_category_click:
            try:
                dropdown_url = await self._find_dropdown_link(page, step.intent)
                if dropdown_url:
                    logger.info(
                        "Dropdown shortcut: navigating directly to %s",
                        dropdown_url,
                    )
                    await self._executor.goto(dropdown_url)
                    with contextlib.suppress(Exception):
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    with contextlib.suppress(Exception):
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    self._last_hover_selector = None
                    elapsed = (time.perf_counter() - start) * 1000
                    return StepResult(
                        step_id=step.step_id, success=True,
                        method="DROPDOWN_NAV", latency_ms=elapsed,
                    )
            except Exception as exc:
                logger.warning("Dropdown shortcut failed: %s", exc)

        # For "type" action, only extract inputs; for "click", both
        if action == "type":
            candidates = await self._extractor.extract_inputs(page)
        else:
            clickables = await self._extractor.extract_clickables(page)
            inputs = await self._extractor.extract_inputs(page)
            candidates = clickables + inputs
        # Filter to visible only and deduplicate by eid
        total_raw = len(candidates)
        visible_count = sum(1 for c in candidates if c.visible)
        seen_eids: set[str] = set()
        unique_candidates: list[ExtractedElement] = []
        for c in candidates:
            if c.visible and c.eid not in seen_eids:
                seen_eids.add(c.eid)
                unique_candidates.append(c)
        candidates = unique_candidates
        logger.info(
            "Candidates: %d raw → %d visible → %d unique (hover_active=%s)",
            total_raw, visible_count, len(candidates),
            self._last_hover_selector is not None,
        )

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

        # Limit candidates: 2-stage filter (structural + optional vector) or legacy keyword.
        # When hover is active (dropdown scenario), use keyword ranking with a larger limit
        # because the structural filter may exclude dropdown items (different DOM region).
        if self._last_hover_selector is not None and action == "click":
            logger.info(
                "Dropdown click: using keyword ranking (limit=120) instead of structural filter"
            )
            candidates = _rank_candidates_by_intent(candidates, step.intent, limit=120)
        elif self._candidate_filter is not None:
            _fr = await self._candidate_filter.filter(candidates, step.intent)
            candidates = _fr.candidates
        else:
            candidates = _rank_candidates_by_intent(candidates, step.intent, limit=50)

        logger.info(
            "Extracted %d candidates (filtered), asking LLM to select for: %s",
            len(candidates),
            step.intent,
        )
        # Debug: log candidate summary for post-run analysis
        for _ci, _c in enumerate(candidates[:10]):
            logger.debug(
                "  candidate[%d]: eid=%s type=%s text=%.60s",
                _ci, _c.eid, _c.type, (_c.text or "").replace("\n", " "),
            )

        patch = await self._planner.select(candidates, step.intent, page_context=page_context)
        selector = _sanitize_selector(patch.target)
        logger.info(
            "LLM selected: %s (confidence=%.2f)", selector, patch.confidence
        )

        # Duplicate-click guard: if the LLM selected the same element as a
        # previous click/hover in this plan, reject it and fail the step
        # so replanning can try a different strategy (e.g. search).
        if selector in self._used_selectors and action in ("click", "hover"):
            logger.warning(
                "Duplicate selector detected: %s (already used). "
                "Failing step to trigger replan with different strategy.",
                selector,
            )
            elapsed = (time.perf_counter() - start) * 1000
            return StepResult(
                step_id=step.step_id, success=False,
                method="L", latency_ms=elapsed,
            )

        # Track this selector for future duplicate detection
        if action in ("click", "hover"):
            self._used_selectors.add(selector)

        # Clear hover state — the dropdown click was either attempted or skipped.
        if action == "click":
            self._last_hover_selector = None

        # 4. Execute (with JS click fallback for hidden elements)
        try:
            await self._do_action(selector, action, step)
        except (AutomationError, Exception) as exc:
            logger.warning("Action failed on LLM-selected element: %s", exc)
            # Fallback: try JavaScript click for elements that exist but aren't interactable
            if action == "click":
                try:
                    js_result = await page.evaluate(
                        """(sel) => {
                            // Extract text from Playwright :has-text() selector
                            const textMatch = sel.match(/:has-text\\("([^"]+)"\\)/);
                            if (textMatch) {
                                const searchText = textMatch[1];
                                const tag = sel.split(':')[0] || '*';
                                const query = tag === '*'
                                    ? 'a, button, [role="link"], [role="button"]'
                                    : tag;
                                const els = [...document.querySelectorAll(query)];
                                // Find element with matching text (visible or hidden — it may be in a dropdown)
                                const match = els.find(el =>
                                    el.textContent && el.textContent.trim().includes(searchText)
                                );
                                if (match) {
                                    // If it's a link with an href, return the URL for direct navigation
                                    const link = match.closest('a[href]');
                                    if (link && link.href && !link.href.endsWith('#')) {
                                        return {clicked: false, href: link.href};
                                    }
                                    match.scrollIntoView({block: 'center'});
                                    match.click();
                                    return {clicked: true, href: null};
                                }
                                return {clicked: false, href: null};
                            }
                            // Standard CSS selector fallback
                            try {
                                const el = document.querySelector(sel);
                                if (el) {
                                    const link = el.closest('a[href]') || el.querySelector('a[href]');
                                    if (link && link.href && !link.href.endsWith('#')) {
                                        return {clicked: false, href: link.href};
                                    }
                                    el.click();
                                    return {clicked: true, href: null};
                                }
                            } catch(e) {}
                            return {clicked: false, href: null};
                        }""",
                        selector,
                    )
                    if js_result.get("href"):
                        # Direct navigation to the link URL (more reliable for dropdown links)
                        logger.info(
                            "JS fallback: navigating to href %s for: %s",
                            js_result["href"], selector,
                        )
                        await self._executor.goto(js_result["href"])
                        with contextlib.suppress(Exception):
                            await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    elif js_result.get("clicked"):
                        logger.info("JS click fallback succeeded for: %s", selector)
                        with contextlib.suppress(Exception):
                            await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    else:
                        elapsed = (time.perf_counter() - start) * 1000
                        return StepResult(
                            step_id=step.step_id, success=False,
                            method="L", latency_ms=elapsed,
                        )
                except Exception as js_exc:
                    logger.warning("JS click fallback also failed: %s", js_exc)
                    elapsed = (time.perf_counter() - start) * 1000
                    return StepResult(
                        step_id=step.step_id, success=False,
                        method="L", latency_ms=elapsed,
                    )
            else:
                elapsed = (time.perf_counter() - start) * 1000
                return StepResult(
                    step_id=step.step_id, success=False,
                    method="L", latency_ms=elapsed,
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

    @trace(name="execute-step-with-retry")
    async def _execute_step_with_retry(
        self,
        step: StepDefinition,
        page_state: PageState,
        previous_action: str = "",
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
            previous_action: Description of the previous action for LLM context.
        """
        max_attempts = step.max_attempts
        last_result: StepResult | None = None

        for attempt in range(max_attempts):
            page_context = self._build_page_context(page_state, previous_action)
            result = await self._execute_step(step, page_context=page_context)

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
                with contextlib.suppress(Exception):
                    await self._executor.scroll("down", 300)

            # Refresh page state for next retry (avoid stale context)
            try:
                page = await self._executor.get_page()
                page_state = await self._extractor.extract_state(page)
            except Exception:
                pass  # keep previous page_state

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

    async def _generate_result_summary(
        self,
        intent: str,
        result: RunResult,
        page: Any,
        page_state: PageState,
    ) -> str:
        """Ask LLM to summarize the final result with a screenshot."""
        try:
            screenshot = await self._executor.screenshot()
            import base64 as _b64
            img_b64 = _b64.b64encode(screenshot).decode()

            current_ps = await self._extractor.extract_state(page)
            steps_ok = sum(1 for r in result.step_results if r.success)
            steps_total = len(result.step_results)

            summary_prompt = (
                f"Original task: {intent}\n"
                f"Result: {'SUCCESS' if result.success else 'FAILED'} "
                f"({steps_ok}/{steps_total} steps succeeded)\n"
                f"Current page URL: {current_ps.url}\n"
                f"Current page title: {current_ps.title}\n"
                f"Visible text (excerpt): {current_ps.visible_text[:300]}\n\n"
                "Look at the screenshot and write a SHORT summary (2-3 sentences) "
                "of what was accomplished. If a specific item was found, describe it "
                "(name, price, key details). Write in the SAME LANGUAGE as the original task."
            )
            resp, tokens = await self._planner._call_gemini(
                summary_prompt, self._planner.tier1_model,
                images=[{"mime_type": "image/png", "base64_data": img_b64}],
            )
            self._planner.usage.record(self._planner.tier1_model, tokens)
            # Clean up markdown fences if present
            summary = resp.strip()
            if summary.startswith("```"):
                summary = summary.split("\n", 1)[-1]
            if summary.endswith("```"):
                summary = summary.rsplit("```", 1)[0]
            return summary.strip()
        except Exception as exc:
            logger.warning("Result summary generation failed: %s", exc)
            return ""

    async def _execute_hover(
        self,
        step: StepDefinition,
        start_time: float,
        page: Any,
        page_context: str = "",
    ) -> StepResult:
        """Execute a hover step — hover over an element to reveal dropdown menus etc."""
        candidates = await self._extractor.extract_clickables(page)
        if self._candidate_filter is not None:
            _fr = await self._candidate_filter.filter(candidates, step.intent)
            candidates = _fr.candidates
        else:
            candidates = _rank_candidates_by_intent(candidates, step.intent, limit=30)
        if not candidates:
            logger.warning("Hover: no candidates found for: %s", step.intent)
            elapsed = (time.perf_counter() - start_time) * 1000
            return StepResult(
                step_id=step.step_id, success=False,
                method="HOVER", latency_ms=elapsed,
            )

        patch = await self._planner.select(candidates, step.intent, page_context=page_context)
        selector = _sanitize_selector(patch.target)
        logger.info("Hover: LLM selected %s (conf=%.2f)", selector, patch.confidence)
        self._used_selectors.add(selector)

        try:
            await self._executor.hover(selector)
            await page.wait_for_timeout(800)  # wait for dropdown to fully appear
            # Store hover selector so the next click step can re-hover
            # to keep the dropdown visible during candidate extraction.
            self._last_hover_selector = selector
            elapsed = (time.perf_counter() - start_time) * 1000
            return StepResult(
                step_id=step.step_id, success=True,
                method="HOVER", latency_ms=elapsed,
            )
        except Exception as exc:
            logger.warning("Hover failed: %s", exc)
            self._last_hover_selector = None
            elapsed = (time.perf_counter() - start_time) * 1000
            return StepResult(
                step_id=step.step_id, success=False,
                method="HOVER", latency_ms=elapsed,
            )

    async def _find_dropdown_link(
        self, page: Any, intent: str,
    ) -> str | None:
        """Extract links from dynamic dropdown/category layers and find best match.

        Two-phase approach:
        1. Quick scan: check ALL links on the page (including hidden ones in
           dynamically created layers) for keyword matches.
        2. Category panel fallback: if quick scan finds nothing, try opening the
           site's full category panel (e.g. "전체 카테고리" button) and hovering
           category links to reveal flyout layers with subcategory links.

        Returns the href URL if a good match is found, or None otherwise.
        This is a zero-LLM-cost shortcut: keyword matching only.
        """
        all_words = re.findall(r"[\w가-힣]{2,}", intent.lower())
        if not all_words:
            return None

        # Filter out generic action words; keep only likely category names
        _generic = {
            "카테고리", "메뉴", "메뉴에서", "드롭다운", "링크", "클릭",
            "버튼", "선택", "이동", "열기", "닫기", "확인", "찾기",
            "관련", "내의", "항목", "또는", "위해", "전체", "패널",
            "페이지", "사이드바", "탭", "마우스", "호버", "서브",
            "링크를", "찾아", "클릭합니다", "합니다", "입니다",
            "가격", "필터", "적용", "검색", "입력", "설정",
            "상품", "목록", "결과", "대기", "로드", "스크롤",
        }
        words = [w for w in all_words if w not in _generic]
        if not words:
            logger.debug("_find_dropdown_link: no specific keywords in intent")
            return None

        logger.info(
            "_find_dropdown_link: searching for %s (from intent: %s)",
            words[:6], intent[:60],
        )

        # Phase 1: Quick scan — all links on current page (including hidden)
        result = await self._scan_all_links(page, words)
        if result:
            logger.info("_find_dropdown_link: Phase 1 (quick scan) found match")
            return result
        logger.info("_find_dropdown_link: Phase 1 no match, trying Phase 2 (category panel)")

        # Phase 2: Try opening category panel and hovering flyout layers
        return await self._open_category_panel_and_find(page, words)

    async def _scan_all_links(
        self, page: Any, words: list[str],
    ) -> str | None:
        """Scan all links on the page for keyword matches."""
        js = """() => {
            const curUrl = location.origin + location.pathname;
            const links = document.querySelectorAll('a[href]');
            const results = [];
            for (const a of links) {
                const href = a.getAttribute('href') || '';
                if (!href || href === '#' || href.startsWith('javascript:'))
                    continue;
                // Skip same-page hash anchors (e.g. "#top100_13")
                if (href.startsWith('#')) continue;
                const fullHref = a.href || '';
                // Skip links that only differ by hash fragment
                const hrefBase = fullHref.split('#')[0];
                if (hrefBase === curUrl || hrefBase === curUrl + '/')
                    continue;
                const text = (a.textContent || '').trim();
                if (!text || text.length > 100) continue;
                let ctx = '';
                let el = a.parentElement;
                for (let i = 0; i < 10 && el; i++) {
                    const prev = el.previousElementSibling;
                    if (prev) {
                        const prevText = (prev.textContent || '').trim();
                        if (prevText.length > 1 && prevText.length < 30) {
                            ctx = prevText + ' ' + ctx;
                        }
                    }
                    const cls = (el.className || '').toString();
                    if (cls.includes('depth') || cls.includes('category')
                        || cls.includes('sub') || cls.includes('layer')) {
                        const catText = el.querySelector('a, span, strong');
                        if (catText) {
                            ctx = (catText.textContent || '').trim() + ' ' + ctx;
                        }
                        break;
                    }
                    el = el.parentElement;
                }
                results.push({text, href: a.href, ctx: ctx.trim()});
            }
            return results;
        }"""
        all_links: list[dict[str, str]] = await page.evaluate(js)
        return self._best_link_match(all_links, words, min_score=2)

    async def _open_category_panel_and_find(
        self, page: Any, words: list[str],
    ) -> str | None:
        """Open the full category panel and hover flyout layers to find links.

        Many sites (danawa, coupang, etc.) have a "전체 카테고리" button that
        opens a sidebar with flyout layers on hover.  The subcategory links
        inside these layers are only created dynamically after hovering the
        parent category.
        """
        # 1. Check if flyout triggers already exist (panel might be open)
        flyout_js = """() => {
            const links = document.querySelectorAll('a[href^="#category"], a[href^="#cateLayer"]');
            return Array.from(links).map(a => ({
                text: (a.textContent || '').trim().substring(0, 60),
                href: a.getAttribute('href') || '',
                selector: 'a[href=\"' + (a.getAttribute('href') || '') + '\"]',
                visible: a.getBoundingClientRect().width > 0,
            })).filter(r => r.text.length > 0 && r.visible);
        }"""
        flyout_triggers: list[dict[str, str]] = await page.evaluate(flyout_js)

        if not flyout_triggers:
            # Panel not open — try clicking "전체 카테고리" button
            cat_btn_js = """() => {
                const candidates = document.querySelectorAll(
                    'button, a, [role="button"], [class*="cate"]'
                );
                for (const el of candidates) {
                    const txt = (el.textContent || '').trim();
                    if ((txt.includes('전체') && txt.includes('카테고리'))
                        || el.className.toString().includes('btn_cate_all')) {
                        return {
                            found: true,
                            selector: el.id ? '#' + el.id
                                : el.className.toString().includes('btn_cate_all')
                                    ? 'button.btn_cate_all'
                                    : null,
                        };
                    }
                }
                return {found: false};
            }"""
            cat_btn = await page.evaluate(cat_btn_js)

            if not cat_btn.get("found") or not cat_btn.get("selector"):
                logger.debug("No category panel or flyout triggers found")
                return None

            logger.info(
                "Category panel: clicking %s to open full category menu",
                cat_btn["selector"],
            )
            try:
                await page.click(cat_btn["selector"], timeout=3000)
                await page.wait_for_timeout(800)
            except Exception as exc:
                logger.warning("Failed to click category button: %s", exc)
                return None

            # Re-check for flyout triggers after opening
            flyout_triggers = await page.evaluate(flyout_js)

        if not flyout_triggers:
            # Fallback: check if the sidebar itself has direct category links
            logger.debug("No flyout triggers found, checking sidebar links")
            result = await self._scan_all_links(page, words)
            return result

        # 3. Hover each relevant flyout trigger and check for matching links
        for trigger in flyout_triggers:
            trigger_text = trigger["text"].lower()
            # Extract sub-words from trigger text for matching
            trigger_words = re.findall(r"[\w가-힣]{2,}", trigger_text)
            # Bidirectional matching: check if any keyword contains a trigger
            # word or vice versa.
            # e.g. "스포츠 · 골프" → trigger_words = ["스포츠", "골프"]
            #      words = ["여성스포츠의류", "등산복"]
            #      "스포츠" in "여성스포츠의류" → True
            trigger_relevant = any(
                (w in trigger_text) or (tw in w)
                for w in words
                for tw in trigger_words
            ) if trigger_words else any(w in trigger_text for w in words)
            if not trigger_relevant:
                continue

            layer_id = trigger["href"].lstrip("#")
            logger.info(
                "Category panel: hovering '%s' (%s) to reveal flyout",
                trigger["text"], trigger["selector"],
            )
            try:
                await page.hover(trigger["selector"], timeout=3000)
                await page.wait_for_timeout(1000)
            except Exception as exc:
                logger.warning("Hover on flyout trigger failed: %s", exc)
                continue

            # 4. Extract ALL links from the dynamically-created layer
            #    (including hidden sub-items with real URLs)
            layer_js = """(layerId) => {
                const layer = document.getElementById(layerId);
                if (!layer) return [];
                const links = layer.querySelectorAll('a[href]');
                return Array.from(links).map(a => {
                    const href = a.getAttribute('href') || '';
                    if (!href || href === '#' || href.startsWith('javascript:'))
                        return null;
                    const text = (a.textContent || '').trim();
                    if (!text || text.length > 100) return null;
                    // Get parent category context
                    let ctx = '';
                    let el = a.parentElement;
                    for (let i = 0; i < 5 && el && el.id !== layerId; i++) {
                        const cls = (el.className || '').toString();
                        if (cls.includes('depth1') || cls.includes('cate_head')
                            || cls.includes('sub_head')) {
                            const header = el.querySelector('a, span, strong');
                            if (header && header !== a) {
                                ctx = (header.textContent || '').trim();
                            }
                            break;
                        }
                        el = el.parentElement;
                    }
                    return {text, href: a.href, ctx};
                }).filter(r => r !== null);
            }"""
            layer_links: list[dict[str, str]] = await page.evaluate(
                layer_js, layer_id,
            )
            logger.info(
                "Flyout layer '%s': found %d links", layer_id, len(layer_links),
            )

            if layer_links:
                result = self._best_link_match(layer_links, words, min_score=1)
                if result:
                    return result

        return None

    @staticmethod
    def _best_link_match(
        links: list[dict[str, str]],
        words: list[str],
        min_score: int = 1,
    ) -> str | None:
        """Score links by keyword overlap and return the best match URL.

        Prefers links whose href contains product-listing indicators
        (cate=, /list/, /category/) to avoid matching navigation-only anchors.
        """
        if not links:
            return None
        _product_url_patterns = ("cate=", "/list/", "/category/", "/product/")
        best_score = 0.0
        best_href: str | None = None
        for link in links:
            href = link.get("href", "")
            # Skip hash-only and javascript links
            if not href or href.endswith("#") or "javascript:" in href:
                continue
            combined = (link.get("text", "") + " " + link.get("ctx", "")).lower()
            score = float(sum(1 for w in words if w in combined))
            # Bonus for product-listing URLs
            if any(p in href for p in _product_url_patterns):
                score += 0.5
            if score > best_score:
                best_score = score
                best_href = href
        if best_score >= min_score and best_href:
            logger.info(
                "Dropdown link match: score=%.1f, url=%s (keywords: %s)",
                best_score, best_href[:80], words[:5],
            )
            return best_href
        return None

    async def _execute_visual_evaluate(
        self,
        step: StepDefinition,
        start_time: float,
    ) -> StepResult:
        """Execute a visual_evaluate step using the vision pipeline.

        Takes a full-page screenshot, uses YOLO to detect repeating items,
        creates a grid, then sends to VLM with the evaluation intent.
        The LLM planner decides when this step is needed — no hardcoding.

        The step's intent describes what to evaluate (e.g., "붉은색 옷 찾기").
        The step's arguments[0] is the evaluation criteria (e.g., "붉은색").
        """
        page = await self._executor.get_page()

        try:
            screenshot = await self._executor.screenshot()
            import io as _io

            from PIL import Image as _PILImage
            img = _PILImage.open(_io.BytesIO(screenshot))
            ss_size = img.size

            # Use YOLO to detect items on the page, or fall back to
            # extracting candidate bboxes from DOM elements.
            item_bboxes: list[tuple[int, int, int, int]] = []

            if self._yolo is not None:
                detections = await self._yolo.detect(screenshot)
                # Use all detections as item regions
                item_bboxes = [d.bbox for d in detections if d.bbox[2] > 30 and d.bbox[3] > 30]

            # Fallback: extract bboxes from similarly-sized DOM elements
            if not item_bboxes:
                candidates = await self._extractor.extract_clickables(page)
                visible = [c for c in candidates if c.visible and c.bbox[2] > 50 and c.bbox[3] > 50]
                if visible:
                    heights = [c.bbox[3] for c in visible]
                    if heights:
                        median_h = sorted(heights)[len(heights) // 2]
                        if median_h > 0:
                            similar = [
                                c for c in visible
                                if abs(c.bbox[3] - median_h) / median_h <= 0.3
                            ]
                            item_bboxes = [c.bbox for c in similar[:20]]

            if not item_bboxes:
                logger.warning("visual_evaluate: no items detected on page")
                elapsed = (time.perf_counter() - start_time) * 1000
                return StepResult(
                    step_id=step.step_id, success=False,
                    method="VE", latency_ms=elapsed,
                )

            # Filter out bboxes that don't overlap with the screenshot area
            sw, sh = ss_size
            valid_bboxes: list[tuple[int, int, int, int]] = []
            for bx, by, bw, bh in item_bboxes:
                # Check that the bbox overlaps at least partially with the image
                if bx + bw > 0 and by + bh > 0 and bx < sw and by < sh:
                    valid_bboxes.append((bx, by, bw, bh))
            item_bboxes = valid_bboxes

            if not item_bboxes:
                logger.warning("visual_evaluate: no valid bboxes after filtering")
                elapsed = (time.perf_counter() - start_time) * 1000
                return StepResult(
                    step_id=step.step_id, success=False,
                    method="VE", latency_ms=elapsed,
                )

            logger.info(
                "visual_evaluate: %d items detected, creating grid for: %s",
                len(item_bboxes), step.intent,
            )

            # Use batch vision pipeline if available
            if self._batch_vision is not None:
                result = await self._batch_vision.process_batch(
                    screenshot=screenshot,
                    item_bboxes=item_bboxes,
                    intent=step.intent,
                    screenshot_size=ss_size,
                    force_vlm=True,  # Visual evaluation needs VLM
                )

                relevant = [
                    it for it in result.items
                    if it.extra.get("relevant", False)
                ]
                if relevant:
                    best = max(relevant, key=lambda it: it.confidence)
                    bx, by, bw, bh = best.page_bbox
                    cx, cy = bx + bw // 2, by + bh // 2
                    logger.info(
                        "visual_evaluate: found match cell %d (conf=%.2f), "
                        "clicking (%d, %d)",
                        best.cell_index, best.confidence, cx, cy,
                    )
                    await page.mouse.click(cx, cy)
                    elapsed = (time.perf_counter() - start_time) * 1000
                    return StepResult(
                        step_id=step.step_id, success=True,
                        method="VE", latency_ms=elapsed,
                    )

                logger.warning("visual_evaluate: no relevant items found by VLM")
                elapsed = (time.perf_counter() - start_time) * 1000
                return StepResult(
                    step_id=step.step_id, success=False,
                    method="VE", latency_ms=elapsed,
                )

            # No batch vision pipeline — use VLM directly on full screenshot
            if self._vlm is not None:
                from src.vision.image_batcher import ImageBatcher
                batcher = ImageBatcher(max_batch_size=4)
                crops = batcher.crop_regions(screenshot, item_bboxes[:4])
                grid_img, _meta = batcher.create_grid_with_metadata(
                    crops, item_bboxes[:4],
                )
                vlm_results = await self._vlm.analyze_grid(
                    grid_img, step.intent, min(len(item_bboxes), 4),
                )
                relevant = [
                    vr for vr in vlm_results if vr.get("relevant", False)
                ]
                if relevant:
                    best_vr = max(relevant, key=lambda v: v.get("confidence", 0))
                    idx = best_vr["index"]
                    if 0 <= idx < len(item_bboxes):
                        bx, by, bw, bh = item_bboxes[idx]
                        cx, cy = bx + bw // 2, by + bh // 2
                        await page.mouse.click(cx, cy)
                        elapsed = (time.perf_counter() - start_time) * 1000
                        return StepResult(
                            step_id=step.step_id, success=True,
                            method="VE", latency_ms=elapsed,
                        )

            # Final fallback: use LLM with screenshot (multimodal) to
            # evaluate items when no dedicated vision pipeline is available.
            # We pass detected bboxes as numbered items so LLM can pick one.
            import base64 as _b64
            criteria = step.arguments[0] if step.arguments else step.intent
            bbox_desc = "\n".join(
                f"Item {i}: at ({bx},{by}) size {bw}x{bh}"
                for i, (bx, by, bw, bh) in enumerate(item_bboxes[:12])
            )
            eval_prompt = (
                f"Look at this screenshot of a product listing page.\n"
                f"Detected items:\n{bbox_desc}\n\n"
                f"Find the item that best matches: {criteria}\n"
                f"Return JSON: {{\"found\": true, \"item_index\": <number>,"
                f" \"description\": \"...\"}} "
                f"or {{\"found\": false}} if no match."
            )
            img_b64 = _b64.b64encode(screenshot).decode()
            try:
                resp, tokens = await self._planner._call_gemini(
                    eval_prompt, self._planner.tier1_model,
                    images=[{
                        "mime_type": "image/png",
                        "base64_data": img_b64,
                    }],
                )
                self._planner.usage.record(self._planner.tier1_model, tokens)
                if '"found": true' in resp.lower() or '"found":true' in resp.lower():
                    logger.info("visual_evaluate (LLM): match found — %s", resp[:200])
                    # Parse item_index from response and click it
                    import re as _re
                    idx_match = _re.search(r'"item_index"\s*:\s*(\d+)', resp)
                    if idx_match:
                        idx = int(idx_match.group(1))
                        if 0 <= idx < len(item_bboxes):
                            bx, by, bw, bh = item_bboxes[idx]
                            cx, cy = bx + bw // 2, by + bh // 2
                            logger.info(
                                "visual_evaluate (LLM): clicking item %d at (%d,%d)",
                                idx, cx, cy,
                            )
                            await page.mouse.click(cx, cy)
                    elapsed = (time.perf_counter() - start_time) * 1000
                    return StepResult(
                        step_id=step.step_id, success=True,
                        method="VE-LLM", latency_ms=elapsed,
                    )
            except Exception as llm_exc:
                logger.warning("visual_evaluate LLM fallback failed: %s", llm_exc)

            logger.warning("visual_evaluate: no matching items found")
            elapsed = (time.perf_counter() - start_time) * 1000
            return StepResult(
                step_id=step.step_id, success=False,
                method="VE", latency_ms=elapsed,
            )

        except Exception as exc:
            logger.warning("visual_evaluate failed: %s", exc)
            elapsed = (time.perf_counter() - start_time) * 1000
            return StepResult(
                step_id=step.step_id, success=False,
                method="VE", latency_ms=elapsed,
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
        if nt in (
            "goto", "click", "type", "press_key", "scroll", "wait",
            "visual_evaluate", "hover", "select_option",
        ):
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
        if any(
            kw in intent_lower
            for kw in ("hover", "마우스 올리", "마우스를 올", "호버")
        ):
            return "hover"
        if any(
            kw in intent_lower
            for kw in ("visual_evaluate", "시각 평가", "시각적 판단")
        ):
            return "visual_evaluate"
        return "click"


def _rank_candidates_by_intent(
    candidates: list[ExtractedElement],
    intent: str,
    limit: int = 50,
) -> list[ExtractedElement]:
    """Rank candidates by text relevance to the intent, then limit.

    Extracts keywords from the intent and scores each candidate by how
    many keywords appear in its text.  High-scoring candidates are placed
    first so that the LLM receives the most relevant elements.
    """
    import re as _re

    # Extract meaningful words (2+ chars) from the intent
    words = _re.findall(r"[\w가-힣]{2,}", intent.lower())

    def _score(el: ExtractedElement) -> int:
        txt = (el.text or "").lower()
        ctx = (el.parent_context or "").lower()
        combined = txt + " " + ctx
        return sum(1 for w in words if w in combined)

    # Separate: with text vs without text
    with_text = [c for c in candidates if c.text and c.text.strip()]
    no_text = [c for c in candidates if not c.text or not c.text.strip()]

    # Sort with-text candidates by relevance score descending
    with_text.sort(key=_score, reverse=True)

    # Take top relevant + fill remaining with non-relevant, then no-text
    result = with_text[:limit]
    remaining = limit - len(result)
    if remaining > 0:
        result.extend(no_text[:remaining])

    return result[:limit]
