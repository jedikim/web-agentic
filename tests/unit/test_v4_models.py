"""Unit tests for v4 models: SiteProfile, Bundle, Failure, MaturityState."""

from __future__ import annotations

import json

import pytest

from src.models.bundle import GeneratedBundle, StrategyAssignment, ValidationResult
from src.models.failure import FailureEvidence, FailureType, RemediationAction
from src.models.maturity import MaturityState
from src.models.site_profile import (
    ContentPattern,
    DOMComplexity,
    ObstaclePattern,
    SiteProfile,
    VisualStructure,
)

# ── SiteProfile ──


def test_site_profile_defaults():
    sp = SiteProfile()
    assert sp.domain == ""
    assert sp.purpose == ""
    assert sp.language == "en"
    assert sp.region == "US"
    assert sp.recon_version == 1
    assert sp.dom_hash == ""
    assert sp.is_spa is False
    assert sp.iframe_count == 0
    assert sp.image_density == "low"
    assert sp.obstacle_frequency == "none"
    assert sp.hover_dependent_menus is False
    assert sp.websocket_usage is False
    # Nested defaults
    assert sp.dom_complexity.total_elements == 0
    assert sp.dom_complexity.aria_coverage == 0.0
    assert sp.visual_structure.layout_type == "responsive"
    assert sp.visual_structure.has_sticky_header is False
    assert sp.canvas_usage.has_canvas is False
    assert sp.navigation.menu_depth == 1
    # Lists should be empty
    assert sp.content_types == []
    assert sp.obstacles == []
    assert sp.interaction_patterns == []
    assert sp.api_endpoints == []
    assert sp.thumbnail_structures == []


def test_site_profile_to_dict_and_back():
    sp = SiteProfile(
        domain="example.com",
        purpose="ecommerce",
        dom_complexity=DOMComplexity(total_elements=500, max_depth=12),
        visual_structure=VisualStructure(layout_type="fixed", has_sticky_header=True),
        obstacles=[ObstaclePattern(type="cookie_consent", dismiss_method="click_close")],
        content_types=[ContentPattern(page_type="home", url_pattern="/")],
        is_spa=True,
        framework="react",
    )
    d = sp.to_dict()
    assert d["domain"] == "example.com"
    assert d["purpose"] == "ecommerce"
    assert isinstance(d["created_at"], str)
    assert isinstance(d["last_recon_at"], str)
    assert d["dom_complexity"]["total_elements"] == 500
    assert d["visual_structure"]["has_sticky_header"] is True
    assert len(d["obstacles"]) == 1
    assert d["obstacles"][0]["type"] == "cookie_consent"

    # Roundtrip
    sp2 = SiteProfile.from_dict(d)
    assert sp2.domain == "example.com"
    assert sp2.purpose == "ecommerce"
    assert sp2.dom_complexity.total_elements == 500
    assert sp2.dom_complexity.max_depth == 12
    assert sp2.visual_structure.has_sticky_header is True
    assert sp2.is_spa is True
    assert sp2.framework == "react"
    assert len(sp2.obstacles) == 1
    assert sp2.obstacles[0].type == "cookie_consent"
    assert len(sp2.content_types) == 1
    assert sp2.content_types[0].page_type == "home"


def test_site_profile_from_json():
    data = {
        "domain": "test.org",
        "purpose": "news",
        "language": "ko",
        "region": "KR",
        "created_at": "2026-01-15T10:30:00",
        "last_recon_at": "2026-01-15T10:30:00",
        "dom_complexity": {"total_elements": 200, "max_depth": 8},
        "navigation": {"menu_depth": 3, "has_search": True},
    }
    json_str = json.dumps(data)
    sp = SiteProfile.from_json(json_str)
    assert sp.domain == "test.org"
    assert sp.language == "ko"
    assert sp.region == "KR"
    assert sp.dom_complexity.total_elements == 200
    assert sp.navigation.menu_depth == 3
    assert sp.navigation.has_search is True
    # Verify datetime parsed
    assert sp.created_at.year == 2026
    assert sp.created_at.month == 1


def test_site_profile_json_roundtrip():
    sp = SiteProfile(domain="round.trip", purpose="portal")
    json_str = sp.to_json()
    sp2 = SiteProfile.from_json(json_str)
    assert sp2.domain == sp.domain
    assert sp2.purpose == sp.purpose


def test_compute_dom_hash():
    sp = SiteProfile(
        dom_complexity=DOMComplexity(total_elements=100, max_depth=5),
        framework="vue",
        is_spa=True,
    )
    h1 = sp.compute_dom_hash()
    assert isinstance(h1, str)
    assert len(h1) == 16

    # Same inputs produce same hash
    h2 = sp.compute_dom_hash()
    assert h1 == h2

    # Different inputs produce different hash
    sp2 = SiteProfile(
        dom_complexity=DOMComplexity(total_elements=200, max_depth=5),
        framework="vue",
        is_spa=True,
    )
    h3 = sp2.compute_dom_hash()
    assert h3 != h1


