"""Unit tests for Orchestrator — main execution loop.

All Protocol modules (X, E, R, V, F, L) are mocked with AsyncMock/MagicMock.
Tests verify:
  - Rule match success path (R -> X -> V)
  - Heuristic fallback path (E + R -> X -> V)
  - Verify failure triggers retry
  - max_attempts limit
  - Skip recovery when fallback_router is None
  - Full step list execution via run()
  - Cost/token tracking
  - LLM escalation path
  - Human handoff and skip strategies
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.orchestrator import Orchestrator
from src.core.types import (
    AutomationError,
    ClickOptions,
    ExtractedElement,
    FailureCode,
    PageState,
    PatchData,
    ProgressEvent,
    ProgressInfo,
    RecoveryPlan,
    RuleMatch,
    SelectorNotFoundError,
    StepContext,
    StepDefinition,
    StepResult,
    VerifyCondition,
    VerifyResult,
)


# ── Fixtures ──────────────────────────────────────────


def _make_page_state(**kwargs) -> PageState:
    """Create a minimal PageState for testing."""
    defaults = {
        "url": "https://example.com",
        "title": "Test Page",
    }
    defaults.update(kwargs)
    return PageState(**defaults)


def _make_step(
    step_id: str = "step_1",
    intent: str = "click the button",
    max_attempts: int = 3,
    verify_condition: VerifyCondition | None = None,
    arguments: list[str] | None = None,
) -> StepDefinition:
    """Create a minimal StepDefinition for testing."""
    return StepDefinition(
        step_id=step_id,
        intent=intent,
        max_attempts=max_attempts,
        verify_condition=verify_condition,
        arguments=arguments or [],
    )


@pytest.fixture
def mock_executor() -> AsyncMock:
    """Mock IExecutor with all needed async methods."""
    executor = AsyncMock()
    mock_page = AsyncMock()
    executor.get_page = AsyncMock(return_value=mock_page)
    executor.click = AsyncMock()
    executor.type_text = AsyncMock()
    executor.goto = AsyncMock()
    executor.scroll = AsyncMock()
    executor.wait_for = AsyncMock()
    return executor


@pytest.fixture
def mock_extractor() -> AsyncMock:
    """Mock IExtractor."""
    extractor = AsyncMock()
    extractor.extract_state = AsyncMock(return_value=_make_page_state())
    extractor.extract_clickables = AsyncMock(return_value=[])
    extractor.extract_inputs = AsyncMock(return_value=[])
    return extractor


@pytest.fixture
def mock_rule_engine() -> MagicMock:
    """Mock IRuleEngine."""
    engine = MagicMock()
    engine.match = MagicMock(return_value=None)
    engine.heuristic_select = MagicMock(return_value=None)
    return engine


@pytest.fixture
def mock_verifier() -> AsyncMock:
    """Mock IVerifier."""
    verifier = AsyncMock()
    verifier.verify = AsyncMock(return_value=VerifyResult(success=True, message="OK"))
    return verifier


@pytest.fixture
def mock_fallback_router() -> MagicMock:
    """Mock IFallbackRouter."""
    router = MagicMock()
    router.classify = MagicMock(return_value=FailureCode.SELECTOR_NOT_FOUND)
    router.route = MagicMock(
        return_value=RecoveryPlan(strategy="retry", tier=1)
    )
    return router


@pytest.fixture
def mock_planner() -> AsyncMock:
    """Mock ILLMPlanner."""
    planner = AsyncMock()
    planner.select = AsyncMock(
        return_value=PatchData(
            patch_type="selector_fix",
            target="#btn-alt",
            data={"selector": "#btn-alt", "method": "click", "tokens_used": 150, "cost_usd": 0.002},
            confidence=0.85,
        )
    )
    return planner


@pytest.fixture
def orchestrator(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
) -> Orchestrator:
    """Create an Orchestrator with required modules only (no optional ones)."""
    return Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
    )


@pytest.fixture
def orchestrator_full(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
    mock_fallback_router: MagicMock,
    mock_planner: AsyncMock,
) -> Orchestrator:
    """Create an Orchestrator with all modules including optional ones."""
    return Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
        fallback_router=mock_fallback_router,
        planner=mock_planner,
    )


# ── 1. Rule match success path ───────────────────────


async def test_rule_match_success(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
    mock_verifier: AsyncMock,
) -> None:
    """R(rule match) -> X(click) -> V(verify success) -> StepResult.success=True."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="popup_close",
        selector="#close-btn",
        method="click",
        confidence=1.0,
    )
    mock_verifier.verify.return_value = VerifyResult(success=True, message="OK")

    step = _make_step(verify_condition=VerifyCondition(type="element_gone", value="#popup"))
    result = await orchestrator.execute_step(step)

    assert result.success is True
    assert result.method == "R"
    assert result.step_id == "step_1"
    mock_executor.click.assert_awaited_once()


