"""
DSPy-powered intent-to-policy compiler.

Uses dspy.Predict with IntentToPolicySignature when an LLM is configured.
Falls back to rule-based generation when no LLM is available (test/dev environments).
All outputs are validated against Pydantic schemas before returning.
"""

from __future__ import annotations

import json
import logging
import re

import dspy

from app.dspy_programs.signatures import IntentToPolicySignature
from app.schemas.recipe_schema import Policy, PolicyCondition, PolicyScoreRule

logger = logging.getLogger(__name__)


def _is_dspy_configured() -> bool:
    """Check whether a DSPy language model is configured."""
    try:
        return dspy.settings.lm is not None
    except Exception:
        return False


class IntentToPolicyProgram(dspy.Module):
    """DSPy module that compiles user constraints into policy DSL."""

    def __init__(self) -> None:
        super().__init__()
        self.generate = dspy.Predict(IntentToPolicySignature)

    def forward(self, goal: str, constraints: str = "[]", preferences: str = ""):
        return self.generate(goal=goal, constraints=constraints, preferences=preferences)


_program: IntentToPolicyProgram | None = None


def _get_program() -> IntentToPolicyProgram:
    global _program
    if _program is None:
        _program = IntentToPolicyProgram()
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


def _build_policy_from_parsed(parsed: dict) -> Policy:
    """Build a Policy from parsed JSON, validating each component."""
    hard: list[PolicyCondition] = []
    for raw in parsed.get("hard", []):
        if isinstance(raw, dict) and "field" in raw and "op" in raw and "value" in raw:
            hard.append(PolicyCondition(field=raw["field"], op=raw["op"], value=raw["value"]))

    score: list[PolicyScoreRule] = []
    for raw in parsed.get("score", []):
        if isinstance(raw, dict) and "when" in raw and "add" in raw:
            when = raw["when"]
            if isinstance(when, dict) and "field" in when and "op" in when and "value" in when:
                score.append(
                    PolicyScoreRule(
                        when=PolicyCondition(field=when["field"], op=when["op"], value=when["value"]),
                        add=float(raw["add"]),
                    )
                )

    tie_break = parsed.get("tie_break", ["label_asc"])
    if not isinstance(tie_break, list):
        tie_break = ["label_asc"]

    pick = parsed.get("pick", "first")
    if pick not in ("argmax", "argmin", "first"):
        pick = "first"

    return Policy(hard=hard, score=score, tie_break=tie_break, pick=pick)


async def _compile_with_dspy(
    goal: str, constraints: dict | None = None
) -> dict[str, Policy]:
    """Use the DSPy program to compile constraints into policies."""
    program = _get_program()
    constraints_str = json.dumps(constraints) if constraints else "[]"

    result = program(
        goal=goal,
        constraints=constraints_str,
        preferences=goal,  # Use goal as preferences context
    )

    parsed = _parse_json_safe(result.policy_json, "policy")
    if isinstance(parsed, dict):
        policy = _build_policy_from_parsed(parsed)
    else:
        policy = _build_default_policy()

    return {"default_policy": policy}


# ---------------------------------------------------------------------------
# Rule-based fallback generation
# ---------------------------------------------------------------------------

# Patterns for extracting constraints from natural language
_CONSTRAINT_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, field, op)
    (r"\b(?:under|below|less\s+than|max(?:imum)?)\s+\$?(\d+(?:\.\d+)?)", "price", "lte"),
    (r"\b(?:over|above|more\s+than|min(?:imum)?)\s+\$?(\d+(?:\.\d+)?)", "price", "gte"),
    (r"\b(?:at\s+least|minimum)\s+(\d+)\s+(?:star|rating)", "rating", "gte"),
    (r"\b(?:within|max)\s+(\d+)\s*(?:mi(?:le)?s?|km)", "distance", "lte"),
    (r"\b(?:before|by)\s+(\d{1,2}[:/]\d{2})", "time", "lte"),
    (r"\b(?:after|from)\s+(\d{1,2}[:/]\d{2})", "time", "gte"),
]

