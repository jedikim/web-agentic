"""
DSPy signatures for the authoring service programs.

Each signature defines the input/output contract for a DSPy program.
The LLM fills in output fields given the input fields.
"""

import dspy


class IntentToWorkflowSignature(dspy.Signature):
    """Convert user automation goal into structured workflow + actions + selectors JSON.

    Given a user's automation goal and optional procedure/domain/context,
    produce valid JSON for workflow steps, action references, and selector entries.
    The workflow_json must contain a 'steps' array where each step has 'id', 'op', and optional fields.
    The actions_json must map target keys to action entries with selector/description/method.
    The selectors_json must map target keys to selector entries with primary/fallbacks/strategy.
    """

    goal: str = dspy.InputField(desc="User's automation goal in natural language")
    procedure: str = dspy.InputField(desc="Step-by-step procedure description", default="")
    domain: str = dspy.InputField(desc="Target website domain", default="")
    context: str = dspy.InputField(desc="Additional context as JSON string", default="{}")
    workflow_json: str = dspy.OutputField(
        desc="Valid JSON object with 'id' (string) and 'steps' array. "
        "Each step has 'id' (string), 'op' (one of: goto, act_cached, extract, choose, checkpoint, wait), "
        "'targetKey' (optional string), 'args' (optional object), 'expect' (optional array of {kind, value})"
    )
    actions_json: str = dspy.OutputField(
        desc="Valid JSON object mapping target keys to action entries. "
        "Each entry has 'instruction' (string), 'preferred' with 'selector' (CSS), "
        "'description' (string), 'method' (click|fill|type|press|focus), "
        "'arguments' (optional string array), and 'observedAt' (ISO datetime string)"
    )
    selectors_json: str = dspy.OutputField(
        desc="Valid JSON object mapping target keys to selector entries. "
        "Each entry has 'primary' (CSS selector string), "
        "'fallbacks' (array of CSS selector strings), 'strategy' (css|xpath|role|testid)"
    )


class IntentToPolicySignature(dspy.Signature):
    """Convert user constraints into policy DSL JSON.

    Given a selection/filtering goal with hard constraints and soft preferences,
    produce valid policy JSON with hard filters, score rules, tie-breaking, and pick strategy.
    """

    goal: str = dspy.InputField(desc="User's selection or filtering goal")
    constraints: str = dspy.InputField(desc="Hard constraints as JSON list of {field, op, value}")
    preferences: str = dspy.InputField(desc="Soft preferences for scoring as natural language")
    policy_json: str = dspy.OutputField(
        desc="Valid JSON object with 'hard' (array of {field, op, value} conditions), "
        "'score' (array of {when: {field, op, value}, add: number} rules), "
        "'tie_break' (array of sort keys like 'price_asc' or 'label_asc'), "
        "'pick' (one of: argmax, argmin, first)"
    )


class PatchPlannerSignature(dspy.Signature):
    """Generate minimal patch to fix an automation failure.

    Given failure context including the failed step, error type, URL, selector, and DOM snippet,
    produce a minimal patch with operations to fix the failure.
    """

    step_id: str = dspy.InputField(desc="ID of the failed workflow step")
    error_type: str = dspy.InputField(desc="Error classification: TargetNotFound, ExpectationFailed, ExtractionEmpty, NotActionable")
    url: str = dspy.InputField(desc="Current page URL where failure occurred")
    failed_selector: str = dspy.InputField(desc="CSS selector that failed", default="")
    dom_snippet: str = dspy.InputField(desc="DOM HTML around the failure point", default="")
    patch_json: str = dspy.OutputField(
        desc="Valid JSON object with 'ops' array and 'reason' string. "
        "Each op has 'op' (actions.replace|actions.add|selectors.replace|selectors.add|"
        "workflow.update_expect|policies.update), 'key' or 'step' (string), and 'value' (object)"
    )
