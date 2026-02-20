import pytest

from app.schemas.patch_schema import PatchOp, PlanPatchResponse
from app.services.patch_validator import (
    validate_patch_op,
    validate_response,
    ALLOWED_OPS,
)


class TestValidatePatchOp:
    def test_valid_actions_replace(self):
        op = PatchOp(
            op="actions.replace",
            key="login.submit",
            value={"selector": "#btn", "method": "click", "description": "btn", "arguments": []},
        )
        assert validate_patch_op(op) == []

    def test_valid_workflow_update_expect(self):
        op = PatchOp(
            op="workflow.update_expect",
            step="login",
            value=[{"kind": "url_contains", "value": "/dashboard"}],
        )
        assert validate_patch_op(op) == []

    def test_valid_selectors_replace(self):
        op = PatchOp(
            op="selectors.replace",
            key="seat.candidates",
            value={"primary": "table.results tr", "fallbacks": [], "strategy": "css"},
        )
        assert validate_patch_op(op) == []

    def test_valid_policies_update(self):
        op = PatchOp(
            op="policies.update",
            key="seat_policy_v1",
            value={"hard": [], "score": [], "tie_break": [], "pick": "first"},
        )
        assert validate_patch_op(op) == []

    def test_invalid_op_type(self):
        op = PatchOp(op="workflow.delete", key="step1", value={})
        errors = validate_patch_op(op)
        assert len(errors) == 1
        assert "Invalid op type" in errors[0]

    def test_actions_without_key(self):
        op = PatchOp(
            op="actions.replace",
            value={"selector": "#btn", "method": "click"},
        )
        errors = validate_patch_op(op)
        assert any("requires a 'key'" in e for e in errors)

    def test_selectors_without_key(self):
        op = PatchOp(
            op="selectors.add",
            value={"primary": "div.item", "fallbacks": [], "strategy": "css"},
        )
        errors = validate_patch_op(op)
        assert any("requires a 'key'" in e for e in errors)

    def test_workflow_update_without_step(self):
        op = PatchOp(
            op="workflow.update_expect",
            value=[{"kind": "url_contains", "value": "/home"}],
        )
        errors = validate_patch_op(op)
        assert any("requires a 'step'" in e for e in errors)

    def test_empty_selector_rejected(self):
        op = PatchOp(
            op="actions.replace",
            key="login.submit",
            value={"selector": "", "method": "click"},
        )
        errors = validate_patch_op(op)
        assert any("must not be empty" in e for e in errors)

    def test_whitespace_only_selector_rejected(self):
        op = PatchOp(
            op="actions.replace",
            key="login.submit",
            value={"selector": "   ", "method": "click"},
        )
        errors = validate_patch_op(op)
        assert any("must not be empty" in e for e in errors)

    def test_overly_generic_selector_rejected(self):
        op = PatchOp(
            op="actions.replace",
            key="login.submit",
            value={"selector": "div", "method": "click"},
        )
        errors = validate_patch_op(op)
        assert any("too generic" in e for e in errors)

    def test_star_selector_rejected(self):
        op = PatchOp(
            op="selectors.replace",
            key="items",
            value={"primary": "*", "fallbacks": [], "strategy": "css"},
        )
        errors = validate_patch_op(op)
        assert any("too generic" in e for e in errors)

    def test_none_value_rejected(self):
        op = PatchOp(op="actions.replace", key="login", value=None)
        errors = validate_patch_op(op)
        assert any("requires a 'value'" in e for e in errors)

    def test_all_allowed_ops_accepted(self):
        """Every allowed op type should pass the op type check."""
        for op_type in ALLOWED_OPS:
            op = PatchOp(op=op_type, key="k", step="s", value={"data": True})
            errors = validate_patch_op(op)
            assert not any("Invalid op type" in e for e in errors), f"{op_type} should be allowed"


class TestValidateResponse:
    def test_valid_response(self):
        response = PlanPatchResponse(
            requestId="r-1",
            patch=[
                PatchOp(
                    op="actions.replace",
                    key="login.submit",
                    value={"selector": "#btn-new", "method": "click", "description": "new", "arguments": []},
                )
            ],
            reason="Updated selector for changed DOM",
        )
        result = validate_response(response)
        assert result.valid is True
        assert result.errors == []

    def test_empty_patch_is_valid(self):
        response = PlanPatchResponse(
            requestId="r-2",
            patch=[],
            reason="No strategy available",
        )
        result = validate_response(response)
        assert result.valid is True

    def test_empty_reason_invalid(self):
        response = PlanPatchResponse(
            requestId="r-3",
            patch=[],
            reason="",
        )
        result = validate_response(response)
        assert result.valid is False
        assert any("non-empty reason" in e for e in result.errors)

    def test_whitespace_reason_invalid(self):
        response = PlanPatchResponse(
            requestId="r-4",
            patch=[],
            reason="   ",
        )
        result = validate_response(response)
        assert result.valid is False

    def test_multiple_patch_ops_validated(self):
        response = PlanPatchResponse(
            requestId="r-5",
            patch=[
                PatchOp(op="actions.replace", key="k1", value={"selector": "#a", "method": "click"}),
                PatchOp(op="invalid.op", key="k2", value={}),
            ],
            reason="Mixed validity",
        )
        result = validate_response(response)
        assert result.valid is False
        assert any("patch[1]" in e for e in result.errors)
        # First patch is valid, no error for patch[0] op type
        assert not any("patch[0]" in e and "Invalid op type" in e for e in result.errors)
