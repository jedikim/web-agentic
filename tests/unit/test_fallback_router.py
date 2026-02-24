"""Unit tests for F(Fallback Router) — ``src.core.fallback_router``."""
from __future__ import annotations

import pytest

from src.core.fallback_router import (
    FallbackRouter,
    create_fallback_router,
    _DYNAMIC_LAYOUT_ATTEMPT_THRESHOLD,
    _ESCALATION_CHAINS,
    _ROUTE_TABLE,
)
from src.core.types import (
    AuthRequiredError,
    AutomationError,
    BudgetExceededError,
    CaptchaDetectedError,
    FailureCode,
    IFallbackRouter,
    NetworkError,
    NotInteractableError,
    PageState,
    RecoveryPlan,
    SelectorNotFoundError,
    StateNotChangedError,
    StepContext,
    StepDefinition,
    VisualAmbiguityError,
)


# ── Fixtures ─────────────────────────────────────────


@pytest.fixture()
def router() -> FallbackRouter:
    """Create a fresh FallbackRouter instance."""
    return FallbackRouter()


@pytest.fixture()
def step_def() -> StepDefinition:
    """Default StepDefinition for building contexts."""
    return StepDefinition(step_id="test-step", intent="click the button")


@pytest.fixture()
def page_state() -> PageState:
    """Default PageState with no special signals."""
    return PageState(
        url="https://example.com/page",
        title="Example Page",
    )


@pytest.fixture()
def context(step_def: StepDefinition, page_state: PageState) -> StepContext:
    """Default StepContext at attempt 0."""
    return StepContext(step=step_def, page_state=page_state, attempt=0)


def _make_context(
    attempt: int = 0,
    has_captcha: bool = False,
    has_popup: bool = False,
) -> StepContext:
    """Helper to build a StepContext with specific flags."""
    return StepContext(
        step=StepDefinition(step_id="s1", intent="test"),
        page_state=PageState(
            url="https://example.com",
            title="Test",
            has_captcha=has_captcha,
            has_popup=has_popup,
        ),
        attempt=attempt,
    )


# ── Test: Protocol Conformance ───────────────────────


class TestProtocolConformance:
    """FallbackRouter satisfies the IFallbackRouter Protocol."""

    def test_implements_ifallback_router_protocol(self, router: FallbackRouter) -> None:
        """FallbackRouter structurally satisfies IFallbackRouter."""
        # Structural subtyping — check that the required methods exist with
        # compatible signatures.  We verify by assigning to a Protocol-typed variable.
        fallback: IFallbackRouter = router  # type: ignore[assignment]
        assert hasattr(fallback, "classify")
        assert hasattr(fallback, "route")
        assert callable(fallback.classify)
        assert callable(fallback.route)

    def test_factory_returns_fallback_router(self) -> None:
        """create_fallback_router returns a FallbackRouter instance."""
        router = create_fallback_router()
        assert isinstance(router, FallbackRouter)


# ── Test: Exception → FailureCode Classification ────


class TestClassifyKnownExceptions:
    """Each AutomationError subclass maps to the correct FailureCode."""

    def test_selector_not_found_error(self, router: FallbackRouter, context: StepContext) -> None:
        code = router.classify(SelectorNotFoundError("missing .btn"), context)
        assert code == FailureCode.SELECTOR_NOT_FOUND

    def test_not_interactable_error(self, router: FallbackRouter, context: StepContext) -> None:
        code = router.classify(NotInteractableError("element hidden"), context)
        assert code == FailureCode.NOT_INTERACTABLE

    def test_state_not_changed_error(self, router: FallbackRouter, context: StepContext) -> None:
        code = router.classify(StateNotChangedError("page unchanged"), context)
        assert code == FailureCode.STATE_NOT_CHANGED

    def test_visual_ambiguity_error(self, router: FallbackRouter, context: StepContext) -> None:
        code = router.classify(VisualAmbiguityError("3 similar buttons"), context)
        assert code == FailureCode.VISUAL_AMBIGUITY

    def test_network_error(self, router: FallbackRouter, context: StepContext) -> None:
        code = router.classify(NetworkError("connection refused"), context)
        assert code == FailureCode.NETWORK_ERROR

    def test_captcha_detected_error(self, router: FallbackRouter, context: StepContext) -> None:
        code = router.classify(CaptchaDetectedError("reCAPTCHA"), context)
        assert code == FailureCode.CAPTCHA_DETECTED

    def test_auth_required_error(self, router: FallbackRouter, context: StepContext) -> None:
        code = router.classify(AuthRequiredError("login needed"), context)
        assert code == FailureCode.AUTH_REQUIRED


