"""GEPA self-improving prompt optimizer.

Runs an optimize loop:
1. Load current profile (signatures + instructions + few-shots)
2. Load task specs bank
3. Generate candidate recipes using DSPy programs
4. Evaluate candidates with eval harness
5. If score < threshold, reflect and improve prompts
6. Repeat until convergence or max rounds
7. Save promoted profile if score >= threshold (0.82)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.gepa.eval_harness import PROMOTION_THRESHOLD, EvalHarness, EvalResult
from app.storage.profiles_repo import ProfilesRepo
from app.storage.task_specs_repo import TaskSpecsRepo


@dataclass
class RoundResult:
    round_num: int
    score: float
    eval_result: EvalResult
    recipe: dict
    reflection: str | None = None


@dataclass
class OptimizationResult:
    profile_id: str
    rounds: int
    final_score: float
    promoted: bool
    promoted_version: int | None = None
    history: list[RoundResult] = field(default_factory=list)


# Type alias for the recipe generator function
RecipeGenerator = Callable[[dict, dict], dict]


def _default_recipe_generator(profile: dict, task_spec: dict) -> dict:
    """Default deterministic recipe generator for testing without a real LLM.

    Generates a well-formed recipe from the profile and task spec.
    """
    goal = task_spec.get("goal", "default task")
    domain = task_spec.get("domain", "example.com")
    procedure = task_spec.get("procedure", "")

    steps = [
        {
            "id": "open",
            "op": "goto",
            "args": {"url": f"https://{domain}"},
            "expect": [{"kind": "url_contains", "value": domain}],
        },
    ]

    # If procedure has steps, add them
    proc_steps = task_spec.get("procedure_steps", [])
    for i, ps in enumerate(proc_steps):
        target_key = ps.get("targetKey", f"step_{i}")
        steps.append({
            "id": f"step_{i}",
            "op": ps.get("op", "act_cached"),
            "targetKey": target_key,
            "expect": ps.get("expect", [{"kind": "selector_visible", "value": "body"}]),
        })

    steps.append({
        "id": "checkpoint_end",
        "op": "checkpoint",
        "args": {"message": f"Completed: {goal}. Verify results?"},
    })

    return {
        "workflow": {
            "id": f"{domain}_flow",
            "steps": steps,
        },
        "actions": {},
        "selectors": {},
        "policies": {},
        "fingerprints": {},
    }


def _default_reflector(profile: dict, eval_result: EvalResult, recipe: dict) -> dict:
    """Default reflection: adjust profile based on evaluation feedback.

    In deterministic mode, improves the profile by adding hints
    based on what scoring dimensions were weak.
    """
    updated = dict(profile)
    hints = updated.get("optimization_hints", [])

    if eval_result.schema_validity < 0.8:
        hints.append("ensure_all_schema_fields")
    if eval_result.dry_run_success < 0.8:
        hints.append("validate_op_types_and_required_fields")
    if eval_result.replay_determinism < 0.8:
        hints.append("add_targetKey_and_expect_to_all_steps")
    if eval_result.token_cost > 0.5:
        hints.append("reduce_extract_and_choose_steps")

    updated["optimization_hints"] = list(set(hints))
    updated["last_score"] = eval_result.total_score
    return updated


def _improved_recipe_generator(profile: dict, task_spec: dict) -> dict:
    """Generate an improved recipe based on optimization hints in the profile."""
    recipe = _default_recipe_generator(profile, task_spec)
    hints = profile.get("optimization_hints", [])

    workflow = recipe["workflow"]
    steps = workflow["steps"]

    if "add_targetKey_and_expect_to_all_steps" in hints:
        for step in steps:
            op = step.get("op", "")
            if op in ("act_cached", "act_template", "extract") and "targetKey" not in step:
                step["targetKey"] = f"{step['id']}.action"
            if op in ("act_cached", "act_template", "extract", "goto") and "expect" not in step:
                step["expect"] = [{"kind": "selector_visible", "value": "body"}]

    if "reduce_extract_and_choose_steps" in hints:
        steps = [s for s in steps if s.get("op") != "choose" or s.get("id") in ("choose",)]
        workflow["steps"] = steps

    return recipe


class GEPAOptimizer:
    """Self-improving prompt optimizer using GEPA methodology."""

    def __init__(
        self,
        profiles_repo: ProfilesRepo,
        task_specs_repo: TaskSpecsRepo,
        eval_harness: EvalHarness | None = None,
        recipe_generator: RecipeGenerator | None = None,
        reflector: Callable[[dict, EvalResult, dict], dict] | None = None,
    ):
        self.profiles_repo = profiles_repo
        self.task_specs_repo = task_specs_repo
        self.eval_harness = eval_harness or EvalHarness()
        self._generate_recipe = recipe_generator
        self._reflect = reflector or _default_reflector

    def optimize(
        self,
        profile_id: str,
        max_rounds: int = 5,
    ) -> OptimizationResult:
        """Run GEPA optimization loop.

        1. Load current profile
        2. Load task specs bank
        3. For each round: generate candidates, evaluate, reflect if needed
        4. If final score >= threshold, promote profile
        5. Return optimization result with full history
        """
        # Load profile
        profile = self.profiles_repo.get(profile_id)
        if profile is None:
            profile = {"id": profile_id, "version": 0}
            self.profiles_repo.save(profile_id, profile)

        # Load task specs
        task_specs = self.task_specs_repo.get_specs()
        if not task_specs:
            # Use a minimal default spec for testing
            task_specs = [{"id": "default", "goal": "test", "domain": "example.com"}]

        history: list[RoundResult] = []
        best_score = 0.0
        best_recipe: dict = {}

        for round_num in range(1, max_rounds + 1):
            # Determine which generator to use
            generator = self._generate_recipe
            if generator is None:
                if profile.get("optimization_hints"):
                    generator = _improved_recipe_generator
                else:
                    generator = _default_recipe_generator

            # Generate and evaluate against all task specs
            round_results: list[EvalResult] = []
            round_recipes: list[dict] = []

            for spec in task_specs:
                recipe = generator(profile, spec)
                result = self.eval_harness.evaluate(recipe, spec)
                round_results.append(result)
                round_recipes.append(recipe)

            # Average score across all specs
            avg_score = self.eval_harness.average_score(round_results)

            # Pick the best recipe from this round
            best_idx = max(range(len(round_results)), key=lambda i: round_results[i].total_score)
            round_recipe = round_recipes[best_idx]
            round_eval = round_results[best_idx]

            reflection = None

            if avg_score >= self.eval_harness.threshold:
                # Passed -- record and stop
                history.append(RoundResult(
                    round_num=round_num,
                    score=avg_score,
                    eval_result=round_eval,
                    recipe=round_recipe,
                ))
                best_score = avg_score
                best_recipe = round_recipe
                break

            # Reflect and improve
            profile = self._reflect(profile, round_eval, round_recipe)
            self.profiles_repo.save(profile_id, profile)
            reflection = f"Round {round_num}: score={avg_score:.3f}, improving based on hints={profile.get('optimization_hints', [])}"

            history.append(RoundResult(
                round_num=round_num,
                score=avg_score,
                eval_result=round_eval,
                recipe=round_recipe,
                reflection=reflection,
            ))

            if avg_score > best_score:
                best_score = avg_score
                best_recipe = round_recipe

        # Determine if we should promote
        promoted = best_score >= self.eval_harness.threshold
        promoted_version = None

        if promoted:
            # Save best recipe into profile
            profile["best_recipe"] = best_recipe
            profile["best_score"] = best_score
            self.profiles_repo.save(profile_id, profile)

            # Promote to versioned copy
            versions = self.profiles_repo.list_versions(profile_id)
            next_version = max(versions, default=0) + 1
            self.profiles_repo.promote(profile_id, next_version)
            promoted_version = next_version

        return OptimizationResult(
            profile_id=profile_id,
            rounds=len(history),
            final_score=best_score,
            promoted=promoted,
            promoted_version=promoted_version,
            history=history,
        )
