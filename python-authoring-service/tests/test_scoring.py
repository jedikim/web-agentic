"""Tests for GEPA scoring functions."""

import pytest

from app.gepa.scoring import (
    score_dry_run_success,
    score_replay_determinism,
    score_schema_validity,
    score_token_cost,
)


def _make_recipe(steps=None, actions=None, selectors=None, policies=None, fingerprints=None):
    return {
        "workflow": {
            "id": "test_flow",
            "steps": steps or [],
        },
        "actions": actions if actions is not None else {},
        "selectors": selectors if selectors is not None else {},
        "policies": policies if policies is not None else {},
        "fingerprints": fingerprints if fingerprints is not None else {},
    }


class TestSchemaValidity:
    def test_valid_recipe_scores_high(self):
        recipe = _make_recipe(
            steps=[
                {"id": "open", "op": "goto", "args": {"url": "https://example.com"}},
                {"id": "login", "op": "act_cached", "targetKey": "login.submit"},
            ],
        )
        score = score_schema_validity(recipe)
        assert score > 0.8

    def test_empty_recipe_scores_zero(self):
        score = score_schema_validity({})
        assert score == 0.0

    def test_missing_workflow_scores_low(self):
        recipe = {"actions": {}, "selectors": {}, "policies": {}, "fingerprints": {}}
        score = score_schema_validity(recipe)
        assert score < 0.7

    def test_missing_steps_scores_low(self):
        recipe = _make_recipe()  # empty steps
        score = score_schema_validity(recipe)
        assert score <= 0.8

    def test_invalid_step_structure(self):
        recipe = _make_recipe(steps=[{"no_id": True}])
        score = score_schema_validity(recipe)
        assert score <= 0.9

    def test_valid_actions_entry(self):
        recipe = _make_recipe(
            steps=[{"id": "s1", "op": "goto"}],
            actions={
                "login.submit": {
                    "instruction": "click login",
                    "preferred": {"selector": "//button", "method": "click"},
                    "observedAt": "2026-01-01",
                }
            },
        )
        score = score_schema_validity(recipe)
        assert score > 0.7

    def test_invalid_actions_entry(self):
        recipe = _make_recipe(
            steps=[{"id": "s1", "op": "goto"}],
            actions={"bad": {"no_instruction": True}},
        )
        score_valid = score_schema_validity(_make_recipe(steps=[{"id": "s1", "op": "goto"}]))
        score_invalid = score_schema_validity(recipe)
        assert score_invalid < score_valid


class TestDryRunSuccess:
    def test_valid_steps_score_high(self):
        workflow = {
            "steps": [
                {"id": "open", "op": "goto", "args": {"url": "https://example.com"}},
                {"id": "login", "op": "act_cached", "targetKey": "login.submit"},
            ]
        }
        score = score_dry_run_success(workflow)
        assert score > 0.7

    def test_empty_steps_score_zero(self):
        score = score_dry_run_success({"steps": []})
        assert score == 0.0

    def test_invalid_op_scores_zero_for_step(self):
        workflow = {
            "steps": [
                {"id": "bad", "op": "invalid_operation"},
            ]
        }
        score = score_dry_run_success(workflow)
        assert score == 0.0

    def test_missing_required_fields_lowers_score(self):
        # goto without args
        workflow = {
            "steps": [
                {"id": "open", "op": "goto"},
            ]
        }
        full_score = score_dry_run_success({
            "steps": [
                {"id": "open", "op": "goto", "args": {"url": "https://x.com"}},
            ]
        })
        partial_score = score_dry_run_success(workflow)
        assert partial_score < full_score

    def test_no_workflow(self):
        score = score_dry_run_success({})
        assert score == 0.0


class TestReplayDeterminism:
    def test_deterministic_workflow_scores_high(self):
        workflow = {
            "steps": [
                {"id": "open", "op": "goto", "args": {"url": "https://example.com"},
                 "expect": [{"kind": "url_contains", "value": "example.com"}]},
                {"id": "login", "op": "act_cached", "targetKey": "login.submit",
                 "expect": [{"kind": "url_contains", "value": "/dashboard"}]},
            ]
        }
        score = score_replay_determinism(workflow)
        assert score >= 0.9

    def test_missing_target_key_penalized(self):
        workflow = {
            "steps": [
                {"id": "login", "op": "act_cached"},  # missing targetKey
            ]
        }
        score = score_replay_determinism(workflow)
        assert score < 0.7

    def test_missing_expect_penalized(self):
        workflow = {
            "steps": [
                {"id": "open", "op": "goto", "args": {"url": "https://example.com"}},
                # no expect
            ]
        }
        score = score_replay_determinism(workflow)
        assert score < 1.0

    def test_empty_steps(self):
        score = score_replay_determinism({"steps": []})
        assert score == 0.0

    def test_checkpoint_without_message(self):
        workflow = {
            "steps": [
                {"id": "cp", "op": "checkpoint", "args": {}},  # no message
            ]
        }
        score = score_replay_determinism(workflow)
        assert score < 1.0


class TestTokenCost:
    def test_minimal_recipe_low_cost(self):
        recipe = _make_recipe(steps=[
            {"id": "open", "op": "goto", "args": {"url": "https://example.com"}},
        ])
        score = score_token_cost(recipe)
        assert score < 0.3

    def test_many_extracts_higher_cost(self):
        steps = [{"id": f"e{i}", "op": "extract", "targetKey": f"data_{i}"} for i in range(5)]
        recipe = _make_recipe(steps=steps)
        score = score_token_cost(recipe)
        assert score > 0.3

    def test_empty_recipe(self):
        score = score_token_cost({})
        assert score == 0.0

    def test_large_workflow_high_cost(self):
        steps = [{"id": f"s{i}", "op": "act_cached", "targetKey": f"t{i}"} for i in range(20)]
        recipe = _make_recipe(steps=steps)
        score = score_token_cost(recipe)
        assert score > 0.3
