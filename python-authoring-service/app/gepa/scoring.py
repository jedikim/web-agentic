"""Scoring functions for GEPA evaluation of generated recipes."""

from __future__ import annotations

# Valid workflow operations (from recipe_schema.py)
VALID_OPS = {"goto", "act_cached", "act_template", "extract", "choose", "checkpoint", "wait"}

# Required fields per operation type
REQUIRED_FIELDS: dict[str, set[str]] = {
    "goto": {"args"},
    "act_cached": {"targetKey"},
    "act_template": {"targetKey"},
    "extract": {"targetKey"},
    "choose": {"args"},
    "checkpoint": {"args"},
    "wait": {"args"},
}


def score_schema_validity(recipe: dict) -> float:
    """Validate workflow/actions/selectors/policies/fingerprints against schemas.

    Checks presence of required top-level keys and basic structural validity.
    Returns 0.0-1.0.
    """
    checks = []

    # Check workflow exists and has steps
    workflow = recipe.get("workflow")
    if isinstance(workflow, dict):
        checks.append(1.0)
        steps = workflow.get("steps", [])
        if isinstance(steps, list) and len(steps) > 0:
            checks.append(1.0)
            # Check each step has id and op
            valid_steps = 0
            for step in steps:
                if isinstance(step, dict) and "id" in step and "op" in step:
                    valid_steps += 1
            checks.append(valid_steps / len(steps) if steps else 0.0)
        else:
            checks.append(0.0)
            checks.append(0.0)
        # Check workflow has an id
        if "id" in workflow:
            checks.append(1.0)
        else:
            checks.append(0.0)
    else:
        checks.extend([0.0, 0.0, 0.0, 0.0])

    # Check actions is a dict
    actions = recipe.get("actions")
    if isinstance(actions, dict):
        checks.append(1.0)
        if actions:
            valid_actions = 0
            for key, entry in actions.items():
                if isinstance(entry, dict) and "preferred" in entry and "instruction" in entry:
                    pref = entry["preferred"]
                    if isinstance(pref, dict) and "selector" in pref and "method" in pref:
                        valid_actions += 1
            checks.append(valid_actions / len(actions))
        else:
            checks.append(1.0)  # Empty actions is valid
    else:
        checks.extend([0.0, 0.0])

    # Check selectors is a dict
    selectors = recipe.get("selectors")
    if isinstance(selectors, dict):
        checks.append(1.0)
    else:
        checks.append(0.0)

    # Check policies is a dict
    policies = recipe.get("policies")
    if isinstance(policies, dict):
        checks.append(1.0)
        if policies:
            valid_policies = 0
            for key, pol in policies.items():
                if isinstance(pol, dict) and "hard" in pol and "pick" in pol:
                    valid_policies += 1
            checks.append(valid_policies / len(policies))
        else:
            checks.append(1.0)
    else:
        checks.extend([0.0, 0.0])

    # Check fingerprints is a dict
    fingerprints = recipe.get("fingerprints")
    if isinstance(fingerprints, dict):
        checks.append(1.0)
    else:
        checks.append(0.0)

    return sum(checks) / len(checks) if checks else 0.0


def score_dry_run_success(workflow: dict) -> float:
    """Check workflow steps are logically valid.

    Validates that operations are known, required fields are present,
    and step ordering is reasonable.
    Returns 0.0-1.0.
    """
    steps = workflow.get("steps", [])
    if not isinstance(steps, list) or len(steps) == 0:
        return 0.0

    scores = []
    for step in steps:
        if not isinstance(step, dict):
            scores.append(0.0)
            continue

        step_score = 0.0
        op = step.get("op", "")

        # Check op is valid
        if op in VALID_OPS:
            step_score += 0.4
        else:
            scores.append(0.0)
            continue

        # Check required fields for this op
        required = REQUIRED_FIELDS.get(op, set())
        present_required = sum(
            1 for f in required
            if step.get(f) is not None or step.get(_camel_case(f)) is not None
        )
        if required:
            step_score += 0.3 * (present_required / len(required))
        else:
            step_score += 0.3

        # Check step has an id
        if "id" in step:
            step_score += 0.2

        # Check goto has a url in args
        if op == "goto":
            args = step.get("args", {})
            if isinstance(args, dict) and "url" in args:
                step_score += 0.1
        else:
            step_score += 0.1

        scores.append(step_score)

    return sum(scores) / len(scores) if scores else 0.0


def score_replay_determinism(workflow: dict) -> float:
    """Check workflow avoids non-deterministic patterns.

    Penalizes:
    - Steps missing targetKey for ops that need them
    - Steps missing expect assertions
    - Steps that rely on dynamic/non-deterministic data
    Returns 0.0-1.0.
    """
    steps = workflow.get("steps", [])
    if not isinstance(steps, list) or len(steps) == 0:
        return 0.0

    scores = []
    ops_needing_target = {"act_cached", "act_template", "extract"}
    ops_needing_expect = {"act_cached", "act_template", "extract", "goto"}

    for step in steps:
        if not isinstance(step, dict):
            scores.append(0.0)
            continue

        step_score = 1.0
        op = step.get("op", "")
        target_key = step.get("targetKey") or step.get("target_key")

        # Penalize missing targetKey for ops that need it
        if op in ops_needing_target and not target_key:
            step_score -= 0.4

        # Penalize missing expect for ops that benefit from assertions
        if op in ops_needing_expect:
            expect = step.get("expect")
            if not expect:
                step_score -= 0.3

        # Penalize checkpoint without message
        if op == "checkpoint":
            args = step.get("args", {})
            if not isinstance(args, dict) or "message" not in args:
                step_score -= 0.2

        scores.append(max(0.0, step_score))

    return sum(scores) / len(scores) if scores else 0.0


def score_token_cost(recipe: dict) -> float:
    """Estimate normalized token cost based on step count, extract count, etc.

    Returns 0.0-1.0 (lower is better -- fewer estimated tokens used).
    """
    workflow = recipe.get("workflow", {})
    steps = workflow.get("steps", []) if isinstance(workflow, dict) else []

    if not steps:
        return 0.0

    # Count step types that consume more tokens
    step_count = len(steps)
    extract_count = sum(1 for s in steps if isinstance(s, dict) and s.get("op") == "extract")
    choose_count = sum(1 for s in steps if isinstance(s, dict) and s.get("op") == "choose")
    checkpoint_count = sum(1 for s in steps if isinstance(s, dict) and s.get("op") == "checkpoint")

    # More steps = higher cost
    step_cost = min(step_count / 20.0, 1.0)

    # Extracts are expensive (LLM usage potential)
    extract_cost = min(extract_count / 5.0, 1.0)

    # Choices add moderate cost
    choose_cost = min(choose_count / 3.0, 1.0)

    # Checkpoints are low cost but add overhead
    checkpoint_cost = min(checkpoint_count / 5.0, 1.0)

    # Weighted combination
    cost = 0.4 * step_cost + 0.3 * extract_cost + 0.2 * choose_cost + 0.1 * checkpoint_cost

    return min(max(cost, 0.0), 1.0)


def _camel_case(snake: str) -> str:
    """Convert snake_case to camelCase."""
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])
