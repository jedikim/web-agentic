"""v3 Orchestrator — main execution loop.

Two paths:
- Cached: execute directly → verify result → done (LLM 0 calls)
- Uncached: VLM screen check → obstacle removal → DOM extract →
  TextMatcher filter → Actor select → execute → verify → cache

Lazy replan: after each step, check if next step's target exists in DOM.
If not (e.g., hover revealed new menu), replan from fresh screenshot.

Chained fast hover followup: after hover steps, immediately extract DOM
and click the next navigation target without VLM. Chains up to 3 levels
of menu navigation (e.g., hover category → click subcategory → click item).
Only falls through to VLM if DOM can't find a match.

Retry: 2 consecutive failures → replan from current screen.
Max replan: 2 times per step group (failure-based).
Max progressive replan: 5 times (navigation/state-based).

Safety: total timeout (600s) and API call budget (60 calls) prevent runaway.
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

from src.core.browser import Browser
from src.core.cache import Cache
from src.core.types import Action, CacheEntry, ProgressEvent, ProgressInfo, StepPlan
from src.learning.site_knowledge import SiteKnowledgeStore, extract_domain

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
        screenshot_b64: Base64-encoded screenshot after step success.
        actor: Who executed: Cache, VLM Planner, LLM Actor, VisualJudge, Executor.
    """

    step_id: str = ""
    success: bool = False
    method: str = "v3"
    tokens_used: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    screenshot_b64: str = ""
    actor: str = ""


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
MAX_PROGRESSIVE_REPLAN = 5  # Re-plan after page/state changes
MAX_API_CALLS = 60
DEFAULT_TIMEOUT_S = 600.0
# Actions that don't change page structure — skip replan check.
# type/fill excluded: after input, page may need apply/submit action.
_PASSIVE_ACTIONS = frozenset({"wait"})
# Actions that need stabilization wait before DOM check
_INPUT_ACTIONS = frozenset({"type", "fill"})