# ── Test: Heuristic Classification (Generic Exceptions) ──


class TestClassifyGenericExceptions:
    """Generic exceptions are classified via message heuristics and page state."""

    def test_timeout_message_maps_to_network_error(
        self, router: FallbackRouter, context: StepContext
    ) -> None:
        """Error message containing 'timeout' → NETWORK_ERROR."""
        code = router.classify(Exception("connection timeout after 30s"), context)
        assert code == FailureCode.NETWORK_ERROR

    def test_captcha_message_maps_to_captcha_detected(
        self, router: FallbackRouter, context: StepContext
    ) -> None:
        """Error message containing 'captcha' → CAPTCHA_DETECTED."""
        code = router.classify(Exception("detected captcha on page"), context)
        assert code == FailureCode.CAPTCHA_DETECTED

    def test_challenge_message_maps_to_captcha_detected(
        self, router: FallbackRouter, context: StepContext
    ) -> None:
        """Error message containing 'challenge' → CAPTCHA_DETECTED."""
        code = router.classify(Exception("security challenge required"), context)
        assert code == FailureCode.CAPTCHA_DETECTED

    def test_generic_exception_defaults_to_selector_not_found(
        self, router: FallbackRouter, context: StepContext
    ) -> None:
        """A plain generic exception defaults to SELECTOR_NOT_FOUND."""
        code = router.classify(ValueError("something broke"), context)
        assert code == FailureCode.SELECTOR_NOT_FOUND

    def test_case_insensitive_heuristic(
        self, router: FallbackRouter, context: StepContext
    ) -> None:
        """Message heuristics are case-insensitive."""
        code = router.classify(RuntimeError("TIMEOUT while waiting"), context)
        assert code == FailureCode.NETWORK_ERROR


# ── Test: Context-Aware Classification ───────────────


class TestClassifyContextAware:
    """Context signals (page state, attempt count) influence classification."""

    def test_page_has_captcha_overrides_default(self, router: FallbackRouter) -> None:
        """When page_state.has_captcha is True, generic error → CAPTCHA_DETECTED."""
        ctx = _make_context(has_captcha=True)
        code = router.classify(RuntimeError("unknown error"), ctx)
        assert code == FailureCode.CAPTCHA_DETECTED

    def test_page_has_popup_maps_to_not_interactable(self, router: FallbackRouter) -> None:
        """When page_state.has_popup is True, generic error → NOT_INTERACTABLE."""
        ctx = _make_context(has_popup=True)
        code = router.classify(RuntimeError("unknown error"), ctx)
        assert code == FailureCode.NOT_INTERACTABLE

    def test_captcha_takes_precedence_over_popup(self, router: FallbackRouter) -> None:
        """has_captcha is checked before has_popup in heuristic order."""
        ctx = _make_context(has_captcha=True, has_popup=True)
        code = router.classify(RuntimeError("unknown error"), ctx)
        assert code == FailureCode.CAPTCHA_DETECTED

    def test_high_attempt_reclassifies_selector_to_dynamic_layout(
        self, router: FallbackRouter,
    ) -> None:
        """SELECTOR_NOT_FOUND at high attempt count → DYNAMIC_LAYOUT."""
        ctx = _make_context(attempt=_DYNAMIC_LAYOUT_ATTEMPT_THRESHOLD)
        code = router.classify(SelectorNotFoundError("missing"), ctx)
        assert code == FailureCode.DYNAMIC_LAYOUT

    def test_low_attempt_keeps_selector_not_found(
        self, router: FallbackRouter,
    ) -> None:
        """SELECTOR_NOT_FOUND below threshold stays as-is."""
        ctx = _make_context(attempt=_DYNAMIC_LAYOUT_ATTEMPT_THRESHOLD - 1)
        code = router.classify(SelectorNotFoundError("missing"), ctx)
        assert code == FailureCode.SELECTOR_NOT_FOUND

    def test_reclassification_only_applies_to_selector_not_found(
        self, router: FallbackRouter,
    ) -> None:
        """High attempt count does not reclassify NETWORK_ERROR."""
        ctx = _make_context(attempt=10)
        code = router.classify(NetworkError("timeout"), ctx)
        assert code == FailureCode.NETWORK_ERROR

    def test_generic_exception_with_high_attempts_becomes_dynamic_layout(
        self, router: FallbackRouter,
    ) -> None:
        """Generic exception → SELECTOR_NOT_FOUND → DYNAMIC_LAYOUT at high attempts."""
        ctx = _make_context(attempt=_DYNAMIC_LAYOUT_ATTEMPT_THRESHOLD)
        code = router.classify(ValueError("something broke"), ctx)
        assert code == FailureCode.DYNAMIC_LAYOUT