def test_compute_dom_hash_deterministic_across_instances():
    kwargs = {
        "dom_complexity": DOMComplexity(total_elements=42, max_depth=3),
        "framework": "angular",
        "is_spa": False,
    }
    sp_a = SiteProfile(**kwargs)
    sp_b = SiteProfile(**kwargs)
    assert sp_a.compute_dom_hash() == sp_b.compute_dom_hash()


# ── Bundle models ──


def test_generated_bundle_defaults():
    b = GeneratedBundle()
    assert b.workflow_dsl == {}
    assert b.python_macro is None
    assert b.ts_macro is None
    assert b.prompts == {}
    assert b.strategy == "dom_only"
    assert b.dependencies == []
    assert b.selector_patches == []
    assert b.version == 1


def test_generated_bundle_custom():
    b = GeneratedBundle(
        workflow_dsl={"steps": [{"action": "click"}]},
        python_macro="def run(): pass",
        strategy="vlm_only",
        version=3,
        dependencies=["playwright"],
    )
    assert b.workflow_dsl["steps"][0]["action"] == "click"
    assert b.python_macro == "def run(): pass"
    assert b.strategy == "vlm_only"
    assert b.version == 3
    assert "playwright" in b.dependencies


def test_validation_result_overall_true():
    vr = ValidationResult(
        dsl_ok=True,
        macro_ok=True,
        selector_ok=True,
        har_replay_ok=True,
        canary_ok=True,
        trace_ok=True,
    )
    assert vr.overall is True


@pytest.mark.parametrize(
    "false_field",
    ["dsl_ok", "macro_ok", "selector_ok", "har_replay_ok", "canary_ok", "trace_ok"],
)
def test_validation_result_overall_false(false_field: str):
    kwargs = {
        "dsl_ok": True,
        "macro_ok": True,
        "selector_ok": True,
        "har_replay_ok": True,
        "canary_ok": True,
        "trace_ok": True,
    }
    kwargs[false_field] = False
    vr = ValidationResult(**kwargs)
    assert vr.overall is False


def test_validation_result_defaults_overall_false():
    vr = ValidationResult()
    assert vr.overall is False
    assert vr.errors == []
    assert vr.trace_path is None


def test_strategy_assignment():
    sa = StrategyAssignment(
        page_type="product_detail",
        url_pattern="/product/*",
        strategy="dom_with_objdet_backup",
        tools_needed=["playwright", "yolo"],
    )
    assert sa.page_type == "product_detail"
    assert sa.url_pattern == "/product/*"
    assert sa.strategy == "dom_with_objdet_backup"
    assert "yolo" in sa.tools_needed


def test_strategy_assignment_defaults():
    sa = StrategyAssignment()
    assert sa.page_type == ""
    assert sa.url_pattern == ""
    assert sa.strategy == "dom_only"
    assert sa.tools_needed == []


# ── Failure models ──


def test_failure_type_enum():
    assert FailureType.SELECTOR_NOT_FOUND.value == "selector_not_found"
    assert FailureType.TIMEOUT.value == "timeout"
    assert FailureType.CAPTCHA.value == "captcha"
    assert FailureType.UNKNOWN.value == "unknown"
    assert FailureType.SITE_CHANGED.value == "site_changed"
    # All enum members
    assert len(FailureType) == 11


def test_remediation_action_enum():
    assert RemediationAction.FIX_SELECTOR.value == "fix_selector"
    assert RemediationAction.FULL_RECON.value == "full_recon"
    assert RemediationAction.HUMAN_HANDOFF.value == "human_handoff"
    assert len(RemediationAction) == 6


@pytest.mark.parametrize(
    ("failure_type", "expected_remediation"),
    [
        (FailureType.SELECTOR_NOT_FOUND, RemediationAction.FIX_SELECTOR),
        (FailureType.SELECTOR_STALE, RemediationAction.FIX_SELECTOR),
        (FailureType.TIMEOUT, RemediationAction.ADD_WAIT),
        (FailureType.OBSTACLE_BLOCKED, RemediationAction.FIX_OBSTACLE),
        (FailureType.NAVIGATION_FAILED, RemediationAction.CHANGE_STRATEGY),
        (FailureType.VERIFICATION_FAILED, RemediationAction.CHANGE_STRATEGY),
        (FailureType.STRATEGY_MISMATCH, RemediationAction.CHANGE_STRATEGY),
        (FailureType.SITE_CHANGED, RemediationAction.FULL_RECON),
        (FailureType.AUTH_REQUIRED, RemediationAction.HUMAN_HANDOFF),
        (FailureType.CAPTCHA, RemediationAction.HUMAN_HANDOFF),
        (FailureType.UNKNOWN, RemediationAction.HUMAN_HANDOFF),
    ],
)
def test_failure_evidence_classify_remediation(
    failure_type: FailureType,
    expected_remediation: RemediationAction,
):
    fe = FailureEvidence(failure_type=failure_type)
    result = fe.classify_remediation()
    assert result == expected_remediation
    assert fe.remediation == expected_remediation


