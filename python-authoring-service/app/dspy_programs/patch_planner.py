"""
DSPy-powered patch planner with rule-based fallback.

Uses dspy.ChainOfThought with PatchPlannerSignature when an LLM is configured.
Falls back to the strategy-pattern PatchGenerator when no LLM is available.
All outputs are validated against the patch schema before returning.
"""

from __future__ import annotations

import json
import logging
import re

import dspy

from app.dspy_programs.signatures import PatchPlannerSignature
from app.schemas.patch_schema import PatchOp, PlanPatchRequest, PlanPatchResponse
from app.services.patch_generator import PatchGenerator
from app.services.patch_validator import validate_response

logger = logging.getLogger(__name__)

_generator = PatchGenerator()


def _is_dspy_configured() -> bool:
    """Check whether a DSPy language model is configured."""
    try:
        return dspy.settings.lm is not None
    except Exception:
        return False


class PatchPlannerProgram(dspy.Module):
    """DSPy module that generates minimal patches for automation failures."""

    def __init__(self) -> None:
        super().__init__()
        self.generate = dspy.ChainOfThought(PatchPlannerSignature)

    def forward(
        self,
        step_id: str,
        error_type: str,
        url: str,
        failed_selector: str = "",
        dom_snippet: str = "",
    ):
        return self.generate(
            step_id=step_id,
            error_type=error_type,
            url=url,
            failed_selector=failed_selector,
            dom_snippet=dom_snippet,
        )


_program: PatchPlannerProgram | None = None


def _get_program() -> PatchPlannerProgram:
    global _program
    if _program is None:
        _program = PatchPlannerProgram()
    return _program


def _parse_json_safe(text: str, field_name: str) -> dict | list | None:
    """Parse JSON from DSPy output, handling markdown code fences."""
    if not text or not text.strip():
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Failed to parse %s JSON: %s", field_name, cleaned[:200])
        return None


def _build_patch_ops_from_parsed(parsed: dict) -> list[PatchOp]:
    """Build PatchOp list from parsed JSON."""
    raw_ops = parsed.get("ops", [])
    ops: list[PatchOp] = []
    for raw in raw_ops:
        if not isinstance(raw, dict) or "op" not in raw:
            continue
        try:
            ops.append(
                PatchOp(
                    op=raw["op"],
                    key=raw.get("key"),
                    step=raw.get("step"),
                    value=raw.get("value", {}),
                )
            )
        except Exception:
            logger.warning("Skipping invalid patch op: %s", raw)
    return ops


async def _plan_with_dspy(request: PlanPatchRequest) -> PlanPatchResponse:
    """Use the DSPy program to generate a patch."""
    program = _get_program()

    result = program(
        step_id=request.step_id,
        error_type=request.error_type,
        url=request.url,
        failed_selector=request.failed_selector or "",
        dom_snippet=request.dom_snippet or "",
    )

    parsed = _parse_json_safe(result.patch_json, "patch")
    if isinstance(parsed, dict):
        ops = _build_patch_ops_from_parsed(parsed)
        reason = parsed.get("reason", f"DSPy-generated patch for {request.error_type} at step {request.step_id}")
    else:
        ops = []
        reason = f"DSPy output could not be parsed for {request.error_type} at step {request.step_id}"

    return PlanPatchResponse(
        requestId=request.request_id,
        patch=ops,
        reason=reason,
    )


async def plan_patch_for_failure(request: PlanPatchRequest) -> PlanPatchResponse:
    """
    Generate a minimal patch to recover from a step failure.

    Uses DSPy ChainOfThought when an LLM is configured for richer context understanding.
    Falls back to the strategy-pattern PatchGenerator for rule-based patch generation.
    All outputs are validated before returning.
    """
    if _is_dspy_configured():
        try:
            response = await _plan_with_dspy(request)
            validation = validate_response(response)
            if validation.valid:
                return response
            logger.warning(
                "DSPy patch failed validation: %s. Falling back to rules.",
                "; ".join(validation.errors),
            )
        except Exception as exc:
            logger.warning("DSPy patch planning failed, falling back to rules: %s", exc)

    # Rule-based fallback via PatchGenerator
    response = _generator.generate_patch(request)

    validation = validate_response(response)
    if not validation.valid:
        return PlanPatchResponse(
            requestId=request.request_id,
            patch=[],
            reason=(
                f"Generated patch failed validation for {request.error_type} "
                f"at step {request.step_id}: {'; '.join(validation.errors)}"
            ),
        )

    return response
