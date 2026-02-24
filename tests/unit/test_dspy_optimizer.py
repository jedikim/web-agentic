"""Tests for PromptOptimizer — placeholder DSPy prompt optimization.

Covers optimize, evaluate, history tracking, and edge cases.
"""
from __future__ import annotations

import pytest

from src.ai.prompt_manager import PromptManager
from src.learning.dspy_optimizer import PromptOptimizer


# ── Fixtures ────────────────────────────────────────


@pytest.fixture
def prompt_manager() -> PromptManager:
    """Create a fresh PromptManager with built-in prompts."""
    return PromptManager()


@pytest.fixture
def optimizer(prompt_manager: PromptManager) -> PromptOptimizer:
    """Create a PromptOptimizer with the prompt manager."""
    return PromptOptimizer(prompt_manager)


# ── Optimize ────────────────────────────────────────


class TestOptimize:
    """Tests for the optimize method."""

    @pytest.mark.asyncio
    async def test_returns_new_version(self, optimizer: PromptOptimizer) -> None:
        """Should return a new version string."""
        examples = [
            {"input": "search for laptops", "expected_output": "step_1"},
        ]
        version = await optimizer.optimize("plan_steps", examples)
        assert version.startswith("v")
        assert version != "v1"

    @pytest.mark.asyncio
    async def test_registers_new_version(
        self, optimizer: PromptOptimizer, prompt_manager: PromptManager
    ) -> None:
        """Should register the new version with the prompt manager."""
        examples = [
            {"input": "click button", "expected_output": "click"},
        ]
        version = await optimizer.optimize("plan_steps", examples)

        prompts = prompt_manager.list_prompts()
        assert version in prompts["plan_steps"]

    @pytest.mark.asyncio
    async def test_optimized_prompt_contains_examples(
        self, optimizer: PromptOptimizer, prompt_manager: PromptManager
    ) -> None:
        """The optimized prompt should contain guidance from examples."""
        examples = [
            {"input": "navigate to page", "expected_output": "goto"},
        ]
        version = await optimizer.optimize("plan_steps", examples)
        prompt = prompt_manager.get_prompt("plan_steps", version=version)
        assert "navigate to page" in prompt
        assert "goto" in prompt

    @pytest.mark.asyncio
    async def test_optimize_with_empty_examples(
        self, optimizer: PromptOptimizer
    ) -> None:
        """Should still produce a new version with empty examples."""
        version = await optimizer.optimize("plan_steps", [])
        assert version.startswith("v")

    @pytest.mark.asyncio
    async def test_optimize_unknown_prompt_raises(
        self, optimizer: PromptOptimizer
    ) -> None:
        """Should raise KeyError for unknown prompt name."""
        with pytest.raises(KeyError):
            await optimizer.optimize("nonexistent_prompt", [])

    @pytest.mark.asyncio
    async def test_optimize_with_metric_fn(
        self, optimizer: PromptOptimizer
    ) -> None:
        """Should use the metric function if provided."""
        examples = [
            {"input": "test", "expected_output": "result"},
        ]

        def metric(exs: list) -> float:
            return 0.99

        version = await optimizer.optimize("plan_steps", examples, metric_fn=metric)
        history = optimizer.get_optimization_history()
        assert history[-1]["score"] == 0.99

    @pytest.mark.asyncio
    async def test_multiple_optimizations_increment_version(
        self, optimizer: PromptOptimizer
    ) -> None:
        """Sequential optimizations should produce incrementing versions."""
        examples = [{"input": "a", "expected_output": "b"}]

        v1 = await optimizer.optimize("plan_steps", examples)
        v2 = await optimizer.optimize("plan_steps", examples)

        assert v1 != v2
        # Both should be valid version strings
        assert v1.startswith("v")
        assert v2.startswith("v")


# ── Evaluate ────────────────────────────────────────