class IPlanner(Protocol):
    """Planner interface for orchestrator."""

    async def check_screen(self, screenshot: bytes) -> object: ...
    async def plan(
        self, task: str, screenshot: bytes,
        site_knowledge: str = "",
    ) -> list[StepPlan]: ...


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
        visual_judge: Any | None = None,
        site_knowledge: SiteKnowledgeStore | None = None,
        progress_callback: Any | None = None,
        knowledge_llm: Any | None = None,
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
        self.visual_judge = visual_judge
        self.site_knowledge = site_knowledge
        self._progress_callback = progress_callback
        self._knowledge_llm = knowledge_llm

        # Runtime counters (reset per run)
        self._run_start: float = 0.0
        self._api_calls: int = 0
        self._total_tokens: int = 0
        self._total_cost: float = 0.0
        self._last_actor: str = ""

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

    def _emit(self, info: ProgressInfo) -> None:
        """Emit progress event if callback is set."""
        if self._progress_callback is not None:
            try:
                self._progress_callback.on_progress(info)
            except Exception:
                pass

    def _get_site_knowledge(self, url: str) -> str:
        """Load site knowledge MD for the current domain."""
        if not self.site_knowledge:
            return ""
        domain = extract_domain(url)
        return self.site_knowledge.load(domain)

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

            site_knowledge_str = self._get_site_knowledge(browser.url)
            logger.info("Planning task...")
            steps = await self.planner.plan(
                task, screenshot, site_knowledge=site_knowledge_str,
            )
            self._track_vlm_call()

            if not steps:
                logger.warning("Planner returned no steps for task: %s", task)
                return False

            logger.info(
                "Plan: %d steps — %s",
                len(steps),
                " → ".join(s.target_description for s in steps),
            )

            return await self._run_loop(task, steps, browser, site_knowledge_str)

        except _BudgetExceededError as exc:
            logger.error("Budget exceeded: %s", exc)
            return False

    def _completed_summary(self, completed: list[str]) -> str:
        """Build summary of completed steps for re-plan prompt."""
        if not completed:
            return ""
        return "완료: " + ", ".join(completed)

    @staticmethod
    def _dedup_steps(
        steps: list[StepPlan], completed: list[str],
    ) -> list[StepPlan]:
        """Remove steps whose description matches already-completed work."""
        if not completed:
            return steps
        lower_completed = {c.lower() for c in completed}
        result: list[StepPlan] = []
        for s in steps:
            desc_lower = s.target_description.lower()
            # Exact match or high keyword overlap → skip
            if desc_lower in lower_completed:
                continue
            # Check if any completed desc is a significant substring
            skip = False
            for c in lower_completed:
                # Both directions: completed ⊂ new or new ⊂ completed
                if len(c) >= 4 and (c in desc_lower or desc_lower in c):
                    skip = True
                    break
            if not skip:
                result.append(s)
        return result

    async def run_with_result(
        self,
        task: str,
        browser: Browser,
        attachments: list[dict[str, Any]] | None = None,
    ) -> V3RunResult:
        """Execute a task and return a rich result for API reporting.

        Same logic as run() but tracks step outcomes for the API layer.
        Supports progressive planning: re-plans after page navigation.

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
        self._last_actor = ""
        step_outcomes: list[V3StepOutcome] = []

        logger.info("▶ v3 run_with_result: %s", task)

        try:
            screenshot = await browser.screenshot()
            self._check_budget()

            site_knowledge_str = self._get_site_knowledge(browser.url)
            logger.info("Planning task...")
            steps = await self.planner.plan(
                task, screenshot, site_knowledge=site_knowledge_str,
            )
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

            self._emit(ProgressInfo(
                event=ProgressEvent.RUN_STARTED,
                total_steps=len(steps),
                message=f"Plan: {len(steps)} steps",
            ))

            replan_count = 0
            progressive_replan_count = 0
            consecutive_failures = 0
            completed_descs: list[str] = []
            completed_steps: list[StepPlan] = []
            failed_descs: list[str] = []
            failed_step_pairs: list[tuple[StepPlan, str]] = []
            task_done = False

            while not task_done:
                i = 0
                while i < len(steps):
                    self._check_budget()
                    step_start = time.monotonic()
                    pre_url = browser.url

                    logger.info(
                        "Step %d/%d: [%s] %s",
                        i + 1, len(steps),
                        steps[i].action_type,
                        steps[i].target_description,
                    )

                    self._emit(ProgressInfo(
                        event=ProgressEvent.STEP_STARTED,
                        step_id=steps[i].target_description,
                        step_index=i,
                        total_steps=len(steps),
                        message=f"[{steps[i].action_type}] {steps[i].target_description}",
                    ))

                    success = await self._execute_step(steps[i], browser)
                    step_ms = (time.monotonic() - step_start) * 1000

                    # Capture screenshot after successful step
                    step_screenshot_b64 = ""
                    if success:
                        try:
                            raw_ss = await browser.screenshot()
                            step_screenshot_b64 = base64.b64encode(
                                raw_ss,
                            ).decode("ascii")
                        except Exception:
                            pass

                    outcome = V3StepOutcome(
                        step_id=steps[i].target_description,
                        success=success,
                        method="cache" if success else "v3",
                        latency_ms=step_ms,
                        tokens_used=_VLM_TOKENS_EST,
                        cost_usd=_VLM_COST_EST if not success else 0.0,
                        screenshot_b64=step_screenshot_b64,
                        actor=self._last_actor,
                    )
                    step_outcomes.append(outcome)

                    self._emit(ProgressInfo(
                        event=(ProgressEvent.STEP_COMPLETED if success
                               else ProgressEvent.STEP_FAILED),
                        step_id=steps[i].target_description,
                        step_index=i,
                        total_steps=len(steps),
                        method=outcome.method,
                        message=f"{'OK' if success else 'FAIL'} ({step_ms:.0f}ms)",
                        screenshot_b64=step_screenshot_b64,
                        actor=self._last_actor,
                        cost_usd=outcome.cost_usd,
                        latency_ms=step_ms,
                        success=success,
                    ))

                    if success:
                        logger.info(
                            "  ✓ Step %d OK (%.0fms)", i + 1, step_ms,
                        )
                        completed_descs.append(steps[i].target_description)
                        completed_steps.append(steps[i])
                        consecutive_failures = 0

                        # Lazy replan: URL change OR next step not in DOM
                        should_replan = await self._should_replan(
                            steps, i, browser, pre_url,
                        )

                        if (
                            should_replan
                            and progressive_replan_count < MAX_PROGRESSIVE_REPLAN
                        ):
                            progressive_replan_count += 1
                            url_changed = browser.url != pre_url
                            reason = (
                                "page navigated" if url_changed
                                else "next step not in DOM"
                            )
                            logger.info(
                                "  Re-planning: %s (progressive %d/%d)...",
                                reason,
                                progressive_replan_count,
                                MAX_PROGRESSIVE_REPLAN,
                            )
                            self._check_budget()
                            screenshot = await browser.screenshot()
                            completed_str = self._completed_summary(
                                completed_descs,
                            )
                            steps = await self.planner.plan(
                                f"{task} ({completed_str})", screenshot,
                                site_knowledge=site_knowledge_str,
                            )
                            self._track_vlm_call()

                            if not steps:
                                logger.info(
                                    "Replan returned no steps — task done",
                                )
                                task_done = True
                                break
                            # Deduplicate against completed steps
                            steps = self._dedup_steps(
                                steps, completed_descs,
                            )
                            if not steps:
                                logger.info(
                                    "All replanned steps already completed",
                                )
                                task_done = True
                                break
                            logger.info(
                                "New plan: %d steps — %s",
                                len(steps),
                                " → ".join(
                                    s.target_description for s in steps
                                ),
                            )
                            break  # restart inner loop with new steps

                        i += 1
                        continue

                    consecutive_failures += 1
                    logger.warning(
                        "  ✗ Step %d FAIL (attempt %d, %.0fms)",
                        i + 1, consecutive_failures, step_ms,
                    )

                    if consecutive_failures >= 2:
                        failed_descs.append(
                            steps[i].target_description,
                        )
                        failed_step_pairs.append(
                            (steps[i], "consecutive failure"),
                        )
                        if replan_count < MAX_REPLAN:
                            replan_count += 1
                            logger.info(
                                "Replanning (%d/%d)...",
                                replan_count, MAX_REPLAN,
                            )
                            self._check_budget()
                            screenshot = await browser.screenshot()
                            remaining = " → ".join(
                                s.target_description for s in steps[i:]
                            )
                            completed_str = self._completed_summary(
                                completed_descs,
                            )
                            failed_hint = ""
                            if failed_descs:
                                failed_hint = (
                                    ", 실패한 접근(다른 방법 시도): "
                                    + ", ".join(
                                        dict.fromkeys(failed_descs),
                                    )
                                )
                            steps = await self.planner.plan(
                                f"{task} ({completed_str},"
                                f" 남은 작업: {remaining}"
                                f"{failed_hint})",
                                screenshot,
                                site_knowledge=site_knowledge_str,
                            )
                            self._track_vlm_call()

                            if not steps:
                                logger.warning("Replan returned no steps")
                                task_done = True
                                break
                            # Deduplicate against completed steps
                            steps = self._dedup_steps(
                                steps, completed_descs,
                            )
                            if not steps:
                                logger.info(
                                    "All replanned steps already completed",
                                )
                                task_done = True
                                break
                            logger.info(
                                "New plan: %d steps — %s",
                                len(steps),
                                " → ".join(
                                    s.target_description for s in steps
                                ),
                            )
                            consecutive_failures = 0
                            break  # restart inner loop

                        logger.error("Max replans exceeded, giving up")
                        task_done = True
                        break
                else:
                    # Inner loop completed all steps — check if done
                    if (
                        progressive_replan_count >= MAX_PROGRESSIVE_REPLAN
                        or not step_outcomes
                        or not step_outcomes[-1].success
                    ):
                        task_done = True
                        continue

                    # Fast path: after hover, iterate through task keywords
                    # to click navigation targets in the hover menu.
                    # Hover menus close during VLM delay, so act NOW.
                    last_action = steps[-1].action_type if steps else None
                    if last_action == "hover":
                        pre_hover_url = browser.url
                        navigated = False
                        anchor_node_id = 0
                        hover_keywords = self._extract_task_keywords(
                            task, completed_descs,
                        )
                        for kw in hover_keywords:
                            step_start = time.monotonic()
                            ok, desc, nid = (
                                await self._fast_hover_followup(
                                    task, completed_descs, browser,
                                    keyword=kw,
                                    after_node_id=anchor_node_id,
                                )
                            )
                            step_ms = (
                                time.monotonic() - step_start
                            ) * 1000
                            if not ok:
                                if nid > 0:
                                    anchor_node_id = nid
                                logger.info(
                                    "  Fast hover kw='%s' %s (%.0fms)",
                                    kw,
                                    f"failed: {desc}"
                                    if desc else "no match",
                                    step_ms,
                                )
                                continue  # try next keyword
                            logger.info(
                                "Fast hover followup OK: %s"
                                " (kw=%s, %.0fms)",
                                desc, kw, step_ms,
                            )
                            # Capture screenshot after hover followup
                            hover_ss_b64 = ""
                            try:
                                hover_ss = await browser.screenshot()
                                hover_ss_b64 = base64.b64encode(
                                    hover_ss,
                                ).decode("ascii")
                            except Exception:
                                pass
                            step_outcomes.append(V3StepOutcome(
                                step_id=desc,
                                success=True,
                                method="fast_dom",
                                latency_ms=step_ms,
                                cost_usd=0.0,
                                screenshot_b64=hover_ss_b64,
                                actor="Executor",
                            ))
                            completed_descs.append(desc)

                            if browser.url != pre_hover_url:
                                navigated = True
                                break
                            # URL same — submenu expanded or header
                            logger.info(
                                "  URL unchanged after '%s',"
                                " trying next keyword",
                                kw,
                            )

                        # Extra wait for slow navigation
                        if not navigated:
                            await browser.wait(2000)
                            if browser.url != pre_hover_url:
                                navigated = True
                                logger.info(
                                    "  Late navigation detected: %s",
                                    browser.url,
                                )

                        if navigated:
                            # Page navigated — plan for new page
                            progressive_replan_count += 1
                            self._check_budget()
                            screenshot = await browser.screenshot()
                            comp = self._completed_summary(
                                completed_descs,
                            )
                            steps = await self.planner.plan(
                                f"{task} ({comp})\n"
                                f"메뉴 탐색 완료. 현재 페이지에서"
                                f" 남은 작업만 출력하세요.\n"
                                f"가격, 색상 등 필터가 필요하면"
                                f" 필터부터 적용한 후 상품을 선택하세요.",
                                screenshot,
                                site_knowledge=site_knowledge_str,
                            )
                            self._track_vlm_call()
                            if steps:
                                logger.info(
                                    "New page plan: %d steps — %s",
                                    len(steps),
                                    " → ".join(
                                        s.target_description
                                        for s in steps
                                    ),
                                )
                                continue  # restart with new steps
                            task_done = True
                            continue
                        # No navigation — fall through to VLM post-check

                    self._check_budget()
                    screenshot = await browser.screenshot()
                    completed_str = self._completed_summary(completed_descs)
                    logger.info(
                        "All steps done. Checking if task needs more"
                        " work... (%s)", completed_str,
                    )
                    extra = await self.planner.plan(
                        f"{task}\n"
                        f"완료: {completed_str}\n"
                        f"현재 스크린샷을 보고 이 페이지에서 할 수 있는"
                        f" 다음 스텝만 출력하세요."
                        f" 이미 도착한 카테고리 메뉴를 다시 탐색하지 마세요.\n"
                        f"중요: 가격, 색상 등 필터 조건이 남아있으면"
                        f" 반드시 필터를 먼저 적용한 후에 상품을 선택하세요."
                        f" 필터 적용 전에 상품을 직접 클릭하지 마세요.\n"
                        f"시각적 속성(색상, 문양 등)으로 상품을 찾아야 하면"
                        f" visual_filter 스텝을 사용하세요."
                        f" 사이트 필터 UI 대신 visual_filter가 우선입니다.\n"
                        f"이미 완료된 스텝은 다시 실행하지 마세요."
                        f" 완료되었으면 빈 배열 [] 출력.",
                        screenshot,
                        site_knowledge=site_knowledge_str,
                    )
                    self._track_vlm_call()

                    if not extra:
                        logger.info("Task complete — no extra steps")
                        task_done = True
                    else:
                        # Deduplicate: skip steps matching already-completed
                        deduped = self._dedup_steps(extra, completed_descs)
                        if not deduped:
                            logger.info(
                                "All %d extra steps already completed",
                                len(extra),
                            )
                            task_done = True
                        else:
                            progressive_replan_count += 1
                            logger.info(
                                "Task not done — %d more steps: %s",
                                len(deduped),
                                " → ".join(
                                    s.target_description for s in deduped
                                ),
                            )
                            steps = deduped

        except _BudgetExceededError as exc:
            logger.error("Budget exceeded: %s", exc)

        all_ok = all(o.success for o in step_outcomes) and len(step_outcomes) > 0

        # Update site knowledge after run (success + failures)
        if self.site_knowledge and (completed_steps or failed_step_pairs):
            domain = extract_domain(browser.url)
            try:
                await self.site_knowledge.save_run(
                    domain=domain,
                    completed_steps=completed_steps,
                    failed_steps=failed_step_pairs,
                    task=task,
                    llm=self._knowledge_llm,
                )
            except Exception:
                logger.warning("Failed to save site knowledge", exc_info=True)

        total_ms = (time.monotonic() - self._run_start) * 1000

        # Capture final screenshot for API/UI reporting
        screenshots: list[str] = []
        try:
            final_png = await browser.screenshot()
            screenshots.append(base64.b64encode(final_png).decode())
        except Exception:
            logger.debug("Failed to capture final screenshot", exc_info=True)

        result = V3RunResult(
            success=all_ok,
            step_results=step_outcomes,
            screenshots=screenshots,
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

        self._emit(ProgressInfo(
            event=ProgressEvent.RUN_COMPLETED,
            total_steps=len(step_outcomes),
            message=result.result_summary or "",
            success=all_ok,
            cost_usd=self._total_cost,
        ))

        return result

    async def _run_loop(
        self, task: str, steps: list[StepPlan], browser: Browser,
        site_knowledge_str: str = "",
    ) -> bool:
        """Main execution loop with lazy replan support.

        Lazy replan: after a successful step, check if the NEXT step's
        target is findable in the current DOM. If not, replan from a fresh
        screenshot. This handles hover menus, dropdowns, and page navigation.
        """
        replan_count = 0
        progressive_replan_count = 0
        consecutive_failures = 0
        completed_descs: list[str] = []
        i = 0

        while i < len(steps):
            self._check_budget()
            pre_url = browser.url

            logger.info(
                "Step %d/%d: [%s] %s",
                i + 1, len(steps),
                steps[i].action_type,
                steps[i].target_description,
            )

            success = await self._execute_step(steps[i], browser)

            if success:
                logger.info("  ✓ Step %d OK", i + 1)
                completed_descs.append(steps[i].target_description)
                consecutive_failures = 0

                # Check if progressive replan is needed
                should_replan = await self._should_replan(
                    steps, i, browser, pre_url,
                )

                if (
                    should_replan
                    and progressive_replan_count < MAX_PROGRESSIVE_REPLAN
                ):
                    progressive_replan_count += 1
                    url_changed = browser.url != pre_url
                    reason = "page navigated" if url_changed else "next step not in DOM"
                    logger.info(
                        "  Re-planning: %s (progressive %d/%d)...",
                        reason,
                        progressive_replan_count, MAX_PROGRESSIVE_REPLAN,
                    )
                    self._check_budget()
                    screenshot = await browser.screenshot()
                    completed_str = self._completed_summary(completed_descs)
                    steps = await self.planner.plan(
                        f"{task} ({completed_str})", screenshot,
                        site_knowledge=site_knowledge_str,
                    )
                    self._track_vlm_call()

                    if not steps:
                        logger.info(
                            "Progressive replan returned no steps"
                            " — task may be complete",
                        )
                        return True
                    steps = self._dedup_steps(steps, completed_descs)
                    if not steps:
                        logger.info("All replanned steps already completed")
                        return True
                    logger.info(
                        "New plan: %d steps — %s",
                        len(steps),
                        " → ".join(s.target_description for s in steps),
                    )
                    i = 0
                    continue

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
                    completed_str = self._completed_summary(completed_descs)
                    steps = await self.planner.plan(
                        f"{task} ({completed_str}, 남은 작업: {remaining})",
                        screenshot,
                        site_knowledge=site_knowledge_str,
                    )
                    self._track_vlm_call()

                    if not steps:
                        return False
                    steps = self._dedup_steps(steps, completed_descs)
                    if not steps:
                        logger.info("All replanned steps already completed")
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

    def _extract_task_keywords(
        self,
        task: str,
        completed: list[str],
    ) -> dict[str, float]:
        """Extract keyword weights from task text, excluding completed parts.

        Simple tokenizer for Korean/English text — splits on common
        delimiters and filters out short/common tokens.
        Earlier keywords get higher weight (1.0→0.5) since users write
        navigation paths in order (e.g., '여성스포츠의류 > 등산복').
        URL/domain tokens (containing '.') are filtered out.
        """
        import re as _re
        # Remove common filler words
        skip = {"에", "가서", "에서", "중에서", "의", "를", "을", "이", "가",
                "하나만", "하나", "메뉴안에", "메뉴", "안에", "중", "찾아줘",
                "해줘", "클릭", "입력", "검색", "이하", "이하의"}
        # Remove completed descriptions from task
        remaining = task
        for desc in completed:
            remaining = remaining.replace(desc, "")
        # Split on delimiters
        tokens = _re.split(r"[\s,>→·/]+", remaining)
        # Strip trailing Korean particles (longest first)
        particles = ("중에서", "에서", "에게", "한테", "으로", "에", "의",
                     "을", "를", "이", "가", "도", "만")
        cleaned: list[str] = []
        for tok in tokens:
            tok = tok.strip()
            if len(tok) < 2 or tok in skip:
                continue
            # Skip URL/domain tokens (e.g., "danawa.com", "naver.com")
            if "." in tok or tok.startswith("http"):
                continue
            for p in particles:
                if tok.endswith(p) and len(tok) > len(p) + 1:
                    tok = tok[:-len(p)]
                    break
            if len(tok) >= 2 and tok not in skip:
                cleaned.append(tok)
        # Deduplicate, keeping first occurrence
        seen: set[str] = set()
        valid_tokens: list[str] = []
        for tok in cleaned:
            if tok not in seen:
                seen.add(tok)
                valid_tokens.append(tok)
        # Weight by position: first keyword = 1.0, decreasing to 0.4
        keywords: dict[str, float] = {}
        n = max(len(valid_tokens), 1)
        for i, tok in enumerate(valid_tokens):
            weight = 1.0 - (i / n) * 0.6  # 1.0 → 0.4
            keywords[tok] = round(weight, 2)
        return keywords

    async def _fast_hover_followup(
        self,
        task: str,
        completed: list[str],
        browser: Browser,
        keyword: str | None = None,
        after_node_id: int = 0,
    ) -> tuple[bool, str, int]:
        """Find and click an element from DOM immediately after hover.

        Bypasses screen check + actor LLM to minimize delay before
        ephemeral hover menus close.

        Returns:
            (success, description, node_id) — node_id of the matched
            element (used as anchor for position-based filtering).

        When keyword is given, searches DOM for that specific keyword.
        When after_node_id > 0, prefers candidates that appear after
        this node in DOM order (for category sub-section context).
        Falls back to Playwright text click if CSS selector fails.
        """
        if keyword:
            keywords = {keyword: 1.0}
        else:
            all_keywords = self._extract_task_keywords(task, completed)
            if not all_keywords:
                return False, "", 0
            first_kw = next(iter(all_keywords))
            keywords = {first_kw: 1.0}

        try:
            nodes = await self.extractor.extract(browser)
            candidates = self.filter.filter(nodes, keywords)

            if not candidates or candidates[0].score < FILTER_SCORE_THRESHOLD:
                return False, "", 0

            # When anchor node is given (from previous dead-link hover),
            # prefer candidates that appear after it in DOM order.
            # This selects e.g. 등산복 under 여성스포츠의류 (not 남성).
            best = candidates[0]
            if after_node_id > 0 and len(candidates) > 1:
                for c in candidates:
                    if (
                        c.score >= FILTER_SCORE_THRESHOLD
                        and c.node.node_id > after_node_id
                        and best.node.node_id <= after_node_id
                    ):
                        best = c
                        break
            node = best.node
            score = candidates[0].score
            desc = node.text or node.ax_name or node.tag
            href = node.attrs.get("href", "")

            # Non-navigating elements (category headers, JS links):
            # HOVER instead of click to highlight sub-section,
            # then let the next keyword find the correct child link.
            is_dead_link = (
                not href
                or href == "#"
                or href.startswith("javascript:")
            )
            logger.info(
                "  Fast hover followup: '%s' (kw=%s, score=%.2f,"
                " tag=%s, href=%s)",
                desc, keyword or "auto", score, node.tag,
                "dead" if is_dead_link else "real",
            )
            if is_dead_link:
                logger.info(
                    "  Hovering non-navigating element (href=%s)"
                    " to reveal sub-section",
                    href or "none",
                )
                try:
                    await self._click_by_text(
                        browser, node, desc, hover_only=True,
                    )
                    await browser.wait(300)
                except Exception:
                    pass
                return False, desc, node.node_id

            pre_url = browser.url
            pre_screenshot = await browser.screenshot()

            # Click strategy: Playwright role/text locator → CSS fallback
            clicked = await self._click_by_text(
                browser, node, desc,
            )

            if not clicked:
                logger.info("  Fast hover: no click method worked")
                return False, desc, node.node_id

            # Wait for navigation
            await browser.wait(1500)
            post_screenshot = await browser.screenshot()
            logger.info(
                "  Fast hover post-click: url=%s (was %s)",
                browser.url, pre_url,
            )

            step_plan = StepPlan(
                step_index=0,
                action_type="click",
                target_description=desc,
                keyword_weights=keywords,
            )
            verify_action = Action(
                selector=None,
                action_type="click",
                viewport_xy=None,
            )
            result = await self.verifier.verify_result(
                pre_screenshot, post_screenshot, verify_action,
                step_plan,
                browser, pre_url=pre_url,
            )

            if result == "ok":
                domain = self._get_domain(browser.url)
                await self.cache.store(CacheEntry(
                    domain=domain,
                    url_pattern=browser.url,
                    task_type=desc,
                    selector=None,
                    action_type="click",
                    keyword_weights=keywords,
                    viewport_xy=None,
                    success_count=1,
                    last_success=None,
                ))
                return True, desc, node.node_id

            return False, desc, node.node_id

        except Exception as exc:
            logger.debug("  Fast hover followup failed: %s", exc)
            return False, "", 0

    async def _click_by_text(
        self,
        browser: Browser,
        node: Any,
        text: str,
        hover_only: bool = False,
    ) -> bool:
        """Click (or hover) an element using Playwright locators.

        Tries in order: role link → a:has-text → generic text → selector.
        Returns True if any method succeeds.
        When hover_only=True, hovers instead of clicking.
        """
        text_target = (text or "").strip()
        if not text_target:
            return False

        # 1. Playwright role-based (best for <a> links)
        if node.tag == "a":
            try:
                locator = browser.page.get_by_role(
                    "link", name=text_target, exact=True,
                )
                if await locator.count() > 0:
                    if hover_only:
                        await locator.first.hover(timeout=2000)
                    else:
                        await locator.first.click(timeout=2000)
                    logger.info(
                        "  %s: link role OK (%d matches)",
                        "Hover" if hover_only else "Click",
                        await locator.count(),
                    )
                    return True
            except Exception:
                pass

            # 2. a:has-text fallback
            try:
                locator = browser.page.locator("a").filter(
                    has_text=text_target,
                )
                if await locator.count() > 0:
                    if hover_only:
                        await locator.first.hover(timeout=2000)
                    else:
                        await locator.first.click(timeout=2000)
                    logger.info(
                        "  %s: a-filter OK (%d matches)",
                        "Hover" if hover_only else "Click",
                        await locator.count(),
                    )
                    return True
            except Exception:
                pass

        # 3. Generic text
        try:
            locator = browser.page.get_by_text(
                text_target, exact=True,
            )
            if await locator.count() > 0:
                if hover_only:
                    await locator.first.hover(timeout=2000)
                else:
                    await locator.first.click(timeout=2000)
                logger.info(
                    "  %s: text OK (%d matches)",
                    "Hover" if hover_only else "Click",
                    await locator.count(),
                )
                return True
        except Exception:
            pass

        # 4. CSS selector + viewport coords
        selector = self._build_quick_selector(node)
        viewport_xy = await self._get_element_coords(
            browser, selector,
        )
        if viewport_xy and viewport_xy[0] > 0.01 and viewport_xy[1] > 0.01:
            action = Action(
                selector=selector,
                action_type="hover" if hover_only else "click",
                viewport_xy=viewport_xy,
            )
            try:
                await self.executor.execute_action(action, browser)
                logger.info(
                    "  %s: selector OK (sel=%s, xy=%s)",
                    "Hover" if hover_only else "Click",
                    selector, viewport_xy,
                )
                return True
            except Exception:
                pass

        if hover_only:
            return False

        # 5. JavaScript click — last resort for off-screen/hidden elements
        #    in hover panels where viewport coords are (0,0)
        if selector and selector != node.tag:
            try:
                safe = selector.replace("\\", "\\\\").replace("'", "\\'")
                clicked = await browser.evaluate(
                    f"(() => {{"
                    f"  const el = document.querySelector('{safe}');"
                    f"  if (!el) return false;"
                    f"  el.click();"
                    f"  return true;"
                    f"}})()",
                )
                if clicked:
                    logger.info(
                        "  Click: JS click OK (sel=%s)", selector,
                    )
                    return True
            except Exception:
                pass

        return False

    def _build_quick_selector(self, node: Any) -> str:
        """Build a CSS selector from a DOMNode's attributes."""
        attrs = node.attrs
        tag: str = str(node.tag)
        if "id" in attrs and attrs["id"]:
            return f"#{attrs['id']}"
        if "href" in attrs and attrs["href"]:
            href = attrs["href"].replace('"', '\\"')
            return f'{tag}[href="{href}"]'
        if "name" in attrs and attrs["name"]:
            return f'{tag}[name="{attrs["name"]}"]'
        if "aria-label" in attrs and attrs["aria-label"]:
            label = attrs["aria-label"][:40].replace('"', '\\"')
            return f'{tag}[aria-label="{label}"]'
        return tag

    async def _get_element_coords(
        self, browser: Browser, selector: str | None,
    ) -> tuple[float, float] | None:
        """Get viewport-relative center coordinates for an element."""
        if not selector:
            return None
        try:
            safe = selector.replace("\\", "\\\\").replace("'", "\\'")
            result = await browser.evaluate(f"""(() => {{
                const el = document.querySelector('{safe}');
                if (!el) return null;
                const r = el.getBoundingClientRect();
                const vw = window.innerWidth;
                const vh = window.innerHeight;
                return {{
                    cx: (r.left + r.right) / 2 / vw,
                    cy: (r.top + r.bottom) / 2 / vh,
                }};
            }})()""")
            if result:
                return (result["cx"], result["cy"])
        except Exception:
            pass
        return None

    async def _should_replan(
        self,
        steps: list[StepPlan],
        current_idx: int,
        browser: Browser,
        pre_url: str,
    ) -> bool:
        """Decide whether to replan after a successful step.

        Triggers replan when:
        1. URL changed (page navigation) — always replan.
        2. Next step's target not findable in DOM — lazy replan.
        Skips replan for passive actions (type/fill/wait) and last steps.
        """
        remaining = len(steps) - current_idx - 1
        if remaining <= 0:
            return False

        # Always replan after URL change
        if browser.url != pre_url:
            return True

        # Skip check for passive actions that don't change page structure
        current_action = steps[current_idx].action_type
        if current_action in _PASSIVE_ACTIONS:
            return False

        # After input actions, wait for page to react before DOM check
        if current_action in _INPUT_ACTIONS:
            await browser.wait(2000)

        # Lazy check: can the next step find its target in current DOM?
        next_step = steps[current_idx + 1]
        if not next_step.keyword_weights:
            return False

        try:
            nodes = await self.extractor.extract(browser)
            candidates = self.filter.filter(nodes, next_step.keyword_weights)
            top_score = candidates[0].score if candidates else 0.0

            if top_score < FILTER_SCORE_THRESHOLD:
                logger.info(
                    "  Next step '%s' not findable (top=%.2f < %.2f)",
                    next_step.target_description, top_score,
                    FILTER_SCORE_THRESHOLD,
                )
                return True

            logger.debug(
                "  Next step '%s' findable (top=%.2f), continuing",
                next_step.target_description, top_score,
            )
        except Exception as exc:
            logger.debug("  DOM check failed: %s, triggering replan", exc)
            return True

        return False

    async def _execute_visual_filter(
        self, step: StepPlan, browser: Browser,
    ) -> bool:
        """Execute a visual_filter step using VisualJudge.

        Flow:
          1. RF-DETR detects cards → crop → grid → VLM judges (preferred)
          2. RF-DETR fails → VLM fullscreen (fallback)
          3. Click matched item by bbox (grid) or planner xy (fullscreen)
        """
        if not self.visual_judge:
            logger.warning("No VisualJudge configured, skipping visual_filter")
            return False

        screenshot = await browser.screenshot()
        items = await self.visual_judge.judge(
            screenshot=screenshot,
            query=step.visual_filter_query or step.value or "",
            complexity=step.visual_complexity or "simple",
        )

        matched = [i for i in items if i.relevant]
        if not matched:
            logger.warning("VisualJudge: no matching items found")
            return False

        best = max(matched, key=lambda i: i.confidence)
        x, y, w, h = best.page_bbox

        # Check if this is a fullscreen result (bbox covers entire page)
        size = await browser.get_viewport_size()
        is_fullscreen = (
            x == 0 and y == 0
            and w >= size["width"] * 0.9
            and h >= size["height"] * 0.9
        )

        if is_fullscreen:
            # Fullscreen VLM fallback — use planner's target coordinates
            if step.target_viewport_xy:
                cx = int(step.target_viewport_xy[0] * size["width"])
                cy = int(step.target_viewport_xy[1] * size["height"])
                logger.info(
                    "VisualJudge[fullscreen]: VLM confirmed match, "
                    "clicking planner xy (%d, %d) — %s (%.2f)",
                    cx, cy, best.label, best.confidence,
                )
            else:
                # No planner coords — fall through to normal pipeline
                logger.info(
                    "VisualJudge[fullscreen]: VLM confirmed match but "
                    "no target coords, delegating to normal pipeline",
                )
                return await self._full_pipeline(step, browser, self._get_domain(browser.url))
        else:
            # Grid result — click center of detected card bbox
            cx = x + w // 2
            cy = y + h // 2
            logger.info(
                "VisualJudge[grid]: clicked item %d at (%d, %d) — %s (%.2f)",
                best.cell_index, cx, cy, best.label, best.confidence,
            )

        page = browser._page
        await page.mouse.click(cx, cy)
        return True

    async def _execute_step(self, step: StepPlan, browser: Browser) -> bool:
        """Execute a single step with cache check and full pipeline fallback."""
        self._last_actor = ""

        if step.action_type == "visual_filter":
            self._last_actor = "VisualJudge"
            return await self._execute_visual_filter(step, browser)

        domain = self._get_domain(browser.url)
        pre_screenshot = await browser.screenshot()

        # === Cached path: try directly ===
        cached = await self.cache.lookup(domain, browser.url, step.target_description)
        if cached:
            logger.info("  Cache hit: %s", cached.selector or "viewport")
            self._last_actor = "Cache"
            result = await self._try_cached(cached, browser, pre_screenshot)
            if result == "ok":
                logger.info("  Cache execution OK")
                return True
            logger.info("  Cache execution %s, falling through to pipeline", result)

        # === Uncached path: full pipeline ===
        self._last_actor = "LLM Actor"
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
            self._last_actor = "LLM Actor"
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
            self._last_actor = "VLM Planner"
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

