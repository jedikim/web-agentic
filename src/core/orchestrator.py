"""Orchestrator — main execution loop tying X, E, R, V, F, L modules together.

Implements the escalation flow:

    R(rule matching) -> success -> X(execute) -> V(verify) -> success -> next step
                  | fail
        E(extract candidates) -> R(heuristic select) -> success -> X -> V
                                                  | fail
                                             F(classify) -> recovery plan
                                               |- retry -> loop
                                               |- escalate_llm -> L(plan/select) -> X -> V
                                               |- escalate_vision -> (placeholder)
                                               |- human_handoff -> emit event
                                               +- skip -> next step

Design principles:
  - Token Zero First: always try R(rule) first, only escalate on failure.
  - Verify-After-Act: always call V after X.
  - All modules injected via Protocol-based DI.
  - Optional modules (F, L, Memory) are None-safe — skip that escalation level.

See docs/ARCHITECTURE.md for the full module dependency diagram.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from src.core.types import (
    AutomationError,
    ClickOptions,
    ExtractedElement,
    FailureCode,
    IExecutor,
    IExtractor,
    IFallbackRouter,
    ILLMPlanner,
    IMemoryManager,
    IRuleEngine,
    IVerifier,
    PageState,
    RecoveryPlan,
    RuleMatch,
    SelectorNotFoundError,
    StepContext,
    StepDefinition,
    StepResult,
    VerifyResult,
)
from src.workflow.step_queue import StepQueue

logger = logging.getLogger(__name__)


class Orchestrator:
    """Main orchestration loop tying all core modules together.

    Consumes a list of ``StepDefinition`` objects and executes them
    through the escalation pipeline: R -> E+R -> F -> L, with V(verify)
    after every action.

    Args:
        executor: Browser automation module (X).
        extractor: DOM extraction module (E).
        rule_engine: Rule matching module (R).
        verifier: Post-action verification module (V).
        fallback_router: Failure classification and routing module (F). Optional.
        planner: LLM-based planning module (L). Optional.
        memory: 4-layer memory manager. Optional.

    Example::

        orchestrator = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine,
            verifier=verifier,
        )
        results = await orchestrator.run(steps)
    """

    def __init__(
        self,
        executor: IExecutor,
        extractor: IExtractor,
        rule_engine: IRuleEngine,
        verifier: IVerifier,
        fallback_router: IFallbackRouter | None = None,
        planner: ILLMPlanner | None = None,
        memory: IMemoryManager | None = None,
    ) -> None:
        self._executor = executor
        self._extractor = extractor
        self._rule_engine = rule_engine
        self._verifier = verifier
        self._fallback_router = fallback_router
        self._planner = planner
        self._memory = memory

    async def run(self, steps: list[StepDefinition]) -> list[StepResult]:
        """Execute a list of steps through the orchestration pipeline.

        Populates a ``StepQueue``, processes each step via ``execute_step``,
        and collects results.  Completed and failed steps are tracked in the
        queue for observability.

        Args:
            steps: Ordered list of step definitions to execute.

        Returns:
            List of ``StepResult`` objects, one per input step, in order.
        """
        queue = StepQueue()
        queue.push_many(steps)
        results: list[StepResult] = []

        while not queue.is_empty():
            step = queue.pop()
            if step is None:
                break  # pragma: no cover — defensive

            logger.info("Executing step '%s': %s", step.step_id, step.intent)
            result = await self.execute_step(step)
            results.append(result)

            if result.success:
                queue.mark_completed(step)
            else:
                queue.mark_failed(step)

        return results

    async def execute_step(self, step: StepDefinition) -> StepResult:
        """Execute a single step through the full escalation pipeline.

        Attempts resolution in order:
        1. R(rule match) -> X(execute) -> V(verify)
        2. E(extract) -> R(heuristic select) -> X -> V
        3. F(classify) -> recovery plan (retry / escalate_llm / skip / etc.)
        4. L(LLM select) -> X -> V

        Respects ``step.max_attempts`` for the overall retry budget.

        Args:
            step: The step definition to execute.

        Returns:
            ``StepResult`` with success flag, method used, timing, and cost info.
        """
        start_time = time.perf_counter()
        total_tokens = 0
        total_cost = 0.0
        last_failure_code: FailureCode | None = None

        page = await self._executor.get_page()
        page_state = await self._extractor.extract_state(page)

        for attempt in range(1, step.max_attempts + 1):
            context = StepContext(
                step=step,
                page_state=page_state,
                attempt=attempt,
            )
            logger.debug(
                "Step '%s' attempt %d/%d", step.step_id, attempt, step.max_attempts
            )

            # ── Level 0: R(rule match) ────────────────────────
            try:
                rule_match = self._try_rule_match(step, page_state)
                if rule_match is not None:
                    await self._execute_action(rule_match.selector, rule_match.method, step)
                    verify_result = await self._verify_step(step, page)
                    if verify_result.success:
                        elapsed_ms = (time.perf_counter() - start_time) * 1000
                        return StepResult(
                            step_id=step.step_id,
                            success=True,
                            method="R",
                            tokens_used=total_tokens,
                            latency_ms=elapsed_ms,
                            cost_usd=total_cost,
                        )
                    # Verify failed — fall through to heuristic
                    logger.debug(
                        "Step '%s': R matched but V failed: %s",
                        step.step_id,
                        verify_result.message,
                    )
            except AutomationError as exc:
                logger.debug(
                    "Step '%s': R path error: %s", step.step_id, exc
                )
                last_failure_code = getattr(exc, "failure_code", None)
                context.previous_error = exc

            # ── Level 1: E(extract) + R(heuristic) ────────────
            try:
                selected_eid = await self._try_heuristic(step, page)
                if selected_eid is not None:
                    await self._execute_action(selected_eid, "click", step)
                    verify_result = await self._verify_step(step, page)
                    if verify_result.success:
                        elapsed_ms = (time.perf_counter() - start_time) * 1000
                        return StepResult(
                            step_id=step.step_id,
                            success=True,
                            method="L1",
                            tokens_used=total_tokens,
                            latency_ms=elapsed_ms,
                            cost_usd=total_cost,
                        )
                    logger.debug(
                        "Step '%s': heuristic matched but V failed: %s",
                        step.step_id,
                        verify_result.message,
                    )
                else:
                    # No heuristic match — synthesize an error for F classification
                    if context.previous_error is None:
                        context.previous_error = SelectorNotFoundError(
                            f"No rule match or heuristic candidate for intent: {step.intent}"
                        )
                        last_failure_code = FailureCode.SELECTOR_NOT_FOUND
            except AutomationError as exc:
                logger.debug(
                    "Step '%s': heuristic path error: %s", step.step_id, exc
                )
                last_failure_code = getattr(exc, "failure_code", None)
                context.previous_error = exc

            # ── Level 2: F(classify) + recovery ───────────────
            recovery = self._try_recovery(context)
            if recovery is not None:
                if recovery.strategy == "skip":
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    return StepResult(
                        step_id=step.step_id,
                        success=False,
                        method="F",
                        tokens_used=total_tokens,
                        latency_ms=elapsed_ms,
                        cost_usd=total_cost,
                        failure_code=last_failure_code,
                    )

                if recovery.strategy == "human_handoff":
                    logger.warning(
                        "Step '%s': human handoff requested", step.step_id
                    )
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    return StepResult(
                        step_id=step.step_id,
                        success=False,
                        method="H",
                        tokens_used=total_tokens,
                        latency_ms=elapsed_ms,
                        cost_usd=total_cost,
                        failure_code=last_failure_code,
                    )

                if recovery.strategy == "escalate_llm":
                    try:
                        llm_result = await self._try_llm(step, page)
                        if llm_result is not None:
                            success, tokens, cost = llm_result
                            total_tokens += tokens
                            total_cost += cost
                            if success:
                                elapsed_ms = (time.perf_counter() - start_time) * 1000
                                return StepResult(
                                    step_id=step.step_id,
                                    success=True,
                                    method="L2",
                                    tokens_used=total_tokens,
                                    latency_ms=elapsed_ms,
                                    cost_usd=total_cost,
                                )
                    except AutomationError as exc:
                        logger.debug(
                            "Step '%s': LLM path error: %s", step.step_id, exc
                        )
                        last_failure_code = getattr(exc, "failure_code", None)

                if recovery.strategy == "escalate_vision":
                    # Placeholder for Phase 3 vision module
                    logger.debug(
                        "Step '%s': vision escalation not yet implemented",
                        step.step_id,
                    )

                if recovery.strategy == "retry":
                    # Just continue to the next attempt
                    logger.debug(
                        "Step '%s': retry strategy, continuing to next attempt",
                        step.step_id,
                    )
                    # Refresh page state for next attempt
                    page_state = await self._extractor.extract_state(page)
                    continue

            # Refresh page state for next attempt
            page_state = await self._extractor.extract_state(page)

        # All attempts exhausted
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning(
            "Step '%s': all %d attempts exhausted",
            step.step_id,
            step.max_attempts,
        )
        return StepResult(
            step_id=step.step_id,
            success=False,
            method="R",
            tokens_used=total_tokens,
            latency_ms=elapsed_ms,
            cost_usd=total_cost,
            failure_code=last_failure_code,
        )

    # ── Internal escalation methods ──────────────────────────

    def _try_rule_match(
        self, step: StepDefinition, page_state: PageState
    ) -> RuleMatch | None:
        """Attempt deterministic rule matching (Level 0).

        Args:
            step: Current step definition.
            page_state: Current page state for context.

        Returns:
            A ``RuleMatch`` if a rule fires, otherwise ``None``.
        """
        rule_match = self._rule_engine.match(step.intent, page_state)
        if rule_match is not None:
            logger.debug(
                "Step '%s': R matched rule '%s' -> %s",
                step.step_id,
                rule_match.rule_id,
                rule_match.selector,
            )
        return rule_match

    async def _try_heuristic(
        self, step: StepDefinition, page: Any
    ) -> str | None:
        """Attempt heuristic element selection (Level 1).

        Extracts candidates from the DOM, then uses R's heuristic scorer
        to pick the best match.

        Args:
            step: Current step definition.
            page: Playwright Page instance.

        Returns:
            The ``eid`` (CSS selector) of the best candidate, or ``None``.
        """
        clickables = await self._extractor.extract_clickables(page)
        inputs = await self._extractor.extract_inputs(page)
        candidates: list[ExtractedElement] = clickables + inputs

        if not candidates:
            logger.debug("Step '%s': no candidates extracted", step.step_id)
            return None

        selected = self._rule_engine.heuristic_select(candidates, step.intent)
        if selected is not None:
            logger.debug(
                "Step '%s': heuristic selected '%s'", step.step_id, selected
            )
        return selected

    async def _try_llm(
        self, step: StepDefinition, page: Any
    ) -> tuple[bool, int, float] | None:
        """Attempt LLM-based element selection (Level 2).

        Uses the LLM planner to select the best element from extracted
        candidates, then executes and verifies.

        Args:
            step: Current step definition.
            page: Playwright Page instance.

        Returns:
            Tuple of (success, tokens_used, cost_usd), or ``None`` if
            the planner is not available.
        """
        if self._planner is None:
            logger.debug(
                "Step '%s': LLM planner not available, skipping L2",
                step.step_id,
            )
            return None

        clickables = await self._extractor.extract_clickables(page)
        inputs = await self._extractor.extract_inputs(page)
        candidates = clickables + inputs

        if not candidates:
            return None

        patch = await self._planner.select(candidates, step.intent)

        # Use the patch data to execute
        selector = patch.data.get("selector", patch.target)
        method = patch.data.get("method", "click")

        # Estimate token cost (planner implementations should provide real numbers)
        tokens = patch.data.get("tokens_used", 100)
        cost = patch.data.get("cost_usd", 0.001)

        await self._execute_action(selector, method, step)
        verify_result = await self._verify_step(step, page)

        return (verify_result.success, tokens, cost)

    def _try_recovery(self, context: StepContext) -> RecoveryPlan | None:
        """Classify failure and produce a recovery plan (Level F).

        Args:
            context: Current step context with error information.

        Returns:
            A ``RecoveryPlan``, or ``None`` if the fallback router is unavailable.
        """
        if self._fallback_router is None:
            logger.debug(
                "Step '%s': fallback router not available, skipping F",
                context.step.step_id,
            )
            return None

        error = context.previous_error
        if error is None:
            # No error to classify — default to retry
            return RecoveryPlan(strategy="retry", tier=1)

        failure_code = self._fallback_router.classify(error, context)
        recovery = self._fallback_router.route(failure_code)
        logger.debug(
            "Step '%s': F classified as %s -> strategy=%s",
            context.step.step_id,
            failure_code,
            recovery.strategy,
        )
        return recovery

    # ── Execution helpers ────────────────────────────────────

    async def _execute_action(
        self, selector: str, method: str, step: StepDefinition
    ) -> None:
        """Execute a browser action using the Executor.

        Dispatches to the appropriate executor method based on the
        ``method`` string (click, type, scroll, wait, goto).

        Args:
            selector: CSS selector or URL target.
            method: Action method name.
            step: Current step definition (for arguments and timeout).

        Raises:
            AutomationError: If the action fails.
        """
        match method:
            case "click":
                await self._executor.click(
                    selector,
                    ClickOptions(timeout_ms=step.timeout_ms),
                )
            case "type":
                text = step.arguments[0] if step.arguments else ""
                await self._executor.type_text(selector, text)
            case "goto":
                url = step.arguments[0] if step.arguments else selector
                await self._executor.goto(url)
            case "scroll":
                direction = step.arguments[0] if step.arguments else "down"
                amount = int(step.arguments[1]) if len(step.arguments) > 1 else 300
                await self._executor.scroll(direction, amount)
            case "wait":
                from src.core.types import WaitCondition
                wait_type = step.arguments[0] if step.arguments else "timeout"
                wait_value = step.arguments[1] if len(step.arguments) > 1 else ""
                condition = WaitCondition(
                    type=wait_type,
                    value=wait_value,
                    timeout_ms=step.timeout_ms,
                )
                await self._executor.wait_for(condition)
            case _:
                # Default to click
                await self._executor.click(
                    selector,
                    ClickOptions(timeout_ms=step.timeout_ms),
                )

    async def _verify_step(
        self, step: StepDefinition, page: Any
    ) -> VerifyResult:
        """Run post-action verification if a verify condition is defined.

        If no verify condition is set on the step, returns success by default.

        Args:
            step: Current step definition (may have verify_condition).
            page: Playwright Page instance.

        Returns:
            ``VerifyResult`` — success if no condition or condition passes.
        """
        if step.verify_condition is None:
            return VerifyResult(success=True, message="No verify condition set")

        return await self._verifier.verify(step.verify_condition, page)