async def test_rule_match_no_verify_condition(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
) -> None:
    """When no verify_condition is set, step succeeds after X(execute)."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="nav_home",
        selector="a.home",
        method="click",
        confidence=1.0,
    )

    step = _make_step()  # no verify_condition
    result = await orchestrator.execute_step(step)

    assert result.success is True
    assert result.method == "R"


# ── 2. Heuristic fallback path ───────────────────────


async def test_heuristic_fallback_success(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_extractor: AsyncMock,
    mock_executor: AsyncMock,
    mock_verifier: AsyncMock,
) -> None:
    """R(miss) -> E(extract) + R(heuristic) -> X -> V -> success with method=L1."""
    # R returns no match
    mock_rule_engine.match.return_value = None

    # E returns candidates
    candidate = ExtractedElement(
        eid="#submit-btn", type="button", text="Submit", visible=True
    )
    mock_extractor.extract_clickables.return_value = [candidate]

    # R heuristic selects the candidate
    mock_rule_engine.heuristic_select.return_value = "#submit-btn"

    # V passes
    mock_verifier.verify.return_value = VerifyResult(success=True, message="OK")

    step = _make_step(
        verify_condition=VerifyCondition(type="element_visible", value="#result")
    )
    result = await orchestrator.execute_step(step)

    assert result.success is True
    assert result.method == "L1"
    mock_executor.click.assert_awaited()


async def test_heuristic_no_candidates(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_extractor: AsyncMock,
) -> None:
    """When E returns no candidates and R has no match, all attempts fail."""
    mock_rule_engine.match.return_value = None
    mock_extractor.extract_clickables.return_value = []
    mock_extractor.extract_inputs.return_value = []
    mock_rule_engine.heuristic_select.return_value = None

    step = _make_step(max_attempts=1)
    result = await orchestrator.execute_step(step)

    assert result.success is False


# ── 3. Verify failure triggers retry ─────────────────


async def test_verify_failure_triggers_retry(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
    mock_verifier: AsyncMock,
) -> None:
    """When V fails, orchestrator retries up to max_attempts."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )

    # First attempt: verify fails. Second attempt: verify succeeds.
    mock_verifier.verify.side_effect = [
        VerifyResult(success=False, message="Element still visible"),
        VerifyResult(success=False, message="Element still visible"),
        VerifyResult(success=True, message="OK"),
        VerifyResult(success=True, message="OK"),
    ]

    step = _make_step(
        max_attempts=2,
        verify_condition=VerifyCondition(type="element_gone", value="#popup"),
    )
    result = await orchestrator.execute_step(step)

    # Second attempt's heuristic path should succeed
    # The rule match verify fails, then heuristic path is tried
    # Since rule_engine.heuristic_select returns None by default and
    # extractor returns empty, only the rule match path is tried each attempt.
    # With verify failing on R path both times, all attempts exhausted.
    # Let's verify the click was called at least twice (once per attempt)
    assert mock_executor.click.await_count >= 2