# ── Test: Route → RecoveryPlan ───────────────────────


class TestRoute:
    """Each failure code routes to the correct recovery strategy and tier."""

    def test_selector_not_found_routes_to_escalate_llm(self, router: FallbackRouter) -> None:
        plan = router.route(FailureCode.SELECTOR_NOT_FOUND)
        assert plan.strategy == "escalate_llm"
        assert plan.tier == 1
        assert plan.params == {"mode": "select"}

    def test_not_interactable_routes_to_retry_with_scroll(self, router: FallbackRouter) -> None:
        plan = router.route(FailureCode.NOT_INTERACTABLE)
        assert plan.strategy == "retry"
        assert plan.tier == 1
        assert plan.params["scroll"] is True
        assert plan.params["wait_ms"] == 1000

    def test_state_not_changed_routes_to_retry(self, router: FallbackRouter) -> None:
        plan = router.route(FailureCode.STATE_NOT_CHANGED)
        assert plan.strategy == "retry"
        assert plan.tier == 1
        assert plan.params["wait_ms"] == 2000

    def test_visual_ambiguity_routes_to_vision(self, router: FallbackRouter) -> None:
        plan = router.route(FailureCode.VISUAL_AMBIGUITY)
        assert plan.strategy == "escalate_vision"
        assert plan.tier == 2
        assert plan.params == {"mode": "detect"}

    def test_network_error_routes_to_retry(self, router: FallbackRouter) -> None:
        plan = router.route(FailureCode.NETWORK_ERROR)
        assert plan.strategy == "retry"
        assert plan.tier == 1
        assert plan.params["wait_ms"] == 3000

    def test_queue_detected_routes_to_retry(self, router: FallbackRouter) -> None:
        plan = router.route(FailureCode.QUEUE_DETECTED)
        assert plan.strategy == "retry"
        assert plan.tier == 1
        assert plan.params["wait_ms"] == 5000

    def test_captcha_detected_routes_to_human_handoff(self, router: FallbackRouter) -> None:
        plan = router.route(FailureCode.CAPTCHA_DETECTED)
        assert plan.strategy == "human_handoff"
        assert plan.tier == 3
        assert plan.params == {"type": "captcha"}

    def test_auth_required_routes_to_human_handoff(self, router: FallbackRouter) -> None:
        plan = router.route(FailureCode.AUTH_REQUIRED)
        assert plan.strategy == "human_handoff"
        assert plan.tier == 3
        assert plan.params == {"type": "auth"}

    def test_dynamic_layout_routes_to_escalate_llm(self, router: FallbackRouter) -> None:
        plan = router.route(FailureCode.DYNAMIC_LAYOUT)
        assert plan.strategy == "escalate_llm"
        assert plan.tier == 2
        assert plan.params["mode"] == "plan"
        assert plan.params["re_extract"] is True

    def test_all_failure_codes_have_routes(self, router: FallbackRouter) -> None:
        """Every FailureCode has a corresponding route entry."""
        for code in FailureCode:
            plan = router.route(code)
            assert isinstance(plan, RecoveryPlan)
            assert plan.strategy in {"retry", "escalate_llm", "escalate_vision", "human_handoff", "skip"}
            assert plan.tier in {1, 2, 3}


# ── Test: Escalation Chains ─────────────────────────


