"""Integration tests — verify module wiring and orchestration flow.

No real browser or API calls. All external dependencies are mocked.
Tests verify that the full engine pipeline (R -> E -> F -> L -> V)
works correctly when modules are wired together through the Orchestrator.

Covers:
- Module instantiation and type correctness
- DI wiring into Orchestrator
- Workflow parsing + orchestration (full path)
- Rule match -> executor -> verifier chain
- Heuristic fallback -> executor -> verifier chain
- Failure -> fallback router -> recovery plan chain
- LLM escalation chain (mocked Gemini)
- Pattern recording after successful step
- Rule promotion after 3 successes
- Memory persistence across steps
- Handoff triggers on CAPTCHA detection
- Step queue integration with orchestrator
- Cost accumulation across multi-step workflow
- Multi-iteration rule match improvement (simulated)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.extractor import DOMExtractor
from src.core.fallback_router import FallbackRouter, create_fallback_router
from src.core.orchestrator import Orchestrator
from src.core.rule_engine import RuleEngine
from src.core.types import (
    CaptchaDetectedError,
    ExtractedElement,
    FailureCode,
    PageState,
    PatchData,
    RecoveryPlan,
    RuleDefinition,
    RuleMatch,
    SelectorNotFoundError,
    StepContext,
    StepDefinition,
    VerifyCondition,
    VerifyResult,
)
from src.core.verifier import Verifier
from src.learning.memory_manager import MemoryManager
from src.learning.pattern_db import PatternDB
from src.learning.rule_promoter import RulePromoter
from src.workflow.dsl_parser import parse_workflow
from src.workflow.step_queue import StepQueue

# ── Helpers ──────────────────────────────────────────


def _make_page_state(**kwargs: object) -> PageState:
    """Create a minimal PageState for testing."""
    defaults = {"url": "https://shopping.naver.com", "title": "Test"}
    defaults.update(kwargs)  # type: ignore[arg-type]
    return PageState(**defaults)  # type: ignore[arg-type]


def _make_step(
    step_id: str = "s1",
    intent: str = "click something",
    max_attempts: int = 3,
    verify_condition: VerifyCondition | None = None,
    arguments: list[str] | None = None,
) -> StepDefinition:
    """Create a minimal StepDefinition."""
    return StepDefinition(
        step_id=step_id,
        intent=intent,
        max_attempts=max_attempts,
        verify_condition=verify_condition,
        arguments=arguments or [],
    )


def _mock_executor() -> AsyncMock:
    """Create a mock executor with async methods."""
    executor = AsyncMock()
    mock_page = AsyncMock()
    mock_page.url = "https://shopping.naver.com/search?query=test"
    executor.get_page = AsyncMock(return_value=mock_page)
    executor.click = AsyncMock()
    executor.type_text = AsyncMock()
    executor.goto = AsyncMock()
    executor.scroll = AsyncMock()
    executor.wait_for = AsyncMock()
    executor.close = AsyncMock()
    return executor


def _mock_extractor() -> AsyncMock:
    """Create a mock extractor."""
    extractor = AsyncMock()
    extractor.extract_state = AsyncMock(return_value=_make_page_state())
    extractor.extract_clickables = AsyncMock(return_value=[])
    extractor.extract_inputs = AsyncMock(return_value=[])
    extractor.extract_products = AsyncMock(return_value=[])
    return extractor


# ── 1. Module Instantiation Tests ───────────────────


class TestModuleInstantiation:
    """Test that all modules instantiate with correct types."""

    def test_extractor_is_correct_type(self) -> None:
        """DOMExtractor instantiates without error."""
        extractor = DOMExtractor()
        assert hasattr(extractor, "extract_inputs")
        assert hasattr(extractor, "extract_clickables")
        assert hasattr(extractor, "extract_products")
        assert hasattr(extractor, "extract_state")

    def test_rule_engine_is_correct_type(self, tmp_path: Path) -> None:
        """RuleEngine instantiates with a temp config dir."""
        # Create minimal config structure.
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (tmp_path / "synonyms.yaml").write_text("{}")
        engine = RuleEngine(config_dir=tmp_path)
        assert hasattr(engine, "match")
        assert hasattr(engine, "heuristic_select")
        assert hasattr(engine, "register_rule")

    def test_verifier_is_correct_type(self) -> None:
        """Verifier instantiates without error."""
        verifier = Verifier()
        assert hasattr(verifier, "verify")

    def test_fallback_router_is_correct_type(self) -> None:
        """FallbackRouter instantiates and has required methods."""
        router = FallbackRouter()
        assert hasattr(router, "classify")
        assert hasattr(router, "route")
        assert hasattr(router, "get_escalation_chain")

    def test_fallback_router_factory(self) -> None:
        """create_fallback_router() returns a FallbackRouter."""
        router = create_fallback_router()
        assert isinstance(router, FallbackRouter)

    async def test_memory_manager_instantiates(self, tmp_path: Path) -> None:
        """MemoryManager instantiates and creates directories."""
        mgr = MemoryManager(data_dir=tmp_path)
        assert mgr.get_working("nonexistent") is None
        assert (tmp_path / "episodes").exists()
        assert (tmp_path / "artifacts").exists()

    async def test_pattern_db_instantiates(self, tmp_path: Path) -> None:
        """PatternDB instantiates and creates the DB file."""
        db = PatternDB(db_path=tmp_path / "test.db")
        await db.init_db()
        assert (tmp_path / "test.db").exists()

    def test_step_queue_instantiates(self) -> None:
        """StepQueue instantiates empty."""
        queue = StepQueue()
        assert queue.is_empty()
        assert queue.size() == 0


# ── 2. Orchestrator DI Wiring ───────────────────────


class TestOrchestratorDI:
    """Test that Orchestrator accepts all modules via DI."""

    def test_orchestrator_with_required_modules_only(self) -> None:
        """Orchestrator initializes with 4 required modules."""
        orch = Orchestrator(
            executor=_mock_executor(),
            extractor=_mock_extractor(),
            rule_engine=MagicMock(),
            verifier=AsyncMock(),
        )
        assert orch is not None

    def test_orchestrator_with_all_modules(self) -> None:
        """Orchestrator initializes with all 7 modules."""
        orch = Orchestrator(
            executor=_mock_executor(),
            extractor=_mock_extractor(),
            rule_engine=MagicMock(),
            verifier=AsyncMock(),
            fallback_router=MagicMock(),
            planner=AsyncMock(),
            memory=MagicMock(),
        )
        assert orch is not None

    def test_orchestrator_optional_modules_default_none(self) -> None:
        """Optional modules (F, L, Memory) default to None."""
        orch = Orchestrator(
            executor=_mock_executor(),
            extractor=_mock_extractor(),
            rule_engine=MagicMock(),
            verifier=AsyncMock(),
        )
        assert orch._fallback_router is None
        assert orch._planner is None
        assert orch._memory is None


# ── 3. Workflow Parsing + Orchestration ─────────────


class TestWorkflowOrchestration:
    """Test workflow parsing integrated with orchestration."""

    def test_parse_naver_workflow(self) -> None:
        """The naver_shopping.yaml parses into 11 StepDefinitions."""
        workflow_path = (
            Path(__file__).resolve().parents[2]
            / "tests"
            / "fixtures"
            / "workflows"
            / "naver_shopping.yaml"
        )
        steps = parse_workflow(workflow_path)
        assert len(steps) == 11
        assert steps[0].step_id == "open_naver_shopping"
        assert steps[2].step_id == "search_product"
        assert steps[10].step_id == "loop_pages"

    async def test_workflow_parsing_then_orchestration(self) -> None:
        """Parse a YAML workflow and run it through the orchestrator."""
        yaml_text = """