async def test_verify_failure_then_success_on_retry(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
    mock_verifier: AsyncMock,
    mock_extractor: AsyncMock,
) -> None:
    """V fails on attempt 1, succeeds on attempt 2."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )

    # Attempt 1: R path verify fails, heuristic path (no candidates)
    # Attempt 2: R path verify succeeds
    call_count = 0

    async def verify_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            return VerifyResult(success=False, message="Not yet")
        return VerifyResult(success=True, message="OK")

    mock_verifier.verify.side_effect = verify_side_effect

    step = _make_step(
        max_attempts=3,
        verify_condition=VerifyCondition(type="element_gone", value="#popup"),
    )
    result = await orchestrator.execute_step(step)

    assert result.success is True


# ── 4. max_attempts limit ────────────────────────────


async def test_max_attempts_exhausted(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
    mock_verifier: AsyncMock,
) -> None:
    """After max_attempts, step returns failure."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )
    mock_verifier.verify.return_value = VerifyResult(
        success=False, message="Always fails"
    )

    step = _make_step(
        max_attempts=2,
        verify_condition=VerifyCondition(type="element_visible", value="#result"),
    )
    result = await orchestrator.execute_step(step)

    assert result.success is False
    assert result.latency_ms > 0


async def test_single_attempt_max(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
) -> None:
    """With max_attempts=1, only one try is made."""
    mock_rule_engine.match.return_value = None

    step = _make_step(max_attempts=1)
    result = await orchestrator.execute_step(step)

    assert result.success is False


# ── 5. Skip recovery when fallback_router is None ────


async def test_no_fallback_router_skips_recovery(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
) -> None:
    """When fallback_router is None, F classification is skipped entirely."""
    # Make R fail with an exception
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#missing", method="click"
    )
    mock_executor.click.side_effect = SelectorNotFoundError("Element not found")

    step = _make_step(max_attempts=1)
    result = await orchestrator.execute_step(step)

    # Should exhaust attempts without crashing
    assert result.success is False


# ── 6. Full step list execution via run() ────────────


async def test_run_multiple_steps(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
) -> None:
    """run() processes all steps and returns results in order."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )

    steps = [
        _make_step(step_id="s1", intent="step one"),
        _make_step(step_id="s2", intent="step two"),
        _make_step(step_id="s3", intent="step three"),
    ]
    results = await orchestrator.run(steps)

    assert len(results) == 3
    assert results[0].step_id == "s1"
    assert results[1].step_id == "s2"
    assert results[2].step_id == "s3"
    assert all(r.success for r in results)


async def test_run_empty_steps(orchestrator: Orchestrator) -> None:
    """run([]) returns an empty list."""
    results = await orchestrator.run([])
    assert results == []


async def test_run_mixed_success_failure(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
) -> None:
    """run() continues even when some steps fail."""
    call_count = 0

    def match_side_effect(intent, context):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            return None  # step 2 will fail (no match, no heuristic)
        return RuleMatch(rule_id="r1", selector="#btn", method="click")

    mock_rule_engine.match.side_effect = match_side_effect

    steps = [
        _make_step(step_id="s1", max_attempts=1),
        _make_step(step_id="s2", max_attempts=1),
        _make_step(step_id="s3", max_attempts=1),
    ]
    results = await orchestrator.run(steps)

    assert len(results) == 3
    assert results[0].success is True
    assert results[1].success is False
    assert results[2].success is True


# ── 7. Cost/token tracking ───────────────────────────


async def test_latency_tracking(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
) -> None:
    """StepResult.latency_ms is always positive."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )

    step = _make_step()
    result = await orchestrator.execute_step(step)

    assert result.latency_ms > 0


