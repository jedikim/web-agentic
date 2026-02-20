"""Tests for GEPA eval harness."""

import pytest

from app.gepa.eval_harness import PROMOTION_THRESHOLD, EvalHarness, EvalResult


def _high_quality_recipe():
    return {
        "workflow": {
            "id": "test_flow",
            "steps": [
                {
                    "id": "open",
                    "op": "goto",
                    "args": {"url": "https://example.com"},
                    "expect": [{"kind": "url_contains", "value": "example.com"}],
                },
                {
                    "id": "login",
                    "op": "act_cached",
                    "targetKey": "login.submit",
                    "expect": [{"kind": "url_contains", "value": "/dashboard"}],
                },
                {
                    "id": "done",
                    "op": "checkpoint",
                    "args": {"message": "Done?"},
                },
            ],
        },
        "actions": {},
        "selectors": {},
        "policies": {},
        "fingerprints": {},
    }


def _low_quality_recipe():
    return {
        "workflow": {
            "steps": [
                {"op": "invalid_op"},
            ],
        },
    }


class TestEvalHarness:
    def test_high_quality_recipe_passes(self):
        harness = EvalHarness()
        result = harness.evaluate(_high_quality_recipe())
        assert result.total_score > 0.5
        assert result.schema_validity > 0.5
        assert result.dry_run_success > 0.5
        assert result.replay_determinism > 0.5

    def test_low_quality_recipe_fails(self):
        harness = EvalHarness()
        result = harness.evaluate(_low_quality_recipe())
        assert result.total_score < PROMOTION_THRESHOLD
        assert result.passed is False

    def test_empty_recipe_scores_zero(self):
        harness = EvalHarness()
        result = harness.evaluate({})
        assert result.total_score == 0.0
        assert result.passed is False

    def test_custom_threshold(self):
        harness = EvalHarness(threshold=0.1)
        result = harness.evaluate(_high_quality_recipe())
        assert result.passed is True

        harness_high = EvalHarness(threshold=0.999)
        result_high = harness_high.evaluate(_high_quality_recipe())
        assert result_high.passed is False

    def test_score_formula_weights(self):
        harness = EvalHarness()
        result = harness.evaluate(_high_quality_recipe())
        expected = (
            0.45 * result.dry_run_success
            + 0.25 * result.schema_validity
            + 0.20 * result.replay_determinism
            - 0.10 * result.token_cost
        )
        expected = max(0.0, min(1.0, expected))
        assert abs(result.total_score - expected) < 0.001

    def test_evaluate_batch(self):
        harness = EvalHarness()
        recipes = [_high_quality_recipe(), _low_quality_recipe()]
        specs = [{"id": "spec1"}, {"id": "spec2"}]
        results = harness.evaluate_batch(recipes, specs)
        assert len(results) == 2
        assert results[0].total_score > results[1].total_score

    def test_average_score(self):
        harness = EvalHarness()
        r1 = EvalResult(total_score=0.8)
        r2 = EvalResult(total_score=0.6)
        assert harness.average_score([r1, r2]) == pytest.approx(0.7)

    def test_average_score_empty(self):
        harness = EvalHarness()
        assert harness.average_score([]) == 0.0

    def test_eval_result_details(self):
        harness = EvalHarness()
        spec = {"id": "test-spec"}
        result = harness.evaluate(_high_quality_recipe(), spec)
        assert result.details["task_spec_id"] == "test-spec"
        assert result.details["threshold"] == PROMOTION_THRESHOLD
