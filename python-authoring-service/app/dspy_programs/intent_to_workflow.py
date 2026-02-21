"""
DSPy-powered intent-to-workflow compiler.

Uses dspy.ChainOfThought with IntentToWorkflowSignature when an LLM is configured.
Falls back to rule-based generation when no LLM is available (test/dev environments).
All outputs are validated against Pydantic schemas before returning.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

import dspy

from app.dspy_programs.signatures import IntentToWorkflowSignature
from app.schemas.recipe_schema import (
    ActionEntry,
    ActionRef,
    CompileIntentRequest,
    CompileIntentResponse,
    Expectation,
    Fingerprint,
    SelectorEntry,
    Workflow,
    WorkflowStep,
)

logger = logging.getLogger(__name__)


def _is_dspy_configured() -> bool:
    """Check whether a DSPy language model is configured."""
    try:
        return dspy.settings.lm is not None
    except Exception:
        return False


class IntentToWorkflowProgram(dspy.Module):
    """DSPy module that compiles user intent into a structured workflow recipe."""

    def __init__(self) -> None:
        super().__init__()
        self.generate = dspy.ChainOfThought(IntentToWorkflowSignature)

    def forward(self, goal: str, procedure: str = "", domain: str = "", context: str = "{}"):
        return self.generate(goal=goal, procedure=procedure, domain=domain, context=context)


# Module-level singleton, created lazily
_program: IntentToWorkflowProgram | None = None


def _get_program() -> IntentToWorkflowProgram:
    global _program
    if _program is None:
        _program = IntentToWorkflowProgram()
    return _program


def _parse_json_safe(text: str, field_name: str) -> dict | list | None:
    """Parse JSON from DSPy output, handling markdown code fences."""
    if not text or not text.strip():
        return None
    cleaned = text.strip()
    # Remove markdown code fences if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Failed to parse %s JSON: %s", field_name, cleaned[:200])
        return None


def _build_workflow_from_parsed(
    parsed: dict, domain: str, goal: str
) -> Workflow:
    """Build a Workflow from parsed JSON, validating each step."""
    workflow_id = parsed.get("id", f"{domain or 'default'}_flow")
    raw_steps = parsed.get("steps", [])
    steps: list[WorkflowStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict) or "id" not in raw or "op" not in raw:
            continue
        steps.append(
            WorkflowStep(
                id=raw["id"],
                op=raw["op"],
                targetKey=raw.get("targetKey"),
                args=raw.get("args"),
                expect=[
                    Expectation(kind=e["kind"], value=e["value"])
                    for e in raw.get("expect", [])
                    if isinstance(e, dict) and "kind" in e and "value" in e
                ] or None,
                onFail=raw.get("onFail"),
            )
        )
    if not steps:
        # Fallback: at minimum a goto step
        steps = _generate_fallback_steps(domain, goal)
    return Workflow(id=workflow_id, steps=steps)


def _build_actions_from_parsed(parsed: dict) -> dict[str, ActionEntry]:
    """Build ActionEntry map from parsed JSON."""
    actions: dict[str, ActionEntry] = {}
    now = datetime.now(timezone.utc).isoformat()
    for key, raw in parsed.items():
        if not isinstance(raw, dict):
            continue
        preferred_raw = raw.get("preferred", raw)
        try:
            preferred = ActionRef(
                selector=preferred_raw.get("selector", ""),
                description=preferred_raw.get("description", key),
                method=preferred_raw.get("method", "click"),
                arguments=preferred_raw.get("arguments"),
            )
            actions[key] = ActionEntry(
                instruction=raw.get("instruction", key),
                preferred=preferred,
                observedAt=raw.get("observedAt", now),
            )
        except Exception:
            logger.warning("Skipping invalid action entry for key: %s", key)
    return actions


def _build_selectors_from_parsed(parsed: dict) -> dict[str, SelectorEntry]:
    """Build SelectorEntry map from parsed JSON."""
    selectors: dict[str, SelectorEntry] = {}
    for key, raw in parsed.items():
        if not isinstance(raw, dict):
            continue
        try:
            selectors[key] = SelectorEntry(
                primary=raw.get("primary", ""),
                fallbacks=raw.get("fallbacks", []),
                strategy=raw.get("strategy", "css"),
            )
        except Exception:
            logger.warning("Skipping invalid selector entry for key: %s", key)
    return selectors


async def _compile_with_dspy(request: CompileIntentRequest) -> CompileIntentResponse:
    """Use the DSPy program to compile intent into a recipe."""
    program = _get_program()
    context_str = json.dumps(request.context) if request.context else "{}"

    result = program(
        goal=request.goal,
        procedure=request.procedure or "",
        domain=request.domain or "",
        context=context_str,
    )

    # Parse the three JSON outputs
    workflow_parsed = _parse_json_safe(result.workflow_json, "workflow")
    actions_parsed = _parse_json_safe(result.actions_json, "actions")
    selectors_parsed = _parse_json_safe(result.selectors_json, "selectors")

    domain = request.domain or "default"

    # Build workflow
    if isinstance(workflow_parsed, dict):
        workflow = _build_workflow_from_parsed(workflow_parsed, domain, request.goal)
    else:
        workflow = Workflow(
            id=f"{domain}_flow",
            steps=_generate_fallback_steps(domain, request.goal),
        )

    # Build actions
    actions = _build_actions_from_parsed(actions_parsed) if isinstance(actions_parsed, dict) else {}

    # Build selectors
    selectors = _build_selectors_from_parsed(selectors_parsed) if isinstance(selectors_parsed, dict) else {}

    return CompileIntentResponse(
        requestId=request.request_id,
        workflow=workflow,
        actions=actions,
        selectors=selectors,
        policies={},
        fingerprints={},
    )


# ---------------------------------------------------------------------------
# Rule-based fallback generation
# ---------------------------------------------------------------------------

_STEP_PATTERNS: list[tuple[str, str, dict | None]] = [
    # (keyword regex, op, extra args template)
    # More specific patterns first to avoid false matches
    (r"\b(?:wait|pause|delay)\b", "wait", {"ms": 1000}),
    (r"\b(?:check|verify|assert|confirm|expect)\b", "checkpoint", None),
    (r"\b(?:go\s*to|open|navigate|visit|load)\b", "goto", None),
    (r"\b(?:click|press|tap|select|choose|toggle)\b", "act_cached", None),
    (r"\b(?:type|enter|fill|input|write|search)\b", "act_cached", None),
    (r"\b(?:extract|scrape|get|read|capture|copy)\b", "extract", None),
    (r"\b(?:pick|filter|sort|rank|compare)\b", "choose", None),
]


def _generate_fallback_steps(domain: str, goal: str) -> list[WorkflowStep]:
    """Generate minimal workflow steps from goal text using pattern matching."""
    steps: list[WorkflowStep] = [
        WorkflowStep(
            id="open",
            op="goto",
            args={"url": f"https://{domain or 'example.com'}"},
        ),
    ]
    return steps


def _split_into_clauses(text: str) -> list[str]:
    """Split a natural-language sentence into individual action clauses.

    Handles:
    - Multi-line numbered/bulleted lists (split by newline)
    - Comma-separated clauses ("go to X, click Y, extract Z")
    - Conjunction-separated clauses ("click X and extract Y", "type X then click Y")

    Only splits on commas/conjunctions when the resulting clauses each contain
    an action verb, to avoid splitting phrases like "extract the price and title".
    """
    # First split by newlines
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]

    # If we already have multiple lines, return them as-is (numbered list format)
    if len(lines) > 1:
        return lines

    # Single line — try splitting on commas and conjunctions
    single = lines[0] if lines else text.strip()

    # Action verb pattern used to detect if a clause is actionable
    _verb_pat = re.compile(
        r"\b(?:go\s*to|open|navigate|visit|load|click|press|tap|select|choose|toggle"
        r"|type|enter|fill|input|write|search|extract|scrape|get|read|capture|copy"
        r"|pick|filter|sort|rank|compare|wait|pause|delay|check|verify|assert"
        r"|confirm|expect|scroll|hover|submit|log\s*in|sign\s*in|add|remove|close)\b",
        re.IGNORECASE,
    )

    # Split on ", " followed by an action verb, or " and/then " between action verbs
    # We use a lookahead approach: split then validate
    # Pattern: comma or " and "/" then "/" after that " as separators
    raw_parts = re.split(r",\s+|\s+(?:and\s+then|then|and)\s+", single)

    # Validate: only accept split if every clause has an action verb
    if len(raw_parts) > 1 and all(_verb_pat.search(p) for p in raw_parts):
        return [p.strip() for p in raw_parts if p.strip()]

    # If splitting didn't produce valid clauses, try just comma splits
    comma_parts = re.split(r",\s+", single)
    if len(comma_parts) > 1 and all(_verb_pat.search(p) for p in comma_parts):
        return [p.strip() for p in comma_parts if p.strip()]

    # Return as single clause
    return [single]


def _parse_procedure_to_steps(
    procedure: str, domain: str
) -> list[WorkflowStep]:
    """Parse a step-by-step procedure string into workflow steps.

    Handles both multi-line numbered lists and single-sentence comma/conjunction-
    separated instructions like:
      "Go to amazon.com, search for laptop, click the first result, extract the price"
    """
    clauses = _split_into_clauses(procedure)
    steps: list[WorkflowStep] = []
    step_idx = 0
    detected_domain = domain

    for clause in clauses:
        # Strip leading numbering like "1.", "1)", "- ", "* "
        cleaned = re.sub(r"^[\d]+[.)]\s*", "", clause)
        cleaned = re.sub(r"^[-*]\s*", "", cleaned).strip()
        if not cleaned:
            continue

        # Match against known patterns
        matched_op = None
        for pattern, op, default_args in _STEP_PATTERNS:
            if re.search(pattern, cleaned, re.IGNORECASE):
                matched_op = op
                break

        if matched_op is None:
            # Default to act_cached for unrecognized steps
            matched_op = "act_cached"

        step_id = f"step_{step_idx}"
        step_idx += 1
        args: dict | None = None
        target_key: str | None = None

        if matched_op == "goto":
            # Try to extract URL from the text
            url_match = re.search(r"(https?://\S+)", cleaned)
            domain_match = re.search(r"\b([\w.-]+\.(?:com|org|net|io|co|ai|dev|app)\b)", cleaned)
            if url_match:
                args = {"url": url_match.group(1)}
            elif domain_match:
                detected_domain = domain_match.group(1)
                args = {"url": f"https://{detected_domain}"}
            else:
                args = {"url": f"https://{detected_domain or 'example.com'}"}
        elif matched_op in ("act_cached", "extract", "choose"):
            target_key = f"target_{step_idx}"
            args = {"instruction": cleaned}
        elif matched_op == "wait":
            args = {"ms": 1000}
        elif matched_op == "checkpoint":
            args = {"message": cleaned}

        steps.append(
            WorkflowStep(
                id=step_id,
                op=matched_op,
                targetKey=target_key,
                args=args,
            )
        )

    return steps


def _generate_actions_from_steps(
    steps: list[WorkflowStep],
) -> dict[str, ActionEntry]:
    """Generate placeholder action entries for steps that have target keys."""
    actions: dict[str, ActionEntry] = {}
    now = datetime.now(timezone.utc).isoformat()
    for step in steps:
        if step.target_key and step.op in ("act_cached", "extract", "choose"):
            instruction = ""
            if step.args and "instruction" in step.args:
                instruction = step.args["instruction"]
            actions[step.target_key] = ActionEntry(
                instruction=instruction or step.id,
                preferred=ActionRef(
                    selector=f"[data-action='{step.target_key}']",
                    description=instruction or step.id,
                    method="click" if step.op != "extract" else "extract",
                    arguments=[],
                ),
                observedAt=now,
            )
    return actions


def _generate_selectors_from_steps(
    steps: list[WorkflowStep],
) -> dict[str, SelectorEntry]:
    """Generate placeholder selector entries for steps that have target keys."""
    selectors: dict[str, SelectorEntry] = {}
    for step in steps:
        if step.target_key:
            selectors[step.target_key] = SelectorEntry(
                primary=f"[data-action='{step.target_key}']",
                fallbacks=[],
                strategy="css",
            )
    return selectors


async def _compile_with_rules(request: CompileIntentRequest) -> CompileIntentResponse:
    """Rule-based fallback when DSPy is not configured."""
    domain = request.domain or "default"

    if request.procedure:
        steps = _parse_procedure_to_steps(request.procedure, request.domain or "example.com")
    else:
        steps = _generate_fallback_steps(request.domain or "example.com", request.goal)

    # Always add a checkpoint at the end
    steps.append(
        WorkflowStep(
            id="checkpoint_start",
            op="checkpoint",
            args={"message": f"Goal: {request.goal}. Proceed?"},
        )
    )

    workflow = Workflow(id=f"{domain}_flow", steps=steps)
    actions = _generate_actions_from_steps(steps)
    selectors = _generate_selectors_from_steps(steps)

    return CompileIntentResponse(
        requestId=request.request_id,
        workflow=workflow,
        actions=actions,
        selectors=selectors,
        policies={},
        fingerprints={},
    )


async def compile_intent_to_recipe(request: CompileIntentRequest) -> CompileIntentResponse:
    """
    Compile user intent into a full recipe (workflow + actions + selectors).

    Uses DSPy ChainOfThought when an LLM is configured.
    Falls back to rule-based generation otherwise.
    """
    if _is_dspy_configured():
        try:
            return await _compile_with_dspy(request)
        except Exception as exc:
            logger.warning("DSPy compilation failed, falling back to rules: %s", exc)

    return await _compile_with_rules(request)