async def test_tokens_zero_for_rule_path(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
) -> None:
    """R path uses zero LLM tokens."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )

    step = _make_step()
    result = await orchestrator.execute_step(step)

    assert result.tokens_used == 0
    assert result.cost_usd == 0.0


async def test_llm_escalation_tracks_tokens(
    orchestrator_full: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_extractor: AsyncMock,
    mock_verifier: AsyncMock,
    mock_fallback_router: MagicMock,
    mock_planner: AsyncMock,
    mock_executor: AsyncMock,
) -> None:
    """LLM escalation path records tokens_used and cost_usd."""
    # R fails, heuristic fails, F routes to escalate_llm, L succeeds
    mock_rule_engine.match.return_value = None
    mock_rule_engine.heuristic_select.return_value = None

    # Make extractor return candidates for LLM
    candidate = ExtractedElement(
        eid="#alt-btn", type="button", text="Alternative", visible=True
    )
    mock_extractor.extract_clickables.return_value = [candidate]

    mock_fallback_router.route.return_value = RecoveryPlan(
        strategy="escalate_llm", tier=2
    )

    mock_verifier.verify.return_value = VerifyResult(success=True, message="OK")

    step = _make_step(
        max_attempts=2,
        verify_condition=VerifyCondition(type="element_visible", value="#result"),
    )
    result = await orchestrator_full.execute_step(step)

    assert result.success is True
    assert result.method == "L2"
    assert result.tokens_used > 0
    assert result.cost_usd > 0.0


# ── 8. Fallback router strategies ────────────────────


async def test_skip_strategy(
    orchestrator_full: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
    mock_fallback_router: MagicMock,
) -> None:
    """F(classify) -> skip strategy returns failure immediately."""
    mock_rule_engine.match.return_value = None
    mock_rule_engine.heuristic_select.return_value = None

    mock_fallback_router.route.return_value = RecoveryPlan(strategy="skip", tier=1)

    step = _make_step(max_attempts=3)
    result = await orchestrator_full.execute_step(step)

    assert result.success is False
    assert result.method == "F"


async def test_human_handoff_strategy(
    orchestrator_full: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
    mock_fallback_router: MagicMock,
) -> None:
    """F(classify) -> human_handoff returns failure with method=H."""
    mock_rule_engine.match.return_value = None
    mock_rule_engine.heuristic_select.return_value = None

    mock_fallback_router.route.return_value = RecoveryPlan(
        strategy="human_handoff", tier=3
    )

    step = _make_step(max_attempts=3)
    result = await orchestrator_full.execute_step(step)

    assert result.success is False
    assert result.method == "H"


async def test_retry_strategy_with_fallback_router(
    orchestrator_full: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
    mock_verifier: AsyncMock,
    mock_fallback_router: MagicMock,
) -> None:
    """F(classify) -> retry strategy allows continuing to next attempt."""
    call_count = 0

    def match_side_effect(intent, context):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None  # First attempt fails
        return RuleMatch(rule_id="r1", selector="#btn", method="click")

    mock_rule_engine.match.side_effect = match_side_effect
    mock_rule_engine.heuristic_select.return_value = None

    mock_fallback_router.route.return_value = RecoveryPlan(
        strategy="retry", tier=1
    )
    mock_verifier.verify.return_value = VerifyResult(success=True, message="OK")

    step = _make_step(
        max_attempts=3,
        verify_condition=VerifyCondition(type="element_visible", value="#result"),
    )
    result = await orchestrator_full.execute_step(step)

    assert result.success is True
    assert result.method == "R"


# ── 9. LLM planner not available ─────────────────────


async def test_llm_escalation_skipped_when_planner_none(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
) -> None:
    """When planner is None, escalate_llm is skipped gracefully."""
    # orchestrator fixture has no planner
    mock_rule_engine.match.return_value = None
    mock_rule_engine.heuristic_select.return_value = None

    step = _make_step(max_attempts=1)
    result = await orchestrator.execute_step(step)

    # Should not crash, just fail
    assert result.success is False


# ── 10. Execution action dispatch ────────────────────


async def test_type_action_dispatch(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
) -> None:
    """Rule match with method=type dispatches to executor.type_text."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="search",
        selector="#search-input",
        method="type",
        arguments=["wireless earbuds"],
    )

    step = _make_step(arguments=["wireless earbuds"])
    result = await orchestrator.execute_step(step)

    assert result.success is True
    mock_executor.type_text.assert_awaited_once()


async def test_execution_error_captured(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_executor: AsyncMock,
) -> None:
    """AutomationError during execution is caught and recorded in failure_code."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )
    mock_executor.click.side_effect = SelectorNotFoundError("Not found")

    step = _make_step(max_attempts=1)
    result = await orchestrator.execute_step(step)

    assert result.success is False
    assert result.failure_code == FailureCode.SELECTOR_NOT_FOUND


# ── 11. Step result method tracking ──────────────────


async def test_method_R_on_rule_path(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
) -> None:
    """Successful rule match path records method='R'."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )

    step = _make_step()
    result = await orchestrator.execute_step(step)

    assert result.method == "R"