_PREFERENCE_PATTERNS: list[tuple[str, str, float]] = [
    # (regex, sort_key_or_score_field, weight)
    (r"\bcheap(?:est|er)?\b", "price_asc", 10.0),
    (r"\bexpensive\b", "price_desc", 10.0),
    (r"\bbest\s+(?:rated?|review)", "rating_desc", 10.0),
    (r"\bclose(?:st|r)?\b", "distance_asc", 10.0),
    (r"\bfast(?:est)?\b", "duration_asc", 10.0),
    (r"\bearli(?:est|er)\b", "time_asc", 10.0),
    (r"\blatest?\b", "time_desc", 10.0),
    (r"\bpopular\b", "popularity_desc", 5.0),
]


def _build_default_policy() -> Policy:
    """Return a safe default policy."""
    return Policy(
        hard=[],
        score=[],
        tie_break=["label_asc"],
        pick="first",
    )


def _extract_constraints_from_text(text: str) -> list[PolicyCondition]:
    """Extract hard constraints from natural language."""
    conditions: list[PolicyCondition] = []
    for pattern, field, op in _CONSTRAINT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1)
            # Try numeric conversion
            try:
                value = float(value)
                if value == int(value):
                    value = int(value)
            except (ValueError, TypeError):
                pass
            conditions.append(PolicyCondition(field=field, op=op, value=value))
    return conditions


def _extract_preferences_from_text(text: str) -> tuple[list[PolicyScoreRule], list[str]]:
    """Extract score rules and tie-break keys from natural language."""
    score_rules: list[PolicyScoreRule] = []
    tie_break_keys: list[str] = []
    for pattern, sort_key, weight in _PREFERENCE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            tie_break_keys.append(sort_key)
            # Also create a score rule
            field = sort_key.rsplit("_", 1)[0]
            is_asc = sort_key.endswith("_asc")
            score_rules.append(
                PolicyScoreRule(
                    when=PolicyCondition(
                        field=field,
                        op="exists",
                        value=True,
                    ),
                    add=weight if not is_asc else -weight,
                )
            )
    return score_rules, tie_break_keys


async def _compile_with_rules(
    goal: str, constraints: dict | None = None
) -> dict[str, Policy]:
    """Rule-based policy generation from goal text and structured constraints."""
    hard: list[PolicyCondition] = []
    score: list[PolicyScoreRule] = []
    tie_break: list[str] = []

    # Process structured constraints if provided
    if constraints:
        if isinstance(constraints, list):
            for c in constraints:
                if isinstance(c, dict) and "field" in c and "op" in c and "value" in c:
                    hard.append(PolicyCondition(field=c["field"], op=c["op"], value=c["value"]))
        elif isinstance(constraints, dict):
            for field, value in constraints.items():
                if isinstance(value, dict) and "op" in value and "value" in value:
                    hard.append(PolicyCondition(field=field, op=value["op"], value=value["value"]))
                else:
                    hard.append(PolicyCondition(field=field, op="eq", value=value))

    # Extract additional constraints from goal text
    text_constraints = _extract_constraints_from_text(goal)
    hard.extend(text_constraints)

    # Extract preferences from goal text
    text_scores, text_tie_breaks = _extract_preferences_from_text(goal)
    score.extend(text_scores)
    tie_break.extend(text_tie_breaks)

    # Determine pick strategy from preference-derived tie-breaks
    pick = "first"
    if tie_break:
        if any("desc" in tb for tb in tie_break):
            pick = "argmax"
        elif any("asc" in tb for tb in tie_break):
            pick = "argmin"

    # Default tie-break if none found from preferences
    if not tie_break:
        tie_break = ["label_asc"]

    policy = Policy(hard=hard, score=score, tie_break=tie_break, pick=pick)
    return {"default_policy": policy}


async def compile_intent_to_policy(
    goal: str,
    constraints: dict | None = None,
) -> dict[str, Policy]:
    """
    Compile user constraints into policy DSL.

    Uses DSPy Predict when an LLM is configured.
    Falls back to rule-based generation otherwise.
    """
    if _is_dspy_configured():
        try:
            return await _compile_with_dspy(goal, constraints)
        except Exception as exc:
            logger.warning("DSPy policy compilation failed, falling back to rules: %s", exc)

    return await _compile_with_rules(goal, constraints)