def test_remediation_mapping_mutates_field():
    fe = FailureEvidence(failure_type=FailureType.TIMEOUT)
    assert fe.remediation == RemediationAction.HUMAN_HANDOFF  # default
    fe.classify_remediation()
    assert fe.remediation == RemediationAction.ADD_WAIT  # updated


def test_failure_evidence_defaults():
    fe = FailureEvidence()
    assert fe.failure_type == FailureType.UNKNOWN
    assert fe.error_message == ""
    assert fe.selector is None
    assert fe.url == ""
    assert fe.screenshot_path is None
    assert fe.dom_snapshot is None
    assert fe.extra == {}


# ── MaturityState ──


def test_cold_initial():
    ms = MaturityState(domain="new-site.com")
    assert ms.stage == "cold"
    assert ms.total_runs == 0
    assert ms.evaluate_stage() == "cold"


def test_warm_transition():
    ms = MaturityState(
        domain="warming.com",
        total_runs=5,
        recent_success_rate=0.75,
        consecutive_successes=3,
        llm_calls_last_10=5,
    )
    assert ms.evaluate_stage() == "warm"
    ms.update_stage()
    assert ms.stage == "warm"


def test_warm_boundary():
    ms = MaturityState(
        domain="edge.com",
        total_runs=3,
        recent_success_rate=0.70,
        consecutive_successes=2,
        llm_calls_last_10=3,
    )
    assert ms.evaluate_stage() == "warm"

    # Below boundary
    ms.recent_success_rate = 0.69
    assert ms.evaluate_stage() == "cold"


def test_hot_transition():
    ms = MaturityState(
        domain="mature.com",
        total_runs=50,
        recent_success_rate=0.98,
        consecutive_successes=15,
        llm_calls_last_10=0,
    )
    assert ms.evaluate_stage() == "hot"
    ms.update_stage()
    assert ms.stage == "hot"


def test_hot_requires_all_conditions():
    # High success rate but still uses LLM
    ms = MaturityState(
        domain="almost.com",
        total_runs=50,
        recent_success_rate=0.98,
        consecutive_successes=15,
        llm_calls_last_10=1,
    )
    assert ms.evaluate_stage() == "warm"  # not hot because llm_calls > 0

    # No LLM calls but not enough consecutive successes
    ms2 = MaturityState(
        domain="almost2.com",
        total_runs=50,
        recent_success_rate=0.98,
        consecutive_successes=9,
        llm_calls_last_10=0,
    )
    assert ms2.evaluate_stage() == "warm"  # not hot because consecutive < 10

    # Not enough success rate
    ms3 = MaturityState(
        domain="almost3.com",
        total_runs=50,
        recent_success_rate=0.94,
        consecutive_successes=15,
        llm_calls_last_10=0,
    )
    assert ms3.evaluate_stage() == "warm"  # not hot because rate < 0.95


def test_record_run_updates_metrics():
    ms = MaturityState(domain="tracker.com")
    assert ms.total_runs == 0

    ms.record_run(success=True, llm_calls=2)
    assert ms.total_runs == 1
    assert ms.consecutive_successes == 1
    assert ms.llm_calls_last_10 == 2
    assert ms.recent_success_rate > 0

    ms.record_run(success=True, llm_calls=1)
    assert ms.total_runs == 2
    assert ms.consecutive_successes == 2

    ms.record_run(success=False, llm_calls=0)
    assert ms.total_runs == 3
    assert ms.consecutive_successes == 0  # reset on failure


def test_record_run_success_rate_increases():
    ms = MaturityState(domain="ema.com", recent_success_rate=0.0)
    for _ in range(20):
        ms.record_run(success=True, llm_calls=0)
    assert ms.recent_success_rate > 0.5


def test_cold_regression():
    ms = MaturityState(
        domain="regress.com",
        total_runs=10,
        recent_success_rate=0.80,
        consecutive_successes=5,
        llm_calls_last_10=2,
    )
    assert ms.evaluate_stage() == "warm"

    # Simulate many failures dropping success rate
    for _ in range(30):
        ms.record_run(success=False, llm_calls=3)

    assert ms.recent_success_rate < 0.70
    assert ms.stage == "cold"
    assert ms.consecutive_successes == 0


def test_record_run_triggers_stage_update():
    ms = MaturityState(domain="auto.com")
    assert ms.stage == "cold"

    # Enough successful runs to become warm
    ms.total_runs = 2
    ms.recent_success_rate = 0.80
    ms.record_run(success=True, llm_calls=1)
    # total_runs is now 3, rate stays high
    assert ms.stage == "warm"
