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

    MAX_CAPTCHA_ATTEMPTS = 3

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

    async def run(self, intent: str) -> RunResult:
        """Execute a user intent end-to-end.

        1. Check for CAPTCHA, solve if present
        2. Get current page context
        3. LLM decomposes intent into steps
        4. Execute each step with cache-first strategy
        5. Screenshot after every step, check for CAPTCHA after each
        """
        page = await self._executor.get_page()
        page_state = await self._extractor.extract_state(page)

        # Check for CAPTCHA before starting
        if page_state.has_captcha:
            logger.warning("CAPTCHA detected before task start!")
            solved = await self._handle_captcha(page)
            if not solved:
                return RunResult(success=False)
            # Re-read page state after CAPTCHA
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
                await page.wait_for_timeout(2000)
                page_state = await self._extractor.extract_state(page)

            # Check for CAPTCHA after each step
            if page_state.has_captcha:
                logger.warning("CAPTCHA detected after step %d!", i + 1)
                solved = await self._handle_captcha(page)
                if not solved:
                    result.success = False
                    break
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