async def test_method_L1_on_heuristic_path(
    orchestrator: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_extractor: AsyncMock,
    mock_verifier: AsyncMock,
) -> None:
    """Heuristic success records method='L1'."""
    mock_rule_engine.match.return_value = None

    candidate = ExtractedElement(
        eid="#found", type="button", text="Found", visible=True
    )
    mock_extractor.extract_clickables.return_value = [candidate]
    mock_rule_engine.heuristic_select.return_value = "#found"
    mock_verifier.verify.return_value = VerifyResult(success=True, message="OK")

    step = _make_step(
        verify_condition=VerifyCondition(type="element_visible", value="#x"),
    )
    result = await orchestrator.execute_step(step)

    assert result.method == "L1"


# ── 12. Vision escalation placeholder ────────────────


async def test_vision_escalation_no_modules(
    orchestrator_full: Orchestrator,
    mock_rule_engine: MagicMock,
    mock_fallback_router: MagicMock,
) -> None:
    """escalate_vision with no vision modules returns failure safely."""
    mock_rule_engine.match.return_value = None
    mock_rule_engine.heuristic_select.return_value = None

    mock_fallback_router.route.return_value = RecoveryPlan(
        strategy="escalate_vision", tier=2
    )

    step = _make_step(max_attempts=1)
    result = await orchestrator_full.execute_step(step)

    # Should exhaust attempts without crashing
    assert result.success is False


# ── 13. Vision escalation (G1) ──────────────────────


def _make_orchestrator_with_vision(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
    mock_fallback_router: MagicMock,
    yolo_detector: AsyncMock | None = None,
    vlm_client: AsyncMock | None = None,
    coord_mapper: MagicMock | None = None,
) -> Orchestrator:
    """Helper to create an orchestrator with vision modules."""
    return Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
        fallback_router=mock_fallback_router,
        yolo_detector=yolo_detector,
        vlm_client=vlm_client,
        coord_mapper=coord_mapper,
    )


async def test_vision_yolo_success(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
    mock_fallback_router: MagicMock,
) -> None:
    """YOLO detects element, verify passes -> method='YOLO', tokens=0."""
    mock_rule_engine.match.return_value = None
    mock_rule_engine.heuristic_select.return_value = None

    mock_fallback_router.route.return_value = RecoveryPlan(
        strategy="escalate_vision", tier=2
    )

    mock_executor.screenshot = AsyncMock(return_value=b"fake_screenshot")
    mock_verifier.verify.return_value = VerifyResult(success=True, message="OK")

    yolo = AsyncMock()
    yolo.detect_elements = AsyncMock(
        return_value=[
            ExtractedElement(
                eid="yolo-0-button", type="button", text="button",
                bbox=(10, 20, 100, 50), visible=True,
            )
        ]
    )

    orch = _make_orchestrator_with_vision(
        mock_executor, mock_extractor, mock_rule_engine,
        mock_verifier, mock_fallback_router, yolo_detector=yolo,
    )

    step = _make_step(
        max_attempts=2,
        verify_condition=VerifyCondition(type="element_visible", value="#result"),
    )
    result = await orch.execute_step(step)

    assert result.success is True
    assert result.method == "YOLO"
    assert result.tokens_used == 0


async def test_vision_vlm_fallback(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
    mock_fallback_router: MagicMock,
) -> None:
    """YOLO is None, VLM succeeds -> method='VLM'."""
    mock_rule_engine.match.return_value = None
    mock_rule_engine.heuristic_select.return_value = None

    mock_fallback_router.route.return_value = RecoveryPlan(
        strategy="escalate_vision", tier=2
    )

    mock_executor.screenshot = AsyncMock(return_value=b"fake_screenshot")
    mock_verifier.verify.return_value = VerifyResult(success=True, message="OK")

    candidate = ExtractedElement(
        eid="#btn-vlm", type="button", text="Click me", visible=True
    )
    mock_extractor.extract_clickables.return_value = [candidate]

    vlm = AsyncMock()
    vlm.select_element = AsyncMock(
        return_value=PatchData(
            patch_type="selector_fix",
            target="#btn-vlm",
            data={"selected_eid": "#btn-vlm", "tokens_used": 200, "cost_usd": 0.002},
            confidence=0.9,
        )
    )

    orch = _make_orchestrator_with_vision(
        mock_executor, mock_extractor, mock_rule_engine,
        mock_verifier, mock_fallback_router, vlm_client=vlm,
    )

    step = _make_step(
        max_attempts=2,
        verify_condition=VerifyCondition(type="element_visible", value="#result"),
    )
    result = await orch.execute_step(step)

    assert result.success is True
    assert result.method == "VLM"
    assert result.tokens_used >= 200


