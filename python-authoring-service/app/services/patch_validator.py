"""
Validate generated patch ops before returning to the Node runtime.

Checks:
- Op types are in the allowed set (Blueprint §8)
- Selectors are non-empty and not too generic
- Reason is non-empty
- Keys/steps are present where required
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.patch_schema import PatchOp, PlanPatchResponse

ALLOWED_OPS = frozenset(
    {
        "actions.replace",
        "actions.add",
        "selectors.add",
        "selectors.replace",
        "workflow.update_expect",
        "policies.update",
    }
)

# Selectors that are too broad and likely to match unintended elements
OVERLY_GENERIC_SELECTORS = frozenset(
    {"*", "div", "span", "body", "html", "a", "p", "input", "button"}
)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)


def validate_patch_op(op: PatchOp) -> list[str]:
    """Validate a single patch op. Returns list of error messages."""
    errors: list[str] = []

    # Check op type
    if op.op not in ALLOWED_OPS:
        errors.append(f"Invalid op type '{op.op}'. Allowed: {sorted(ALLOWED_OPS)}")

    # Check key/step presence based on op type
    if op.op.startswith("actions.") or op.op.startswith("selectors."):
        if not op.key:
            errors.append(f"Op '{op.op}' requires a 'key' field")

    if op.op == "workflow.update_expect":
        if not op.step:
            errors.append(f"Op '{op.op}' requires a 'step' field")

    # Check value is present
    if op.value is None:
        errors.append(f"Op '{op.op}' requires a 'value' field")

    # Check selector quality for action/selector ops
    if op.value and isinstance(op.value, dict):
        # Check for selector in action ops or primary in selector ops
        has_selector = "selector" in op.value
        has_primary = "primary" in op.value
        if has_selector or has_primary:
            selector = op.value.get("selector") if has_selector else op.value.get("primary")
            if not selector or not selector.strip():
                errors.append("Selector must not be empty")
            elif selector.strip() in OVERLY_GENERIC_SELECTORS:
                errors.append(
                    f"Selector '{selector}' is too generic and may match unintended elements"
                )

    return errors


def validate_response(response: PlanPatchResponse) -> ValidationResult:
    """Validate a complete patch response."""
    errors: list[str] = []

    # Reason must be non-empty
    if not response.reason or not response.reason.strip():
        errors.append("Patch response must include a non-empty reason")

    # Validate each op
    for i, op in enumerate(response.patch):
        op_errors = validate_patch_op(op)
        for err in op_errors:
            errors.append(f"patch[{i}]: {err}")

    return ValidationResult(valid=len(errors) == 0, errors=errors)