class TestEscalationChain:
    """Escalation chains are ordered cheapest → most expensive."""

    def test_chain_for_selector_not_found(self, router: FallbackRouter) -> None:
        chain = router.get_escalation_chain(FailureCode.SELECTOR_NOT_FOUND)
        assert len(chain) >= 3
        # First entry is cheapest (retry), last is most expensive (human_handoff).
        assert chain[0].strategy == "retry"
        assert chain[-1].strategy == "human_handoff"

    def test_chain_for_captcha_is_immediate_handoff(self, router: FallbackRouter) -> None:
        chain = router.get_escalation_chain(FailureCode.CAPTCHA_DETECTED)
        assert len(chain) == 1
        assert chain[0].strategy == "human_handoff"

    def test_chain_tiers_are_non_decreasing(self, router: FallbackRouter) -> None:
        """Within each escalation chain, tiers never decrease."""
        for code in FailureCode:
            chain = router.get_escalation_chain(code)
            for i in range(1, len(chain)):
                assert chain[i].tier >= chain[i - 1].tier, (
                    f"Tier decreased in chain for {code}: "
                    f"tier {chain[i - 1].tier} → {chain[i].tier}"
                )

    def test_chain_returns_copy(self, router: FallbackRouter) -> None:
        """get_escalation_chain returns a copy, not a mutable reference."""
        chain1 = router.get_escalation_chain(FailureCode.SELECTOR_NOT_FOUND)
        chain2 = router.get_escalation_chain(FailureCode.SELECTOR_NOT_FOUND)
        assert chain1 == chain2
        assert chain1 is not chain2

    def test_all_failure_codes_have_chains(self, router: FallbackRouter) -> None:
        """Every FailureCode has at least one entry in its escalation chain."""
        for code in FailureCode:
            chain = router.get_escalation_chain(code)
            assert len(chain) >= 1


# ── Test: should_escalate ────────────────────────────


class TestShouldEscalate:
    """should_escalate decides when to move to the next recovery tier."""

    def test_first_attempt_does_not_escalate(self, router: FallbackRouter) -> None:
        assert router.should_escalate(FailureCode.SELECTOR_NOT_FOUND, attempt=0) is False

    def test_second_attempt_escalates(self, router: FallbackRouter) -> None:
        assert router.should_escalate(FailureCode.SELECTOR_NOT_FOUND, attempt=1) is True

    def test_captcha_always_escalates(self, router: FallbackRouter) -> None:
        """CAPTCHA_DETECTED escalates even at attempt 0."""
        assert router.should_escalate(FailureCode.CAPTCHA_DETECTED, attempt=0) is True

    def test_auth_always_escalates(self, router: FallbackRouter) -> None:
        """AUTH_REQUIRED escalates even at attempt 0."""
        assert router.should_escalate(FailureCode.AUTH_REQUIRED, attempt=0) is True

    def test_does_not_escalate_beyond_chain_length(self, router: FallbackRouter) -> None:
        """When attempt >= chain length, should_escalate returns False."""
        chain_len = len(router.get_escalation_chain(FailureCode.NETWORK_ERROR))
        assert router.should_escalate(FailureCode.NETWORK_ERROR, attempt=chain_len) is False

    def test_escalates_within_chain_length(self, router: FallbackRouter) -> None:
        """When attempt < chain length and > 0, should_escalate returns True."""
        chain_len = len(router.get_escalation_chain(FailureCode.NOT_INTERACTABLE))
        if chain_len > 1:
            assert router.should_escalate(FailureCode.NOT_INTERACTABLE, attempt=1) is True


# ── Test: Statistics Tracking ────────────────────────


