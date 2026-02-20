import pytest

from app.schemas.patch_schema import PlanPatchRequest
from app.services.patch_generator import (
    PatchGenerator,
    TargetNotFoundStrategy,
    ExpectationFailedStrategy,
    ExtractionEmptyStrategy,
    NotActionableStrategy,
)


@pytest.fixture
def generator():
    return PatchGenerator()


# --- TargetNotFound strategy ---


class TestTargetNotFoundStrategy:
    def test_generates_replacement_from_dom_with_id(self):
        strategy = TargetNotFoundStrategy()
        request = PlanPatchRequest(
            requestId="r-1",
            step_id="login",
            error_type="TargetNotFound",
            url="https://example.com/login",
            failed_selector="button#old-submit",
            dom_snippet='<div><button id="new-submit" class="btn">Sign In</button></div>',
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        assert ops[0].op == "actions.replace"
        assert ops[0].key == "login"
        assert "new-submit" in ops[0].value["selector"]

    def test_generates_replacement_from_data_testid(self):
        strategy = TargetNotFoundStrategy()
        request = PlanPatchRequest(
            requestId="r-2",
            step_id="search",
            error_type="TargetNotFound",
            url="https://example.com",
            failed_selector=".old-search-btn",
            dom_snippet='<button data-testid="search-submit">Search</button>',
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        assert ops[0].value["selector"] == '[data-testid="search-submit"]'

    def test_returns_empty_without_dom_snippet(self):
        strategy = TargetNotFoundStrategy()
        request = PlanPatchRequest(
            requestId="r-3",
            step_id="login",
            error_type="TargetNotFound",
            url="https://example.com",
        )
        ops = strategy.generate(request)
        assert ops == []

    def test_uses_target_key_from_failed_action(self):
        strategy = TargetNotFoundStrategy()
        request = PlanPatchRequest(
            requestId="r-4",
            step_id="login",
            error_type="TargetNotFound",
            url="https://example.com",
            failed_action={"targetKey": "login.submit", "method": "click"},
            dom_snippet='<button id="sign-in">Login</button>',
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        assert ops[0].key == "login.submit"

    def test_preserves_method_from_failed_action(self):
        strategy = TargetNotFoundStrategy()
        request = PlanPatchRequest(
            requestId="r-5",
            step_id="fill_email",
            error_type="TargetNotFound",
            url="https://example.com",
            failed_action={"method": "fill"},
            dom_snippet='<input id="email-field" type="email">',
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        assert ops[0].value["method"] == "fill"

    def test_explain_includes_context(self):
        strategy = TargetNotFoundStrategy()
        request = PlanPatchRequest(
            requestId="r-6",
            step_id="login",
            error_type="TargetNotFound",
            url="https://example.com",
            failed_selector="#old-btn",
        )
        explanation = strategy.explain(request)
        assert "login" in explanation
        assert "#old-btn" in explanation
        assert "Target not found" in explanation


# --- ExpectationFailed strategy ---


class TestExpectationFailedStrategy:
    def test_generates_url_expectation(self):
        strategy = ExpectationFailedStrategy()
        request = PlanPatchRequest(
            requestId="r-10",
            step_id="login",
            error_type="ExpectationFailed",
            url="https://example.com/dashboard",
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        assert ops[0].op == "workflow.update_expect"
        assert ops[0].step == "login"
        expectations = ops[0].value
        assert any(e["kind"] == "url_contains" and "/dashboard" in e["value"] for e in expectations)

    def test_generates_title_expectation(self):
        strategy = ExpectationFailedStrategy()
        request = PlanPatchRequest(
            requestId="r-11",
            step_id="login",
            error_type="ExpectationFailed",
            url="https://example.com/home",
            title="Welcome Home",
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        expectations = ops[0].value
        assert any(e["kind"] == "title_contains" and e["value"] == "Welcome Home" for e in expectations)

    def test_returns_empty_for_root_url_no_title(self):
        strategy = ExpectationFailedStrategy()
        request = PlanPatchRequest(
            requestId="r-12",
            step_id="home",
            error_type="ExpectationFailed",
            url="https://example.com/",
        )
        ops = strategy.generate(request)
        # Root path "/" is skipped, and no title -> empty expectations -> no ops
        assert ops == []

    def test_explain_includes_url_and_title(self):
        strategy = ExpectationFailedStrategy()
        request = PlanPatchRequest(
            requestId="r-13",
            step_id="login",
            error_type="ExpectationFailed",
            url="https://example.com/dashboard",
            title="Dashboard",
        )
        explanation = strategy.explain(request)
        assert "login" in explanation
        assert "https://example.com/dashboard" in explanation
        assert "Dashboard" in explanation


# --- ExtractionEmpty strategy ---


class TestExtractionEmptyStrategy:
    def test_broadens_nth_child_selector(self):
        strategy = ExtractionEmptyStrategy()
        request = PlanPatchRequest(
            requestId="r-20",
            step_id="extract_items",
            error_type="ExtractionEmpty",
            url="https://example.com/list",
            failed_selector="ul.results > li:nth-child(1)",
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        assert ops[0].op == "selectors.replace"
        assert ":nth-child" not in ops[0].value["primary"]

    def test_broadens_deep_descendant_selector(self):
        strategy = ExtractionEmptyStrategy()
        request = PlanPatchRequest(
            requestId="r-21",
            step_id="extract_data",
            error_type="ExtractionEmpty",
            url="https://example.com/data",
            failed_selector="div.container > table > tbody > tr",
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        # Should remove the last segment
        assert ops[0].value["primary"] == "div.container > table > tbody"

    def test_uses_dom_snippet_when_no_selector(self):
        strategy = ExtractionEmptyStrategy()
        request = PlanPatchRequest(
            requestId="r-22",
            step_id="extract_items",
            error_type="ExtractionEmpty",
            url="https://example.com/list",
            dom_snippet='<div id="results-panel"><ul><li>Item 1</li></ul></div>',
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        assert "results-panel" in ops[0].value["primary"]

    def test_returns_empty_without_selector_or_dom(self):
        strategy = ExtractionEmptyStrategy()
        request = PlanPatchRequest(
            requestId="r-23",
            step_id="extract",
            error_type="ExtractionEmpty",
            url="https://example.com",
        )
        ops = strategy.generate(request)
        assert ops == []

    def test_explain_includes_selector(self):
        strategy = ExtractionEmptyStrategy()
        request = PlanPatchRequest(
            requestId="r-24",
            step_id="extract_items",
            error_type="ExtractionEmpty",
            url="https://example.com",
            failed_selector="table.data > tr",
        )
        explanation = strategy.explain(request)
        assert "extract_items" in explanation
        assert "table.data > tr" in explanation


# --- NotActionable strategy ---


class TestNotActionableStrategy:
    def test_replaces_click_with_focus(self):
        strategy = NotActionableStrategy()
        request = PlanPatchRequest(
            requestId="r-30",
            step_id="submit",
            error_type="NotActionable",
            url="https://example.com",
            failed_selector="#submit-btn",
            failed_action={"method": "click", "selector": "#submit-btn"},
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        assert ops[0].op == "actions.replace"
        assert ops[0].value["method"] == "focus"

    def test_replaces_fill_with_type(self):
        strategy = NotActionableStrategy()
        request = PlanPatchRequest(
            requestId="r-31",
            step_id="fill_email",
            error_type="NotActionable",
            url="https://example.com",
            failed_action={"method": "fill", "selector": "input#email", "arguments": ["test@test.com"]},
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        assert ops[0].value["method"] == "type"
        # Arguments should be carried over for compatible methods
        assert ops[0].value["arguments"] == ["test@test.com"]

    def test_defaults_to_click_for_unknown_method(self):
        strategy = NotActionableStrategy()
        request = PlanPatchRequest(
            requestId="r-32",
            step_id="interact",
            error_type="NotActionable",
            url="https://example.com",
            failed_action={"method": "hover", "selector": ".menu"},
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        assert ops[0].value["method"] == "click"

    def test_uses_failed_selector(self):
        strategy = NotActionableStrategy()
        request = PlanPatchRequest(
            requestId="r-33",
            step_id="submit",
            error_type="NotActionable",
            url="https://example.com",
            failed_selector="#my-button",
        )
        ops = strategy.generate(request)
        assert len(ops) == 1
        assert ops[0].value["selector"] == "#my-button"

    def test_explain_includes_method_and_step(self):
        strategy = NotActionableStrategy()
        request = PlanPatchRequest(
            requestId="r-34",
            step_id="submit",
            error_type="NotActionable",
            url="https://example.com",
            failed_action={"method": "click", "selector": "#btn"},
        )
        explanation = strategy.explain(request)
        assert "submit" in explanation
        assert "click" in explanation


# --- PatchGenerator routing ---


class TestPatchGenerator:
    def test_routes_to_target_not_found(self, generator):
        request = PlanPatchRequest(
            requestId="r-40",
            step_id="login",
            error_type="TargetNotFound",
            url="https://example.com",
            dom_snippet='<button id="sign-in">Login</button>',
        )
        response = generator.generate_patch(request)
        assert response.request_id == "r-40"
        assert len(response.patch) == 1
        assert response.patch[0].op == "actions.replace"

    def test_routes_to_expectation_failed(self, generator):
        request = PlanPatchRequest(
            requestId="r-41",
            step_id="login",
            error_type="ExpectationFailed",
            url="https://example.com/dashboard",
            title="Dashboard",
        )
        response = generator.generate_patch(request)
        assert len(response.patch) == 1
        assert response.patch[0].op == "workflow.update_expect"

    def test_routes_to_extraction_empty(self, generator):
        request = PlanPatchRequest(
            requestId="r-42",
            step_id="extract",
            error_type="ExtractionEmpty",
            url="https://example.com",
            failed_selector="div.container > table > tbody > tr",
        )
        response = generator.generate_patch(request)
        assert len(response.patch) == 1
        assert response.patch[0].op == "selectors.replace"

    def test_routes_to_not_actionable(self, generator):
        request = PlanPatchRequest(
            requestId="r-43",
            step_id="submit",
            error_type="NotActionable",
            url="https://example.com",
            failed_action={"method": "click", "selector": "#btn"},
        )
        response = generator.generate_patch(request)
        assert len(response.patch) == 1
        assert response.patch[0].op == "actions.replace"

    def test_unknown_error_type_returns_empty(self, generator):
        request = PlanPatchRequest(
            requestId="r-44",
            step_id="step1",
            error_type="CaptchaOr2FA",
            url="https://example.com",
        )
        response = generator.generate_patch(request)
        assert response.patch == []
        assert "No strategy" in response.reason
        assert "CaptchaOr2FA" in response.reason

    def test_insufficient_context_noted_in_reason(self, generator):
        request = PlanPatchRequest(
            requestId="r-45",
            step_id="login",
            error_type="TargetNotFound",
            url="https://example.com",
            # No dom_snippet, so strategy can't produce ops
        )
        response = generator.generate_patch(request)
        assert response.patch == []
        assert "insufficient context" in response.reason.lower()
