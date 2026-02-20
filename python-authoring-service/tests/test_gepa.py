"""Tests for GEPA optimizer."""

import tempfile
from pathlib import Path

import pytest

from app.gepa.eval_harness import EvalHarness, EvalResult
from app.gepa.optimizer import (
    GEPAOptimizer,
    OptimizationResult,
    _default_recipe_generator,
    _improved_recipe_generator,
)
from app.storage.profiles_repo import ProfilesRepo
from app.storage.task_specs_repo import TaskSpecsRepo


@pytest.fixture
def tmp_dirs():
    with tempfile.TemporaryDirectory() as profiles_dir, tempfile.TemporaryDirectory() as specs_dir:
        yield profiles_dir, specs_dir


@pytest.fixture
def repos(tmp_dirs):
    profiles_dir, specs_dir = tmp_dirs
    profiles = ProfilesRepo(base_dir=profiles_dir)
    specs = TaskSpecsRepo(base_dir=specs_dir)
    return profiles, specs


class TestDefaultRecipeGenerator:
    def test_generates_valid_recipe(self):
        profile = {"id": "test"}
        spec = {"goal": "book flight", "domain": "airline.com"}
        recipe = _default_recipe_generator(profile, spec)
        assert "workflow" in recipe
        assert "actions" in recipe
        assert "selectors" in recipe
        assert "policies" in recipe
        assert "fingerprints" in recipe
        assert len(recipe["workflow"]["steps"]) >= 2

    def test_includes_procedure_steps(self):
        profile = {"id": "test"}
        spec = {
            "goal": "login",
            "domain": "example.com",
            "procedure_steps": [
                {"op": "act_cached", "targetKey": "login.submit"},
                {"op": "extract", "targetKey": "data.result"},
            ],
        }
        recipe = _default_recipe_generator(profile, spec)
        steps = recipe["workflow"]["steps"]
        # goto + 2 procedure steps + checkpoint
        assert len(steps) == 4


class TestImprovedRecipeGenerator:
    def test_adds_target_keys_when_hinted(self):
        profile = {"id": "test", "optimization_hints": ["add_targetKey_and_expect_to_all_steps"]}
        spec = {"goal": "test", "domain": "example.com"}
        recipe = _improved_recipe_generator(profile, spec)
        steps = recipe["workflow"]["steps"]
        for step in steps:
            op = step.get("op")
            if op in ("act_cached", "act_template", "extract"):
                assert "targetKey" in step


class TestGEPAOptimizer:
    def test_optimize_creates_profile_if_missing(self, repos):
        profiles, specs = repos
        harness = EvalHarness(threshold=0.01)  # very low threshold
        optimizer = GEPAOptimizer(profiles, specs, harness)
        result = optimizer.optimize("new-profile", max_rounds=1)
        assert result.profile_id == "new-profile"
        assert profiles.get("new-profile") is not None

    def test_optimize_promotes_on_high_score(self, repos):
        profiles, specs = repos
        profiles.save("prof-1", {"id": "prof-1", "version": 0})
        specs.add_spec({"id": "spec-1", "goal": "test", "domain": "example.com"})

        # Use very low threshold so default generator passes
        harness = EvalHarness(threshold=0.01)
        optimizer = GEPAOptimizer(profiles, specs, harness)
        result = optimizer.optimize("prof-1", max_rounds=3)

        assert result.promoted is True
        assert result.promoted_version == 1
        assert result.final_score > 0.0
        assert len(result.history) >= 1

    def test_optimize_runs_multiple_rounds(self, repos):
        profiles, specs = repos
        profiles.save("prof-2", {"id": "prof-2", "version": 0})
        specs.add_spec({"id": "spec-1", "goal": "test", "domain": "example.com"})

        # High threshold forces reflection rounds
        harness = EvalHarness(threshold=0.999)
        optimizer = GEPAOptimizer(profiles, specs, harness)
        result = optimizer.optimize("prof-2", max_rounds=3)

        assert result.promoted is False
        assert result.rounds == 3
        assert len(result.history) == 3
        # Check that reflections were recorded
        assert result.history[0].reflection is not None

    def test_optimize_with_custom_generator(self, repos):
        profiles, specs = repos
        profiles.save("prof-3", {"id": "prof-3"})

        def perfect_generator(profile, spec):
            return {
                "workflow": {
                    "id": "perfect",
                    "steps": [
                        {
                            "id": "open",
                            "op": "goto",
                            "args": {"url": "https://example.com"},
                            "expect": [{"kind": "url_contains", "value": "example.com"}],
                        },
                        {
                            "id": "action",
                            "op": "act_cached",
                            "targetKey": "btn.click",
                            "expect": [{"kind": "selector_visible", "value": "#result"}],
                        },
                    ],
                },
                "actions": {},
                "selectors": {},
                "policies": {},
                "fingerprints": {},
            }

        harness = EvalHarness()
        optimizer = GEPAOptimizer(profiles, specs, harness, recipe_generator=perfect_generator)
        result = optimizer.optimize("prof-3", max_rounds=5)

        # A well-formed recipe should score well
        assert result.final_score > 0.5
        assert result.rounds >= 1

    def test_optimize_with_multiple_specs(self, repos):
        profiles, specs = repos
        profiles.save("prof-4", {"id": "prof-4"})
        specs.add_spec({"id": "spec-a", "goal": "task a", "domain": "a.com"})
        specs.add_spec({"id": "spec-b", "goal": "task b", "domain": "b.com"})

        harness = EvalHarness(threshold=0.01)
        optimizer = GEPAOptimizer(profiles, specs, harness)
        result = optimizer.optimize("prof-4", max_rounds=2)

        assert result.promoted is True
        assert result.final_score > 0.0

    def test_optimization_result_history_structure(self, repos):
        profiles, specs = repos
        profiles.save("prof-5", {"id": "prof-5"})

        harness = EvalHarness(threshold=0.999)
        optimizer = GEPAOptimizer(profiles, specs, harness)
        result = optimizer.optimize("prof-5", max_rounds=2)

        for rr in result.history:
            assert rr.round_num >= 1
            assert isinstance(rr.score, float)
            assert isinstance(rr.eval_result, EvalResult)
            assert isinstance(rr.recipe, dict)

    def test_promoted_version_increments(self, repos):
        profiles, specs = repos
        profiles.save("prof-6", {"id": "prof-6"})

        harness = EvalHarness(threshold=0.01)
        optimizer = GEPAOptimizer(profiles, specs, harness)

        result1 = optimizer.optimize("prof-6", max_rounds=1)
        assert result1.promoted_version == 1

        result2 = optimizer.optimize("prof-6", max_rounds=1)
        assert result2.promoted_version == 2
