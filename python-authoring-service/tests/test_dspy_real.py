"""
Tests for real DSPy programs with fallback mode (no LLM configured).

Tests cover:
- IntentToWorkflow program (rule-based fallback)
- IntentToPolicy program (rule-based fallback)
- PatchPlanner program (rule-based fallback via PatchGenerator)
- JSON parsing and schema validation
- Error handling for invalid inputs
- API endpoint integration
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.dspy_programs.intent_to_policy import (
    IntentToPolicyProgram,
    _build_policy_from_parsed,
    _extract_constraints_from_text,
    _extract_preferences_from_text,
    compile_intent_to_policy,
)
from app.dspy_programs.intent_to_workflow import (
    IntentToWorkflowProgram,
    _build_actions_from_parsed,
    _build_selectors_from_parsed,
    _build_workflow_from_parsed,
    _parse_json_safe,
    _parse_procedure_to_steps,
    compile_intent_to_recipe,
)
from app.dspy_programs.patch_planner import (
    PatchPlannerProgram,
    _build_patch_ops_from_parsed,
    plan_patch_for_failure,
)
from app.dspy_programs.signatures import (
    IntentToPolicySignature,
    IntentToWorkflowSignature,
    PatchPlannerSignature,
)
from app.main import app
from app.schemas.patch_schema import PlanPatchRequest
from app.schemas.recipe_schema import CompileIntentRequest


# ---------------------------------------------------------------------------
# DSPy Signature tests
# ---------------------------------------------------------------------------


class TestSignatures:
    """Verify DSPy signatures are properly defined."""

    def test_intent_to_workflow_signature_fields(self):
        fields = IntentToWorkflowSignature.model_fields
        assert "goal" in fields
        assert "procedure" in fields
        assert "domain" in fields
        assert "context" in fields
        assert "workflow_json" in fields
        assert "actions_json" in fields
        assert "selectors_json" in fields

    def test_intent_to_policy_signature_fields(self):
        fields = IntentToPolicySignature.model_fields
        assert "goal" in fields
        assert "constraints" in fields
        assert "preferences" in fields
        assert "policy_json" in fields

    def test_patch_planner_signature_fields(self):
        fields = PatchPlannerSignature.model_fields
        assert "step_id" in fields
        assert "error_type" in fields
        assert "url" in fields
        assert "failed_selector" in fields
        assert "dom_snippet" in fields
        assert "patch_json" in fields


# ---------------------------------------------------------------------------
# DSPy Module instantiation tests
# ---------------------------------------------------------------------------


class TestDSPyModules:
    """Verify DSPy modules can be instantiated."""

    def test_intent_to_workflow_program_creates(self):
        program = IntentToWorkflowProgram()
        assert program.generate is not None

    def test_intent_to_policy_program_creates(self):
        program = IntentToPolicyProgram()
        assert program.generate is not None

    def test_patch_planner_program_creates(self):
        program = PatchPlannerProgram()
        assert program.generate is not None


# ---------------------------------------------------------------------------
# JSON parsing tests
# ---------------------------------------------------------------------------


class TestJsonParsing:
    """Test the JSON parsing utility used across programs."""

    def test_parse_valid_json(self):
        result = _parse_json_safe('{"key": "value"}', "test")
        assert result == {"key": "value"}

    def test_parse_json_with_code_fence(self):
        text = '```json\n{"key": "value"}\n```'
        result = _parse_json_safe(text, "test")
        assert result == {"key": "value"}

    def test_parse_json_with_plain_code_fence(self):
        text = '```\n{"key": "value"}\n```'
        result = _parse_json_safe(text, "test")
        assert result == {"key": "value"}

    def test_parse_invalid_json_returns_none(self):
        result = _parse_json_safe("not json at all", "test")
        assert result is None

    def test_parse_empty_string_returns_none(self):
        result = _parse_json_safe("", "test")
        assert result is None

    def test_parse_whitespace_returns_none(self):
        result = _parse_json_safe("   ", "test")
        assert result is None

    def test_parse_json_array(self):
        result = _parse_json_safe('[1, 2, 3]', "test")
        assert result == [1, 2, 3]


# ---------------------------------------------------------------------------
# IntentToWorkflow fallback tests
# ---------------------------------------------------------------------------


class TestIntentToWorkflowFallback:
    """Test rule-based fallback for intent-to-workflow compilation."""

    @pytest.mark.asyncio
    async def test_basic_goal_generates_goto_and_checkpoint(self):
        request = CompileIntentRequest(
            requestId="req-100", goal="Book a flight", domain="airline.com"
        )
        result = await compile_intent_to_recipe(request)
        assert result.request_id == "req-100"
        assert result.workflow.id == "airline.com_flow"
        # Must have at least goto + checkpoint
        ops = [s.op for s in result.workflow.steps]
        assert "goto" in ops
        assert "checkpoint" in ops
        # First step should be goto with domain
        assert result.workflow.steps[0].op == "goto"
        assert "airline.com" in result.workflow.steps[0].args["url"]

    @pytest.mark.asyncio
    async def test_default_domain_fallback(self):
        request = CompileIntentRequest(requestId="req-101", goal="Do something")
        result = await compile_intent_to_recipe(request)
        assert result.workflow.id == "default_flow"
        assert "example.com" in result.workflow.steps[0].args["url"]

    @pytest.mark.asyncio
    async def test_procedure_parsing_generates_steps(self):
        request = CompileIntentRequest(
            requestId="req-102",
            goal="Search for products",
            domain="shop.com",
            procedure="1. Go to shop.com\n2. Click the search box\n3. Type 'laptop'\n4. Click search button\n5. Extract the results",
        )
        result = await compile_intent_to_recipe(request)
        assert len(result.workflow.steps) > 2  # More than just goto + checkpoint
        ops = [s.op for s in result.workflow.steps]
        assert "goto" in ops or "act_cached" in ops

    @pytest.mark.asyncio
    async def test_procedure_with_url(self):
        request = CompileIntentRequest(
            requestId="req-103",
            goal="Check weather",
            procedure="1. Navigate to https://weather.com\n2. Extract the temperature",
        )
        result = await compile_intent_to_recipe(request)
        steps = result.workflow.steps
        # Should find the URL in a goto step
        goto_steps = [s for s in steps if s.op == "goto"]
        assert len(goto_steps) >= 1

    @pytest.mark.asyncio
    async def test_response_has_valid_schema(self):
        request = CompileIntentRequest(
            requestId="req-104", goal="Test recipe", domain="test.com"
        )
        result = await compile_intent_to_recipe(request)
        # Verify all fields are present and valid types
        assert isinstance(result.workflow.steps, list)
        assert isinstance(result.actions, dict)
        assert isinstance(result.selectors, dict)
        assert isinstance(result.policies, dict)
        assert isinstance(result.fingerprints, dict)

    @pytest.mark.asyncio
    async def test_procedure_generates_actions_for_act_steps(self):
        request = CompileIntentRequest(
            requestId="req-105",
            goal="Fill a form",
            domain="form.com",
            procedure="1. Go to the page\n2. Click submit button\n3. Type email address",
        )
        result = await compile_intent_to_recipe(request)
        # Steps with target_key should produce actions
        act_steps = [s for s in result.workflow.steps if s.target_key]
        for step in act_steps:
            assert step.target_key in result.actions or step.target_key in result.selectors


# ---------------------------------------------------------------------------
# Workflow parsing helpers tests
# ---------------------------------------------------------------------------


class TestWorkflowParsingHelpers:
    """Test helper functions for building workflow from parsed JSON."""

    def test_build_workflow_from_parsed_valid(self):
        parsed = {
            "id": "my_flow",
            "steps": [
                {"id": "s1", "op": "goto", "args": {"url": "https://example.com"}},
                {"id": "s2", "op": "act_cached", "targetKey": "btn"},
            ],
        }
        workflow = _build_workflow_from_parsed(parsed, "example.com", "test")
        assert workflow.id == "my_flow"
        assert len(workflow.steps) == 2
        assert workflow.steps[0].op == "goto"
        assert workflow.steps[1].target_key == "btn"

    def test_build_workflow_skips_invalid_steps(self):
        parsed = {
            "steps": [
                {"id": "s1", "op": "goto"},
                {"invalid": True},  # missing id and op
                "not a dict",
                {"id": "s2"},  # missing op
            ],
        }
        workflow = _build_workflow_from_parsed(parsed, "default", "test")
        assert len(workflow.steps) == 1  # only s1

    def test_build_workflow_fallback_on_empty_steps(self):
        parsed = {"steps": []}
        workflow = _build_workflow_from_parsed(parsed, "default", "test")
        assert len(workflow.steps) >= 1  # at least goto

    def test_build_workflow_with_expectations(self):
        parsed = {
            "steps": [
                {
                    "id": "s1",
                    "op": "goto",
                    "expect": [
                        {"kind": "url_contains", "value": "/home"},
                        {"kind": "title_contains", "value": "Home"},
                    ],
                }
            ],
        }
        workflow = _build_workflow_from_parsed(parsed, "default", "test")
        assert workflow.steps[0].expect is not None
        assert len(workflow.steps[0].expect) == 2

    def test_build_actions_from_parsed(self):
        parsed = {
            "login_btn": {
                "instruction": "Click login",
                "preferred": {
                    "selector": "#login-btn",
                    "description": "Login button",
                    "method": "click",
                },
            }
        }
        actions = _build_actions_from_parsed(parsed)
        assert "login_btn" in actions
        assert actions["login_btn"].preferred.selector == "#login-btn"

    def test_build_actions_skips_invalid(self):
        parsed = {
            "valid": {"instruction": "test", "preferred": {"selector": "#x", "description": "x", "method": "click"}},
            "invalid": "not a dict",
        }
        actions = _build_actions_from_parsed(parsed)
        assert "valid" in actions
        assert "invalid" not in actions

    def test_build_selectors_from_parsed(self):
        parsed = {
            "search_box": {
                "primary": "#search",
                "fallbacks": [".search-input", "[name=q]"],
                "strategy": "css",
            }
        }
        selectors = _build_selectors_from_parsed(parsed)
        assert "search_box" in selectors
        assert selectors["search_box"].primary == "#search"
        assert len(selectors["search_box"].fallbacks) == 2


# ---------------------------------------------------------------------------
# Procedure parsing tests
# ---------------------------------------------------------------------------


class TestProcedureParsing:
    """Test step-by-step procedure parsing."""

    def test_parse_numbered_steps(self):
        procedure = "1. Go to the website\n2. Click login\n3. Type username"
        steps = _parse_procedure_to_steps(procedure, "test.com")
        assert len(steps) >= 3

    def test_parse_bullet_steps(self):
        procedure = "- Navigate to page\n- Click button\n- Extract data"
        steps = _parse_procedure_to_steps(procedure, "test.com")
        assert len(steps) >= 3

    def test_parse_recognizes_goto(self):
        procedure = "1. Go to the homepage"
        steps = _parse_procedure_to_steps(procedure, "test.com")
        assert any(s.op == "goto" for s in steps)

    def test_parse_recognizes_click(self):
        procedure = "1. Click the submit button"
        steps = _parse_procedure_to_steps(procedure, "test.com")
        assert any(s.op == "act_cached" for s in steps)

    def test_parse_recognizes_extract(self):
        procedure = "1. Extract the price list"
        steps = _parse_procedure_to_steps(procedure, "test.com")
        assert any(s.op == "extract" for s in steps)

    def test_parse_recognizes_wait(self):
        procedure = "1. Wait for the page to load"
        steps = _parse_procedure_to_steps(procedure, "test.com")
        assert any(s.op == "wait" for s in steps)

    def test_parse_empty_procedure(self):
        steps = _parse_procedure_to_steps("", "test.com")
        assert steps == []

    def test_parse_unrecognized_defaults_to_act(self):
        procedure = "1. Do something unusual"
        steps = _parse_procedure_to_steps(procedure, "test.com")
        assert len(steps) == 1
        assert steps[0].op == "act_cached"


# ---------------------------------------------------------------------------
# IntentToPolicy fallback tests
# ---------------------------------------------------------------------------


class TestIntentToPolicyFallback:
    """Test rule-based fallback for intent-to-policy compilation."""

    @pytest.mark.asyncio
    async def test_basic_goal_returns_default_policy(self):
        policies = await compile_intent_to_policy(goal="Pick best seat")
        assert "default_policy" in policies
        policy = policies["default_policy"]
        assert policy.pick in ("first", "argmax", "argmin")
        assert isinstance(policy.hard, list)
        assert isinstance(policy.score, list)
        assert isinstance(policy.tie_break, list)

    @pytest.mark.asyncio
    async def test_price_constraint_extracted(self):
        policies = await compile_intent_to_policy(goal="Find flights under $500")
        policy = policies["default_policy"]
        price_constraints = [c for c in policy.hard if c.field == "price"]
        assert len(price_constraints) >= 1
        assert price_constraints[0].op == "lte"

    @pytest.mark.asyncio
    async def test_cheapest_preference(self):
        policies = await compile_intent_to_policy(goal="Find the cheapest option")
        policy = policies["default_policy"]
        assert any("price_asc" in tb for tb in policy.tie_break)

    @pytest.mark.asyncio
    async def test_best_rated_preference(self):
        policies = await compile_intent_to_policy(goal="Find the best rated restaurant")
        policy = policies["default_policy"]
        assert any("rating" in tb for tb in policy.tie_break)

    @pytest.mark.asyncio
    async def test_structured_constraints(self):
        constraints = [
            {"field": "category", "op": "eq", "value": "electronics"},
        ]
        policies = await compile_intent_to_policy(
            goal="Filter products", constraints=constraints
        )
        policy = policies["default_policy"]
        assert any(c.field == "category" for c in policy.hard)

    @pytest.mark.asyncio
    async def test_dict_constraints(self):
        constraints = {"color": "red", "size": {"op": "gte", "value": 10}}
        policies = await compile_intent_to_policy(
            goal="Filter items", constraints=constraints
        )
        policy = policies["default_policy"]
        assert any(c.field == "color" for c in policy.hard)
        assert any(c.field == "size" for c in policy.hard)


# ---------------------------------------------------------------------------
# Policy parsing helpers tests
# ---------------------------------------------------------------------------


class TestPolicyParsingHelpers:
    """Test helper functions for building policy from parsed JSON."""

    def test_build_policy_from_valid_parsed(self):
        parsed = {
            "hard": [{"field": "price", "op": "lte", "value": 100}],
            "score": [{"when": {"field": "rating", "op": "gte", "value": 4}, "add": 10.0}],
            "tie_break": ["price_asc"],
            "pick": "argmin",
        }
        policy = _build_policy_from_parsed(parsed)
        assert len(policy.hard) == 1
        assert policy.hard[0].field == "price"
        assert len(policy.score) == 1
        assert policy.score[0].add == 10.0
        assert policy.tie_break == ["price_asc"]
        assert policy.pick == "argmin"

    def test_build_policy_with_invalid_pick(self):
        parsed = {"hard": [], "score": [], "tie_break": [], "pick": "invalid"}
        policy = _build_policy_from_parsed(parsed)
        assert policy.pick == "first"  # defaults to first

    def test_build_policy_with_missing_fields(self):
        parsed = {}
        policy = _build_policy_from_parsed(parsed)
        assert policy.hard == []
        assert policy.score == []
        assert policy.tie_break == ["label_asc"]
        assert policy.pick == "first"

    def test_build_policy_skips_invalid_conditions(self):
        parsed = {
            "hard": [
                {"field": "price", "op": "lte", "value": 100},
                {"missing_field": True},  # invalid
                "not a dict",
            ],
        }
        policy = _build_policy_from_parsed(parsed)
        assert len(policy.hard) == 1

    def test_extract_constraints_price_under(self):
        constraints = _extract_constraints_from_text("Find flights under $300")
        assert any(c.field == "price" and c.op == "lte" for c in constraints)

    def test_extract_constraints_rating(self):
        constraints = _extract_constraints_from_text("At least 4 star rating")
        assert any(c.field == "rating" and c.op == "gte" for c in constraints)

    def test_extract_preferences_cheapest(self):
        scores, tie_breaks = _extract_preferences_from_text("Find cheapest hotel")
        assert "price_asc" in tie_breaks

    def test_extract_preferences_popular(self):
        scores, tie_breaks = _extract_preferences_from_text("Find most popular restaurant")
        assert "popularity_desc" in tie_breaks


# ---------------------------------------------------------------------------
# PatchPlanner fallback tests
# ---------------------------------------------------------------------------


class TestPatchPlannerFallback:
    """Test patch planner with rule-based fallback via PatchGenerator."""

    @pytest.mark.asyncio
    async def test_target_not_found_with_dom(self):
        request = PlanPatchRequest(
            requestId="req-200",
            step_id="login",
            error_type="TargetNotFound",
            url="https://example.com/login",
            failed_selector="#old-btn",
            dom_snippet='<button id="new-login-btn">Log In</button>',
        )
        result = await plan_patch_for_failure(request)
        assert result.request_id == "req-200"
        assert len(result.patch) >= 1
        assert result.patch[0].op == "actions.replace"

    @pytest.mark.asyncio
    async def test_target_not_found_without_dom(self):
        request = PlanPatchRequest(
            requestId="req-201",
            step_id="login",
            error_type="TargetNotFound",
            url="https://example.com/login",
        )
        result = await plan_patch_for_failure(request)
        assert result.request_id == "req-201"
        # Without DOM snippet, may return empty patch
        assert isinstance(result.patch, list)
        assert result.reason  # reason should always be present

    @pytest.mark.asyncio
    async def test_expectation_failed(self):
        request = PlanPatchRequest(
            requestId="req-202",
            step_id="dashboard",
            error_type="ExpectationFailed",
            url="https://example.com/dashboard",
            title="Dashboard - Example",
        )
        result = await plan_patch_for_failure(request)
        assert result.request_id == "req-202"
        if result.patch:
            assert result.patch[0].op == "workflow.update_expect"

    @pytest.mark.asyncio
    async def test_extraction_empty(self):
        request = PlanPatchRequest(
            requestId="req-203",
            step_id="scrape",
            error_type="ExtractionEmpty",
            url="https://example.com/products",
            failed_selector="div.product-list > div.item:nth-child(1)",
        )
        result = await plan_patch_for_failure(request)
        assert result.request_id == "req-203"
        if result.patch:
            assert result.patch[0].op == "selectors.replace"

    @pytest.mark.asyncio
    async def test_not_actionable(self):
        request = PlanPatchRequest(
            requestId="req-204",
            step_id="submit",
            error_type="NotActionable",
            url="https://example.com/form",
            failed_selector="#submit-btn",
            failed_action={"method": "click", "selector": "#submit-btn"},
        )
        result = await plan_patch_for_failure(request)
        assert result.request_id == "req-204"
        assert len(result.patch) >= 1
        assert result.patch[0].op == "actions.replace"

    @pytest.mark.asyncio
    async def test_unknown_error_type(self):
        request = PlanPatchRequest(
            requestId="req-205",
            step_id="unknown",
            error_type="UnknownError",
            url="https://example.com",
        )
        result = await plan_patch_for_failure(request)
        assert result.request_id == "req-205"
        assert isinstance(result.patch, list)
        assert result.reason


# ---------------------------------------------------------------------------
# Patch parsing helpers tests
# ---------------------------------------------------------------------------


class TestPatchParsingHelpers:
    """Test helper functions for building patch ops from parsed JSON."""

    def test_build_patch_ops_valid(self):
        parsed = {
            "ops": [
                {
                    "op": "actions.replace",
                    "key": "login_btn",
                    "value": {"selector": "#new-btn", "method": "click"},
                }
            ],
            "reason": "Updated selector",
        }
        ops = _build_patch_ops_from_parsed(parsed)
        assert len(ops) == 1
        assert ops[0].op == "actions.replace"
        assert ops[0].key == "login_btn"

    def test_build_patch_ops_skips_invalid(self):
        parsed = {
            "ops": [
                {"op": "actions.replace", "key": "x", "value": {}},
                {"missing_op": True},
                "not a dict",
            ]
        }
        ops = _build_patch_ops_from_parsed(parsed)
        assert len(ops) == 1

    def test_build_patch_ops_empty(self):
        parsed = {"ops": []}
        ops = _build_patch_ops_from_parsed(parsed)
        assert ops == []

    def test_build_patch_ops_no_ops_key(self):
        parsed = {"reason": "no ops"}
        ops = _build_patch_ops_from_parsed(parsed)
        assert ops == []


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestAPIIntegration:
    """Test that API endpoints work with real DSPy programs in fallback mode."""

    @pytest.mark.asyncio
    async def test_compile_intent_endpoint(self, client):
        payload = {
            "requestId": "api-001",
            "goal": "Book a flight",
            "domain": "airline.com",
        }
        response = await client.post("/compile-intent", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["requestId"] == "api-001"
        assert "workflow" in data
        assert "steps" in data["workflow"]
        assert len(data["workflow"]["steps"]) >= 1

    @pytest.mark.asyncio
    async def test_compile_intent_with_procedure(self, client):
        payload = {
            "requestId": "api-002",
            "goal": "Search products",
            "domain": "shop.com",
            "procedure": "1. Go to shop.com\n2. Click search\n3. Type laptop",
        }
        response = await client.post("/compile-intent", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["workflow"]["steps"]) >= 2

    @pytest.mark.asyncio
    async def test_plan_patch_endpoint(self, client):
        payload = {
            "requestId": "api-003",
            "step_id": "login",
            "error_type": "TargetNotFound",
            "url": "https://example.com/login",
            "dom_snippet": '<button id="sign-in">Sign In</button>',
        }
        response = await client.post("/plan-patch", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["requestId"] == "api-003"
        assert "patch" in data
        assert "reason" in data