async def test_vision_no_modules(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
    mock_fallback_router: MagicMock,
) -> None:
    """No vision modules -> returns None safely."""
    mock_rule_engine.match.return_value = None
    mock_rule_engine.heuristic_select.return_value = None

    mock_fallback_router.route.return_value = RecoveryPlan(
        strategy="escalate_vision", tier=2
    )

    orch = _make_orchestrator_with_vision(
        mock_executor, mock_extractor, mock_rule_engine,
        mock_verifier, mock_fallback_router,
    )

    step = _make_step(max_attempts=1)
    result = await orch.execute_step(step)

    assert result.success is False


async def test_vision_yolo_fail_vlm_success(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
    mock_fallback_router: MagicMock,
) -> None:
    """YOLO raises exception, VLM succeeds."""
    mock_rule_engine.match.return_value = None
    mock_rule_engine.heuristic_select.return_value = None

    mock_fallback_router.route.return_value = RecoveryPlan(
        strategy="escalate_vision", tier=2
    )

    mock_executor.screenshot = AsyncMock(return_value=b"fake_screenshot")
    mock_verifier.verify.return_value = VerifyResult(success=True, message="OK")

    candidate = ExtractedElement(
        eid="#btn-vlm", type="button", text="Click me", visible=True
    )
    mock_extractor.extract_clickables.return_value = [candidate]

    yolo = AsyncMock()
    yolo.detect_elements = AsyncMock(side_effect=RuntimeError("YOLO model error"))

    vlm = AsyncMock()
    vlm.select_element = AsyncMock(
        return_value=PatchData(
            patch_type="selector_fix",
            target="#btn-vlm",
            data={"selected_eid": "#btn-vlm", "tokens_used": 200, "cost_usd": 0.002},
            confidence=0.9,
        )
    )

    orch = _make_orchestrator_with_vision(
        mock_executor, mock_extractor, mock_rule_engine,
        mock_verifier, mock_fallback_router,
        yolo_detector=yolo, vlm_client=vlm,
    )

    step = _make_step(
        max_attempts=2,
        verify_condition=VerifyCondition(type="element_visible", value="#result"),
    )
    result = await orch.execute_step(step)

    assert result.success is True
    assert result.method == "VLM"


# ── 14. Learning loop (G2) ──────────────────────────


async def test_learning_records_success(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
) -> None:
    """After successful step, rule_promoter.record_step_result is called."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )
    mock_verifier.verify.return_value = VerifyResult(success=True, message="OK")

    rule_promoter = AsyncMock()
    rule_promoter.record_step_result = AsyncMock()
    rule_promoter.check_and_promote = AsyncMock(return_value=[])

    orch = Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
        rule_promoter=rule_promoter,
    )

    steps = [_make_step()]
    await orch.run(steps)

    rule_promoter.record_step_result.assert_awaited_once()
    # Verify the first positional arg is a StepResult with success=True
    call_args = rule_promoter.record_step_result.call_args
    assert call_args[0][0].success is True


async def test_learning_records_failure(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
) -> None:
    """After failed step, record_step_result is called with failure."""
    mock_rule_engine.match.return_value = None
    mock_rule_engine.heuristic_select.return_value = None

    rule_promoter = AsyncMock()
    rule_promoter.record_step_result = AsyncMock()
    rule_promoter.check_and_promote = AsyncMock(return_value=[])

    orch = Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
        rule_promoter=rule_promoter,
    )

    steps = [_make_step(max_attempts=1)]
    await orch.run(steps)

    rule_promoter.record_step_result.assert_awaited_once()
    call_args = rule_promoter.record_step_result.call_args
    assert call_args[0][0].success is False


async def test_learning_periodic_promotion(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
) -> None:
    """After 5 steps, check_and_promote is called."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )
    mock_verifier.verify.return_value = VerifyResult(success=True, message="OK")

    rule_promoter = AsyncMock()
    rule_promoter.record_step_result = AsyncMock()
    rule_promoter.check_and_promote = AsyncMock(return_value=[])

    orch = Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
        rule_promoter=rule_promoter,
    )

    steps = [_make_step(step_id=f"s{i}") for i in range(5)]
    await orch.run(steps)

    # check_and_promote should be called once (at step 5)
    rule_promoter.check_and_promote.assert_awaited_once()