class TestEvaluate:
    """Tests for the evaluate method."""

    @pytest.mark.asyncio
    async def test_calculates_accuracy(
        self, optimizer: PromptOptimizer, prompt_manager: PromptManager
    ) -> None:
        """Should return accuracy based on expected output matching."""
        # Register a simple prompt
        prompt_manager.register_prompt(
            "test_prompt", "Hello $name, welcome to $place", "v1"
        )

        test_cases = [
            {"input": {"name": "Alice", "place": "Wonderland"}, "expected_output": "Alice"},
            {"input": {"name": "Bob", "place": "Office"}, "expected_output": "Bob"},
            {"input": {"name": "Charlie", "place": "Park"}, "expected_output": "MISSING_VALUE"},
        ]

        accuracy = await optimizer.evaluate("test_prompt", test_cases)
        # 2 out of 3 should match (Alice and Bob are in the output)
        assert abs(accuracy - 2.0 / 3.0) < 0.01

    @pytest.mark.asyncio
    async def test_evaluate_with_no_test_cases(
        self, optimizer: PromptOptimizer
    ) -> None:
        """Should return 1.0 when there are no test cases."""
        accuracy = await optimizer.evaluate("plan_steps", [])
        assert accuracy == 1.0

    @pytest.mark.asyncio
    async def test_evaluate_all_pass(
        self, optimizer: PromptOptimizer, prompt_manager: PromptManager
    ) -> None:
        """Should return 1.0 when all test cases pass."""
        prompt_manager.register_prompt("greet", "Hello $name!", "v1")

        test_cases = [
            {"input": {"name": "Alice"}, "expected_output": "Hello Alice!"},
            {"input": {"name": "Bob"}, "expected_output": "Hello Bob!"},
        ]

        accuracy = await optimizer.evaluate("greet", test_cases)
        assert accuracy == 1.0

    @pytest.mark.asyncio
    async def test_evaluate_all_fail(
        self, optimizer: PromptOptimizer, prompt_manager: PromptManager
    ) -> None:
        """Should return 0.0 when no test cases pass."""
        prompt_manager.register_prompt("greet", "Hello $name!", "v1")

        test_cases = [
            {"input": {"name": "Alice"}, "expected_output": "WRONG_OUTPUT_1"},
            {"input": {"name": "Bob"}, "expected_output": "WRONG_OUTPUT_2"},
        ]

        accuracy = await optimizer.evaluate("greet", test_cases)
        assert accuracy == 0.0

    @pytest.mark.asyncio
    async def test_evaluate_with_no_expected(
        self, optimizer: PromptOptimizer, prompt_manager: PromptManager
    ) -> None:
        """Test cases without expected_output should count as passing."""
        prompt_manager.register_prompt("greet", "Hello $name!", "v1")

        test_cases = [
            {"input": {"name": "Alice"}},
            {"input": {"name": "Bob"}, "expected_output": ""},
        ]

        accuracy = await optimizer.evaluate("greet", test_cases)
        assert accuracy == 1.0


# ── Optimization History ────────────────────────────


class TestOptimizationHistory:
    """Tests for optimization history tracking."""

    @pytest.mark.asyncio
    async def test_empty_history(self, optimizer: PromptOptimizer) -> None:
        """Should start with empty history."""
        assert optimizer.get_optimization_history() == []

    @pytest.mark.asyncio
    async def test_history_records_entries(
        self, optimizer: PromptOptimizer
    ) -> None:
        """Should record entries on optimization."""
        examples = [{"input": "test", "expected_output": "out"}]
        await optimizer.optimize("plan_steps", examples)

        history = optimizer.get_optimization_history()
        assert len(history) == 1
        entry = history[0]
        assert entry["prompt_name"] == "plan_steps"
        assert "version" in entry
        assert "score" in entry
        assert "timestamp" in entry
        assert entry["num_examples"] == 1

    @pytest.mark.asyncio
    async def test_history_accumulates(
        self, optimizer: PromptOptimizer
    ) -> None:
        """Multiple optimizations should accumulate in history."""
        for i in range(3):
            await optimizer.optimize(
                "plan_steps",
                [{"input": f"input_{i}", "expected_output": f"out_{i}"}],
            )

        history = optimizer.get_optimization_history()
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_history_returns_copy(
        self, optimizer: PromptOptimizer
    ) -> None:
        """get_optimization_history should return a copy, not a reference."""
        await optimizer.optimize("plan_steps", [{"input": "x", "expected_output": "y"}])

        h1 = optimizer.get_optimization_history()
        h2 = optimizer.get_optimization_history()
        assert h1 == h2
        assert h1 is not h2