class TestStatistics:
    """record_outcome and get_stats track failure/recovery metrics."""

    def test_initial_stats_are_empty(self, router: FallbackRouter) -> None:
        assert router.get_stats() == {}

    def test_record_single_recovery(self, router: FallbackRouter) -> None:
        router.record_outcome(FailureCode.SELECTOR_NOT_FOUND, recovered=True)
        stats = router.get_stats()
        entry = stats["SelectorNotFound"]
        assert entry["total"] == 1
        assert entry["recovered"] == 1
        assert entry["failed"] == 0
        assert entry["recovery_rate"] == 1.0

    def test_record_single_failure(self, router: FallbackRouter) -> None:
        router.record_outcome(FailureCode.CAPTCHA_DETECTED, recovered=False)
        stats = router.get_stats()
        entry = stats["CaptchaDetected"]
        assert entry["total"] == 1
        assert entry["recovered"] == 0
        assert entry["failed"] == 1
        assert entry["recovery_rate"] == 0.0

    def test_mixed_outcomes_compute_rate(self, router: FallbackRouter) -> None:
        """Recovery rate is correctly computed from mixed outcomes."""
        router.record_outcome(FailureCode.NETWORK_ERROR, recovered=True)
        router.record_outcome(FailureCode.NETWORK_ERROR, recovered=True)
        router.record_outcome(FailureCode.NETWORK_ERROR, recovered=False)
        stats = router.get_stats()
        entry = stats["NetworkError"]
        assert entry["total"] == 3
        assert entry["recovered"] == 2
        assert entry["failed"] == 1
        assert abs(entry["recovery_rate"] - 2.0 / 3.0) < 1e-9

    def test_multiple_failure_codes_tracked_independently(
        self, router: FallbackRouter
    ) -> None:
        router.record_outcome(FailureCode.SELECTOR_NOT_FOUND, recovered=True)
        router.record_outcome(FailureCode.NETWORK_ERROR, recovered=False)
        stats = router.get_stats()
        assert "SelectorNotFound" in stats
        assert "NetworkError" in stats
        assert stats["SelectorNotFound"]["recovered"] == 1
        assert stats["NetworkError"]["failed"] == 1

    def test_stats_use_failure_code_value_as_key(self, router: FallbackRouter) -> None:
        """Stats dictionary keys are FailureCode.value strings, not enum members."""
        router.record_outcome(FailureCode.AUTH_REQUIRED, recovered=False)
        stats = router.get_stats()
        assert "AuthRequired" in stats
        # Ensure it's a plain string key.
        for key in stats:
            assert isinstance(key, str)


# ── Test: Route Table Completeness ───────────────────


class TestRouteTableCompleteness:
    """Verify the static routing and escalation tables are well-formed."""

    def test_every_failure_code_in_route_table(self) -> None:
        """_ROUTE_TABLE has an entry for every FailureCode."""
        for code in FailureCode:
            assert code in _ROUTE_TABLE, f"Missing route for {code}"

    def test_every_failure_code_in_escalation_chains(self) -> None:
        """_ESCALATION_CHAINS has an entry for every FailureCode."""
        for code in FailureCode:
            assert code in _ESCALATION_CHAINS, f"Missing escalation chain for {code}"

    def test_escalation_chains_end_with_human_handoff_or_retry(self) -> None:
        """Every chain's last entry is human_handoff or retry (terminal strategies)."""
        terminal = {"human_handoff", "retry"}
        for code, chain in _ESCALATION_CHAINS.items():
            assert chain[-1].strategy in terminal, (
                f"Chain for {code} ends with non-terminal strategy: {chain[-1].strategy}"
            )


# ── Test: End-to-End Classify → Route Flow ───────────


class TestEndToEndFlow:
    """Integration-like tests verifying classify → route → escalation chain."""

    def test_selector_error_full_flow(self, router: FallbackRouter) -> None:
        ctx = _make_context(attempt=0)
        code = router.classify(SelectorNotFoundError("no .btn"), ctx)
        plan = router.route(code)
        chain = router.get_escalation_chain(code)

        assert code == FailureCode.SELECTOR_NOT_FOUND
        assert plan.strategy == "escalate_llm"
        assert len(chain) >= 3

    def test_high_attempt_selector_full_flow(self, router: FallbackRouter) -> None:
        """High attempt count reclassifies to DYNAMIC_LAYOUT and routes accordingly."""
        ctx = _make_context(attempt=5)
        code = router.classify(SelectorNotFoundError("no .btn"), ctx)
        plan = router.route(code)

        assert code == FailureCode.DYNAMIC_LAYOUT
        assert plan.strategy == "escalate_llm"
        assert plan.params["re_extract"] is True

    def test_captcha_page_state_full_flow(self, router: FallbackRouter) -> None:
        """Generic error on a page with captcha → CAPTCHA → human handoff."""
        ctx = _make_context(has_captcha=True)
        code = router.classify(RuntimeError("something failed"), ctx)
        plan = router.route(code)

        assert code == FailureCode.CAPTCHA_DETECTED
        assert plan.strategy == "human_handoff"
        assert plan.params["type"] == "captcha"

    def test_popup_blocking_full_flow(self, router: FallbackRouter) -> None:
        """Generic error on a page with popup → NOT_INTERACTABLE → retry with scroll."""
        ctx = _make_context(has_popup=True)
        code = router.classify(RuntimeError("click failed"), ctx)
        plan = router.route(code)

        assert code == FailureCode.NOT_INTERACTABLE
        assert plan.strategy == "retry"
        assert plan.params["scroll"] is True