async def test_learning_none_safe(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
) -> None:
    """With rule_promoter=None, no errors occur."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )

    orch = Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
        rule_promoter=None,
    )

    steps = [_make_step(step_id=f"s{i}") for i in range(6)]
    results = await orch.run(steps)

    assert len(results) == 6
    assert all(r.success for r in results)


# ── 15. Progress callbacks (G5) ─────────────────────


async def test_progress_events_emitted(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
) -> None:
    """Run 1 step, verify RUN_STARTED, STEP_STARTED, STEP_COMPLETED, RUN_COMPLETED events."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )

    callback = MagicMock()
    callback.on_progress = MagicMock()

    orch = Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
        progress_callback=callback,
    )

    steps = [_make_step()]
    await orch.run(steps)

    # Collect all events emitted
    events = [call[0][0].event for call in callback.on_progress.call_args_list]

    assert ProgressEvent.RUN_STARTED in events
    assert ProgressEvent.STEP_STARTED in events
    assert ProgressEvent.STEP_COMPLETED in events
    assert ProgressEvent.RUN_COMPLETED in events


async def test_progress_callback_none_safe(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
) -> None:
    """With progress_callback=None, no errors occur."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )

    orch = Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
        progress_callback=None,
    )

    steps = [_make_step()]
    results = await orch.run(steps)

    assert len(results) == 1
    assert results[0].success is True


# ── 16. Single-step API (G8) ────────────────────────


async def test_execute_one_success(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
) -> None:
    """execute_one returns StepResult and learning is called."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )

    rule_promoter = AsyncMock()
    rule_promoter.record_step_result = AsyncMock()

    callback = MagicMock()
    callback.on_progress = MagicMock()

    orch = Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
        rule_promoter=rule_promoter,
        progress_callback=callback,
    )

    step = _make_step()
    result = await orch.execute_one(step)

    assert result.success is True
    assert result.method == "R"
    rule_promoter.record_step_result.assert_awaited_once()

    # Check callbacks emitted
    events = [call[0][0].event for call in callback.on_progress.call_args_list]
    assert ProgressEvent.RUN_STARTED in events
    assert ProgressEvent.STEP_COMPLETED in events
    assert ProgressEvent.RUN_COMPLETED in events


async def test_execute_one_failure(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
) -> None:
    """execute_one with failing step emits STEP_FAILED."""
    mock_rule_engine.match.return_value = None
    mock_rule_engine.heuristic_select.return_value = None

    callback = MagicMock()
    callback.on_progress = MagicMock()

    orch = Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
        progress_callback=callback,
    )

    step = _make_step(max_attempts=1)
    result = await orch.execute_one(step)

    assert result.success is False

    events = [call[0][0].event for call in callback.on_progress.call_args_list]
    assert ProgressEvent.STEP_FAILED in events


async def test_run_intent_success(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
) -> None:
    """run_intent('click search', '#btn') works."""
    mock_rule_engine.match.return_value = RuleMatch(
        rule_id="r1", selector="#btn", method="click"
    )

    orch = Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
    )

    result = await orch.run_intent("click search", "#btn")

    assert result.success is True
    assert result.step_id == "inline_1"


async def test_run_intent_defaults(
    mock_executor: AsyncMock,
    mock_extractor: AsyncMock,
    mock_rule_engine: MagicMock,
    mock_verifier: AsyncMock,
) -> None:
    """run_intent with minimal args (no selector, no arguments)."""
    mock_rule_engine.match.return_value = None
    mock_rule_engine.heuristic_select.return_value = None

    orch = Orchestrator(
        executor=mock_executor,
        extractor=mock_extractor,
        rule_engine=mock_rule_engine,
        verifier=mock_verifier,
    )

    result = await orch.run_intent("click something")

    assert result.step_id == "inline_1"
    # Will fail because no rule match and no heuristic, but should not crash
    assert result.success is False
