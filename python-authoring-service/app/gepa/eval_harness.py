"""Evaluation harness for GEPA optimization loop."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.gepa.scoring import (
    score_dry_run_success,
    score_replay_determinism,
    score_schema_validity,
    score_token_cost,
)

PROMOTION_THRESHOLD = 0.82


@dataclass
class EvalResult:
    schema_validity: float = 0.0
    dry_run_success: float = 0.0
    replay_determinism: float = 0.0
    token_cost: float = 0.0
    total_score: float = 0.0
    passed: bool = False
    details: dict = field(default_factory=dict)


class EvalHarness:
    """Evaluate generated recipes against quality criteria.

    Score formula:
        score = 0.45 * dry_run_success
              + 0.25 * schema_validity
              + 0.20 * replay_determinism
              - 0.10 * token_cost

    Promotion threshold: 0.82
    """

    def __init__(self, threshold: float = PROMOTION_THRESHOLD):
        self.threshold = threshold

    def evaluate(self, recipe_json: dict, task_spec: dict | None = None) -> EvalResult:
        """Compute weighted score for a generated recipe."""
        workflow = recipe_json.get("workflow", {})
        if isinstance(workflow, dict):
            workflow_data = workflow
        else:
            workflow_data = {}

        sv = score_schema_validity(recipe_json)
        dr = score_dry_run_success(workflow_data)
        rd = score_replay_determinism(workflow_data)
        tc = score_token_cost(recipe_json)

        total = 0.45 * dr + 0.25 * sv + 0.20 * rd - 0.10 * tc
        total = max(0.0, min(1.0, total))

        return EvalResult(
            schema_validity=sv,
            dry_run_success=dr,
            replay_determinism=rd,
            token_cost=tc,
            total_score=total,
            passed=total >= self.threshold,
            details={
                "task_spec_id": task_spec.get("id") if task_spec else None,
                "threshold": self.threshold,
            },
        )

    def evaluate_batch(
        self, recipes: list[dict], task_specs: list[dict]
    ) -> list[EvalResult]:
        """Evaluate multiple recipes against corresponding task specs."""
        results = []
        for i, recipe in enumerate(recipes):
            spec = task_specs[i] if i < len(task_specs) else None
            results.append(self.evaluate(recipe, spec))
        return results

    def average_score(self, results: list[EvalResult]) -> float:
        """Compute average total score across results."""
        if not results:
            return 0.0
        return sum(r.total_score for r in results) / len(results)