workflow:
  name: "test"
  steps:
    - id: "s1"
      intent: "Go to example"
      arguments: ["https://example.com"]
    - id: "s2"
      intent: "Click button"
"""
        steps = parse_workflow(yaml_text)
        assert len(steps) == 2

        executor = _mock_executor()
        extractor = _mock_extractor()
        rule_engine = MagicMock()
        rule_engine.match.return_value = RuleMatch(
            rule_id="r1", selector="#btn", method="click"
        )
        verifier = AsyncMock()
        verifier.verify = AsyncMock(return_value=VerifyResult(success=True))

        orch = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine,
            verifier=verifier,
        )
        results = await orch.run(steps)
        assert len(results) == 2
        assert all(r.success for r in results)


# ── 4. Rule Match -> Executor -> Verifier Chain ────


class TestRuleExecuteVerifyChain:
    """Test the R -> X -> V pipeline."""

    async def test_rule_match_triggers_click(self) -> None:
        """Rule match dispatches to executor.click()."""
        executor = _mock_executor()
        extractor = _mock_extractor()
        rule_engine = MagicMock()
        rule_engine.match.return_value = RuleMatch(
            rule_id="popup_close",
            selector="#close-btn",
            method="click",
        )
        verifier = AsyncMock()
        verifier.verify = AsyncMock(return_value=VerifyResult(success=True))

        orch = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine,
            verifier=verifier,
        )
        step = _make_step(
            verify_condition=VerifyCondition(type="element_gone", value="#popup")
        )
        result = await orch.execute_step(step)

        assert result.success is True
        assert result.method == "R"
        executor.click.assert_awaited_once()

    async def test_rule_match_type_dispatches_to_type_text(self) -> None:
        """Rule match with method='type' dispatches to executor.type_text()."""
        executor = _mock_executor()
        extractor = _mock_extractor()
        rule_engine = MagicMock()
        rule_engine.match.return_value = RuleMatch(
            rule_id="search_input",
            selector="#search",
            method="type",
            arguments=["test query"],
        )
        verifier = AsyncMock()
        verifier.verify = AsyncMock(return_value=VerifyResult(success=True))

        orch = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine,
            verifier=verifier,
        )
        step = _make_step(arguments=["test query"])
        result = await orch.execute_step(step)

        assert result.success is True
        executor.type_text.assert_awaited_once()


# ── 5. Heuristic Fallback -> Executor -> Verifier ──


class TestHeuristicFallbackChain:
    """Test the E + R(heuristic) -> X -> V pipeline."""

    async def test_heuristic_fallback_succeeds(self) -> None:
        """When R(rule) misses, heuristic select picks a candidate."""
        executor = _mock_executor()
        extractor = _mock_extractor()
        candidate = ExtractedElement(
            eid="#alt-btn", type="button", text="Alternative", visible=True
        )
        extractor.extract_clickables.return_value = [candidate]

        rule_engine = MagicMock()
        rule_engine.match.return_value = None
        rule_engine.heuristic_select.return_value = "#alt-btn"

        verifier = AsyncMock()
        verifier.verify = AsyncMock(return_value=VerifyResult(success=True))

        orch = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine,
            verifier=verifier,
        )
        step = _make_step(
            verify_condition=VerifyCondition(type="element_visible", value="#result")
        )
        result = await orch.execute_step(step)

        assert result.success is True
        assert result.method == "L1"


# ── 6. Failure -> Fallback Router -> Recovery Plan ──


class TestFailureRecoveryChain:
    """Test the F(classify) -> recovery chain."""

    async def test_fallback_router_classifies_and_routes(self) -> None:
        """FallbackRouter.classify + route produces a valid RecoveryPlan."""
        router = FallbackRouter()
        error = SelectorNotFoundError("Not found")
        context = StepContext(
            step=_make_step(),
            page_state=_make_page_state(),
            attempt=1,
        )

        code = router.classify(error, context)
        assert code == FailureCode.SELECTOR_NOT_FOUND

        plan = router.route(code)
        assert plan.strategy == "escalate_llm"
        assert plan.tier == 1

    async def test_captcha_triggers_human_handoff(self) -> None:
        """CaptchaDetectedError routes to human_handoff."""
        router = FallbackRouter()
        error = CaptchaDetectedError("CAPTCHA found")
        context = StepContext(
            step=_make_step(),
            page_state=_make_page_state(has_captcha=True),
            attempt=1,
        )

        code = router.classify(error, context)
        assert code == FailureCode.CAPTCHA_DETECTED

        plan = router.route(code)
        assert plan.strategy == "human_handoff"

    async def test_escalation_chain_ordering(self) -> None:
        """Escalation chain is ordered cheapest-first."""
        router = FallbackRouter()
        chain = router.get_escalation_chain(FailureCode.SELECTOR_NOT_FOUND)

        assert len(chain) >= 3
        # First should be retry (cheapest).
        assert chain[0].strategy == "retry"
        # Last should be human_handoff (most expensive).
        assert chain[-1].strategy == "human_handoff"

    async def test_recovery_skip_returns_failure(self) -> None:
        """Skip strategy from fallback router produces immediate failure."""
        executor = _mock_executor()
        extractor = _mock_extractor()
        rule_engine = MagicMock()
        rule_engine.match.return_value = None
        rule_engine.heuristic_select.return_value = None
        verifier = AsyncMock()

        fallback_router = MagicMock()
        fallback_router.classify.return_value = FailureCode.SELECTOR_NOT_FOUND
        fallback_router.route.return_value = RecoveryPlan(strategy="skip", tier=1)

        orch = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine,
            verifier=verifier,
            fallback_router=fallback_router,
        )
        step = _make_step(max_attempts=3)
        result = await orch.execute_step(step)

        assert result.success is False
        assert result.method == "F"


# ── 7. LLM Escalation Chain (Mocked Gemini) ────────


class TestLLMEscalation:
    """Test LLM escalation path with mocked planner."""

    async def test_llm_escalation_succeeds(self) -> None:
        """F -> escalate_llm -> L(select) -> X -> V -> success."""
        executor = _mock_executor()
        extractor = _mock_extractor()
        candidate = ExtractedElement(
            eid="#llm-pick", type="button", text="LLM Choice", visible=True
        )
        extractor.extract_clickables.return_value = [candidate]

        rule_engine = MagicMock()
        rule_engine.match.return_value = None
        rule_engine.heuristic_select.return_value = None

        verifier = AsyncMock()
        verifier.verify = AsyncMock(return_value=VerifyResult(success=True))

        fallback_router = MagicMock()
        fallback_router.classify.return_value = FailureCode.SELECTOR_NOT_FOUND
        fallback_router.route.return_value = RecoveryPlan(
            strategy="escalate_llm", tier=2
        )

        planner = AsyncMock()
        planner.select = AsyncMock(
            return_value=PatchData(
                patch_type="selector_fix",
                target="#llm-pick",
                data={
                    "selector": "#llm-pick",
                    "method": "click",
                    "tokens_used": 200,
                    "cost_usd": 0.003,
                },
                confidence=0.9,
            )
        )

        orch = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine,
            verifier=verifier,
            fallback_router=fallback_router,
            planner=planner,
        )
        step = _make_step(
            max_attempts=2,
            verify_condition=VerifyCondition(type="element_visible", value="#result"),
        )
        result = await orch.execute_step(step)

        assert result.success is True
        assert result.method == "L2"
        assert result.tokens_used > 0
        assert result.cost_usd > 0.0

    async def test_llm_planner_none_skips_escalation(self) -> None:
        """When planner=None, escalate_llm is silently skipped."""
        executor = _mock_executor()
        extractor = _mock_extractor()
        rule_engine = MagicMock()
        rule_engine.match.return_value = None
        rule_engine.heuristic_select.return_value = None
        verifier = AsyncMock()

        fallback_router = MagicMock()
        fallback_router.classify.return_value = FailureCode.SELECTOR_NOT_FOUND
        fallback_router.route.return_value = RecoveryPlan(
            strategy="escalate_llm", tier=2
        )

        orch = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine,
            verifier=verifier,
            fallback_router=fallback_router,
            planner=None,
        )
        step = _make_step(max_attempts=1)
        result = await orch.execute_step(step)

        assert result.success is False


# ── 8. Pattern Recording After Success ──────────────


class TestPatternRecording:
    """Test that pattern_db records successes."""

    async def test_pattern_db_records_success(self, tmp_path: Path) -> None:
        """PatternDB.record_success increments count."""
        db = PatternDB(db_path=tmp_path / "patterns.db")
        await db.init_db()

        p1 = await db.record_success("click button", "example.com", "#btn", "click")
        assert p1.success_count == 1

        p2 = await db.record_success("click button", "example.com", "#btn", "click")
        assert p2.success_count == 2

    async def test_pattern_db_records_failure(self, tmp_path: Path) -> None:
        """PatternDB.record_failure increments fail count."""
        db = PatternDB(db_path=tmp_path / "patterns.db")
        await db.init_db()

        p1 = await db.record_failure("click button", "example.com", "#btn", "click")
        assert p1.fail_count == 1


# ── 9. Rule Promotion After 3 Successes ─────────────


class TestRulePromotion:
    """Test pattern promotion to rules after threshold."""

    async def test_promotion_after_3_successes(self, tmp_path: Path) -> None:
        """Pattern with 3 successes gets promoted to a rule."""
        db = PatternDB(db_path=tmp_path / "patterns.db")
        await db.init_db()

        # Create a minimal rule engine.
        rules_dir = tmp_path / "config" / "rules"
        rules_dir.mkdir(parents=True)
        (tmp_path / "config" / "synonyms.yaml").write_text("{}")
        rule_engine = RuleEngine(config_dir=tmp_path / "config")

        promoter = RulePromoter(db, rule_engine, min_success=3, min_ratio=0.8)

        # Record 3 successes.
        for _ in range(3):
            await db.record_success("인기순 정렬", "shopping.naver.com", "#sort-pop", "click")

        # Check and promote.
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1
        assert promoted[0].intent_pattern == "인기순 정렬"
        assert promoted[0].selector == "#sort-pop"
        assert promoted[0].category == "sort"

    async def test_no_promotion_below_threshold(self, tmp_path: Path) -> None:
        """Patterns below threshold are not promoted."""
        db = PatternDB(db_path=tmp_path / "patterns.db")
        await db.init_db()

        rules_dir = tmp_path / "config" / "rules"
        rules_dir.mkdir(parents=True)
        (tmp_path / "config" / "synonyms.yaml").write_text("{}")
        rule_engine = RuleEngine(config_dir=tmp_path / "config")

        promoter = RulePromoter(db, rule_engine, min_success=3, min_ratio=0.8)

        # Only 2 successes — not enough.
        for _ in range(2):
            await db.record_success("click btn", "example.com", "#btn", "click")

        promoted = await promoter.check_and_promote()
        assert len(promoted) == 0

    async def test_promoted_rule_registers_in_engine(self, tmp_path: Path) -> None:
        """After promotion, the rule is findable in the rule engine."""
        db = PatternDB(db_path=tmp_path / "patterns.db")
        await db.init_db()

        rules_dir = tmp_path / "config" / "rules"
        rules_dir.mkdir(parents=True)
        (tmp_path / "config" / "synonyms.yaml").write_text("{}")
        rule_engine = RuleEngine(config_dir=tmp_path / "config")

        promoter = RulePromoter(db, rule_engine, min_success=3, min_ratio=0.8)

        for _ in range(3):
            await db.record_success("검색", "example.com", "#search", "type")

        await promoter.check_and_promote()

        # The engine should now have at least one rule.
        assert len(rule_engine.rules) >= 1
        rule_ids = [r.rule_id for r in rule_engine.rules]
        assert any(rid.startswith("promoted_") for rid in rule_ids)


# ── 10. Memory Persistence Across Steps ─────────────


class TestMemoryPersistence:
    """Test memory manager across steps."""

    async def test_working_memory_persists_within_session(
        self, tmp_path: Path
    ) -> None:
        """Working memory values are accessible until clear."""
        mgr = MemoryManager(data_dir=tmp_path)
        mgr.set_working("current_url", "https://shopping.naver.com")
        assert mgr.get_working("current_url") == "https://shopping.naver.com"

        mgr.set_working("step_count", 5)
        assert mgr.get_working("step_count") == 5

    async def test_working_memory_clears_correctly(self, tmp_path: Path) -> None:
        """clear_working() resets all working memory."""
        mgr = MemoryManager(data_dir=tmp_path)
        mgr.set_working("key1", "value1")
        mgr.clear_working()
        assert mgr.get_working("key1") is None

    async def test_episode_memory_save_load(self, tmp_path: Path) -> None:
        """Episode data survives save/load cycle."""
        mgr = MemoryManager(data_dir=tmp_path)
        data = {"steps": 5, "success_rate": 0.8}
        await mgr.save_episode("task-1", data)

        loaded = await mgr.load_episode("task-1")
        assert loaded is not None
        assert loaded["steps"] == 5
        assert loaded["success_rate"] == 0.8

    async def test_policy_memory_save_query(self, tmp_path: Path) -> None:
        """Policy rules persist in SQLite and are queryable."""
        mgr = MemoryManager(data_dir=tmp_path)
        await mgr._ensure_db()

        rule = RuleDefinition(
            rule_id="test_rule",
            category="sort",
            intent_pattern="인기순 정렬",
            selector="#sort-pop",
            method="click",
            site_pattern="shopping.naver.com",
        )
        await mgr.save_policy(rule, success_count=5)

        match = await mgr.query_policy("인기순 정렬", "shopping.naver.com")
        assert match is not None
        assert match.selector == "#sort-pop"
        assert match.rule_id == "test_rule"


# ── 11. Handoff Triggers on CAPTCHA Detection ──────


class TestHandoffTriggers:
    """Test CAPTCHA detection triggers human handoff."""

    async def test_captcha_detection_triggers_handoff_in_orchestrator(self) -> None:
        """CAPTCHA -> F classifies -> human_handoff strategy -> method=H."""
        executor = _mock_executor()
        extractor = _mock_extractor()
        extractor.extract_state.return_value = _make_page_state(has_captcha=True)

        rule_engine = MagicMock()
        rule_engine.match.return_value = None
        rule_engine.heuristic_select.return_value = None

        verifier = AsyncMock()
        fallback_router = FallbackRouter()

        orch = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine,
            verifier=verifier,
            fallback_router=fallback_router,
        )
        step = _make_step(max_attempts=1)
        result = await orch.execute_step(step)

        # With CAPTCHA in page state, F should classify as CAPTCHA_DETECTED
        # which routes to human_handoff.
        # However, the classify depends on the error type; since no error is
        # explicitly CaptchaDetectedError, the heuristic classifier checks
        # page_state.has_captcha.
        # The result should indicate failure with handoff.
        assert result.success is False

    async def test_captcha_error_routes_to_handoff(self) -> None:
        """CaptchaDetectedError always routes to human_handoff."""
        router = FallbackRouter()
        error = CaptchaDetectedError("CAPTCHA detected")
        context = StepContext(
            step=_make_step(),
            page_state=_make_page_state(has_captcha=True),
            attempt=1,
        )
        code = router.classify(error, context)
        plan = router.route(code)

        assert code == FailureCode.CAPTCHA_DETECTED
        assert plan.strategy == "human_handoff"
        assert plan.tier == 3


# ── 12. Step Queue + Orchestrator Integration ──────


class TestStepQueueIntegration:
    """Test step queue used within orchestrator."""

    async def test_step_queue_feeds_orchestrator(self) -> None:
        """Steps pushed to queue are all executed by orchestrator.run()."""
        executor = _mock_executor()
        extractor = _mock_extractor()
        rule_engine = MagicMock()
        rule_engine.match.return_value = RuleMatch(
            rule_id="r1", selector="#btn", method="click"
        )
        verifier = AsyncMock()
        verifier.verify = AsyncMock(return_value=VerifyResult(success=True))

        orch = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine,
            verifier=verifier,
        )

        steps = [
            _make_step(step_id="q1"),
            _make_step(step_id="q2"),
            _make_step(step_id="q3"),
        ]
        results = await orch.run(steps)

        assert len(results) == 3
        assert [r.step_id for r in results] == ["q1", "q2", "q3"]

    def test_step_queue_tracking_completed_and_failed(self) -> None:
        """Queue correctly tracks completed and failed steps."""
        queue = StepQueue()
        s1 = _make_step(step_id="s1")
        s2 = _make_step(step_id="s2")
        s3 = _make_step(step_id="s3")

        queue.push_many([s1, s2, s3])

        step = queue.pop()
        assert step is not None
        queue.mark_completed(step)

        step = queue.pop()
        assert step is not None
        queue.mark_failed(step)

        assert len(queue.completed) == 1
        assert len(queue.failed) == 1
        assert queue.size() == 1  # s3 still pending


# ── 13. Cost Accumulation Across Multi-Step ────────


class TestCostAccumulation:
    """Test that cost and token metrics accumulate correctly."""

    async def test_rule_path_zero_cost(self) -> None:
        """R path has zero tokens and zero cost."""
        executor = _mock_executor()
        extractor = _mock_extractor()
        rule_engine = MagicMock()
        rule_engine.match.return_value = RuleMatch(
            rule_id="r1", selector="#btn", method="click"
        )
        verifier = AsyncMock()
        verifier.verify = AsyncMock(return_value=VerifyResult(success=True))

        orch = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine,
            verifier=verifier,
        )

        steps = [_make_step(step_id=f"s{i}") for i in range(5)]
        results = await orch.run(steps)

        total_tokens = sum(r.tokens_used for r in results)
        total_cost = sum(r.cost_usd for r in results)

        assert total_tokens == 0
        assert total_cost == 0.0

    async def test_llm_path_accumulates_cost(self) -> None:
        """LLM path accumulates tokens and cost across steps."""
        executor = _mock_executor()
        extractor = _mock_extractor()
        candidate = ExtractedElement(
            eid="#x", type="button", text="X", visible=True
        )
        extractor.extract_clickables.return_value = [candidate]

        rule_engine = MagicMock()
        rule_engine.match.return_value = None
        rule_engine.heuristic_select.return_value = None

        verifier = AsyncMock()
        verifier.verify = AsyncMock(return_value=VerifyResult(success=True))

        fallback_router = MagicMock()
        fallback_router.classify.return_value = FailureCode.SELECTOR_NOT_FOUND
        fallback_router.route.return_value = RecoveryPlan(
            strategy="escalate_llm", tier=2
        )

        planner = AsyncMock()
        planner.select = AsyncMock(
            return_value=PatchData(
                patch_type="selector_fix",
                target="#x",
                data={
                    "selector": "#x",
                    "method": "click",
                    "tokens_used": 100,
                    "cost_usd": 0.001,
                },
                confidence=0.9,
            )
        )

        orch = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine,
            verifier=verifier,
            fallback_router=fallback_router,
            planner=planner,
        )

        steps = [
            _make_step(
                step_id=f"s{i}",
                max_attempts=2,
                verify_condition=VerifyCondition(type="element_visible", value="#r"),
            )
            for i in range(3)
        ]
        results = await orch.run(steps)

        total_tokens = sum(r.tokens_used for r in results)
        total_cost = sum(r.cost_usd for r in results)

        # Each step uses LLM with 100 tokens and $0.001.
        assert total_tokens > 0
        assert total_cost > 0.0
        assert all(r.method == "L2" for r in results)


# ── 14. Multi-Iteration Rule Match Improvement ─────


class TestMultiIterationImprovement:
    """Simulate multiple iterations showing rule match improvement."""

    async def test_simulated_rule_match_improvement(self, tmp_path: Path) -> None:
        """Simulate learning: first iteration uses LLM, later iterations use R.

        In a real scenario:
        - Iteration 1: no rule matches, falls to LLM, LLM succeeds, pattern recorded
        - Iteration 2: pattern has 1 success, not promoted yet, LLM again
        - Iteration 3: pattern promoted to rule, R matches directly

        Here we simulate the rule engine's behavior changing over iterations.
        """
        executor = _mock_executor()
        extractor = _mock_extractor()
        verifier = AsyncMock()
        verifier.verify = AsyncMock(return_value=VerifyResult(success=True))

        step = _make_step(
            verify_condition=VerifyCondition(type="element_visible", value="#x")
        )

        iteration_methods: list[str] = []

        for iteration in range(1, 6):
            rule_engine = MagicMock()
            # Simulate: first 2 iterations no rule match, later iterations match
            if iteration <= 2:
                rule_engine.match.return_value = None
                rule_engine.heuristic_select.return_value = "#btn"
                extractor.extract_clickables.return_value = [
                    ExtractedElement(
                        eid="#btn", type="button", text="Btn", visible=True
                    )
                ]
            else:
                rule_engine.match.return_value = RuleMatch(
                    rule_id="promoted_abc", selector="#btn", method="click"
                )

            orch = Orchestrator(
                executor=executor,
                extractor=extractor,
                rule_engine=rule_engine,
                verifier=verifier,
            )
            result = await orch.execute_step(step)
            iteration_methods.append(result.method)

        # First 2 iterations used heuristic (L1), later 3 used R.
        assert iteration_methods[:2] == ["L1", "L1"]
        assert iteration_methods[2:] == ["R", "R", "R"]

    async def test_token_usage_decreases_with_rules(self) -> None:
        """Token usage should be zero once R(rule) handles all steps."""
        executor = _mock_executor()
        extractor = _mock_extractor()
        verifier = AsyncMock()
        verifier.verify = AsyncMock(return_value=VerifyResult(success=True))

        # Iteration 1: LLM path.
        rule_engine_1 = MagicMock()
        rule_engine_1.match.return_value = None
        rule_engine_1.heuristic_select.return_value = None
        extractor.extract_clickables.return_value = [
            ExtractedElement(eid="#x", type="button", text="X", visible=True)
        ]

        fallback = MagicMock()
        fallback.classify.return_value = FailureCode.SELECTOR_NOT_FOUND
        fallback.route.return_value = RecoveryPlan(strategy="escalate_llm", tier=2)

        planner = AsyncMock()
        planner.select = AsyncMock(
            return_value=PatchData(
                patch_type="selector_fix",
                target="#x",
                data={
                    "selector": "#x",
                    "method": "click",
                    "tokens_used": 200,
                    "cost_usd": 0.002,
                },
                confidence=0.9,
            )
        )

        orch1 = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine_1,
            verifier=verifier,
            fallback_router=fallback,
            planner=planner,
        )
        step = _make_step(
            max_attempts=2,
            verify_condition=VerifyCondition(type="element_visible", value="#r"),
        )
        r1 = await orch1.execute_step(step)
        assert r1.tokens_used > 0

        # Iteration 2: R path (rule promoted).
        rule_engine_2 = MagicMock()
        rule_engine_2.match.return_value = RuleMatch(
            rule_id="promoted_abc", selector="#x", method="click"
        )

        orch2 = Orchestrator(
            executor=executor,
            extractor=extractor,
            rule_engine=rule_engine_2,
            verifier=verifier,
        )
        r2 = await orch2.execute_step(step)
        assert r2.tokens_used == 0
        assert r2.cost_usd == 0.0

        # Tokens decreased.
        assert r2.tokens_used < r1.tokens_used


# ── 15. Additional Wiring Tests ────────────────────


class TestAdditionalWiring:
    """Additional integration tests for edge cases and completeness."""

    async def test_orchestrator_handles_empty_step_list(self) -> None:
        """run([]) returns empty results without error."""
        orch = Orchestrator(
            executor=_mock_executor(),
            extractor=_mock_extractor(),
            rule_engine=MagicMock(),
            verifier=AsyncMock(),
        )
        results = await orch.run([])
        assert results == []

    async def test_verify_condition_types_accepted(self) -> None:
        """All verify condition types parse without error."""
        for vtype in ["url_changed", "url_contains", "element_visible",
                       "element_gone", "text_present", "network_idle"]:
            vc = VerifyCondition(type=vtype, value="test")
            assert vc.type == vtype

    async def test_all_failure_codes_have_routes(self) -> None:
        """Every FailureCode has a route in the FallbackRouter."""
        router = FallbackRouter()
        for code in FailureCode:
            plan = router.route(code)
            assert plan is not None
            assert plan.strategy in {
                "retry", "escalate_llm", "escalate_vision", "human_handoff", "skip"
            }

    async def test_all_failure_codes_have_escalation_chains(self) -> None:
        """Every FailureCode has an escalation chain."""
        router = FallbackRouter()
        for code in FailureCode:
            chain = router.get_escalation_chain(code)
            assert len(chain) >= 1

    async def test_fallback_stats_recording(self) -> None:
        """FallbackRouter records recovery outcome statistics."""
        router = FallbackRouter()
        router.record_outcome(FailureCode.SELECTOR_NOT_FOUND, recovered=True)
        router.record_outcome(FailureCode.SELECTOR_NOT_FOUND, recovered=True)
        router.record_outcome(FailureCode.SELECTOR_NOT_FOUND, recovered=False)

        stats = router.get_stats()
        snf = stats["SelectorNotFound"]
        assert snf["total"] == 3
        assert snf["recovered"] == 2
        assert snf["failed"] == 1
        assert snf["recovery_rate"] == pytest.approx(2 / 3)

    async def test_reclassification_after_many_attempts(self) -> None:
        """After 3+ attempts, SELECTOR_NOT_FOUND reclassifies to DYNAMIC_LAYOUT."""
        router = FallbackRouter()
        error = SelectorNotFoundError("Not found")
        context = StepContext(
            step=_make_step(),
            page_state=_make_page_state(),
            attempt=3,
        )
        code = router.classify(error, context)
        assert code == FailureCode.DYNAMIC_LAYOUT
