import pytest
from app.dspy_programs.intent_to_workflow import compile_intent_to_recipe
from app.dspy_programs.intent_to_policy import compile_intent_to_policy
from app.dspy_programs.patch_planner import plan_patch_for_failure
from app.schemas.recipe_schema import CompileIntentRequest
from app.schemas.patch_schema import PlanPatchRequest


@pytest.mark.asyncio
async def test_compile_intent_to_recipe_returns_workflow():
    request = CompileIntentRequest(requestId="req-100", goal="Book a flight", domain="airline.com")
    result = await compile_intent_to_recipe(request)
    assert result.request_id == "req-100"
    assert result.workflow.id == "airline.com_flow"
    assert len(result.workflow.steps) == 2
    assert result.workflow.steps[0].op == "goto"
    assert "airline.com" in result.workflow.steps[0].args["url"]
    assert result.workflow.steps[1].op == "checkpoint"


@pytest.mark.asyncio
async def test_compile_intent_to_recipe_default_domain():
    request = CompileIntentRequest(requestId="req-101", goal="Do something")
    result = await compile_intent_to_recipe(request)
    assert result.workflow.id == "default_flow"
    assert "example.com" in result.workflow.steps[0].args["url"]


@pytest.mark.asyncio
async def test_compile_intent_to_policy_returns_default():
    policies = await compile_intent_to_policy(goal="Pick best seat")
    assert "default_policy" in policies
    policy = policies["default_policy"]
    assert policy.pick == "first"
    assert policy.hard == []
    assert policy.score == []
    assert policy.tie_break == ["label_asc"]


@pytest.mark.asyncio
async def test_patch_planner_returns_empty_patch():
    request = PlanPatchRequest(
        requestId="req-200",
        step_id="login",
        error_type="TargetNotFound",
        url="https://example.com/login",
    )
    result = await plan_patch_for_failure(request)
    assert result.request_id == "req-200"
    assert result.patch == []
    assert "TargetNotFound" in result.reason
    assert "login" in result.reason
