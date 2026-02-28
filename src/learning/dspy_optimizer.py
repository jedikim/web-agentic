"""DSPy Prompt Optimizer — placeholder for MIPROv2 optimization.

This module provides a lightweight placeholder implementation for prompt
optimization.  It does NOT import ``dspy`` (optional dependency).  The
real DSPy integration will replace the internals in a future phase.

Currently it:
- Tracks optimization history (prompt_name, version, score, timestamp)
- Registers new prompt versions with minor adjustments
- Evaluates test cases by checking if expected output is present in actual output

Usage::

    optimizer = PromptOptimizer(prompt_manager)
    new_version = await optimizer.optimize("plan_steps", examples)
    accuracy = await optimizer.evaluate("plan_steps", test_cases)
    history = optimizer.get_optimization_history()
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from string import Template
from typing import Any

from src.ai.prompt_manager import PromptManager

logger = logging.getLogger(__name__)


class PromptOptimizer:
    """Placeholder prompt optimizer for future DSPy MIPROv2 integration.

    Args:
        prompt_manager: The prompt manager to read/write prompt versions.
    """

    def __init__(self, prompt_manager: PromptManager) -> None:
        self._prompt_manager = prompt_manager
        self._history: list[dict[str, Any]] = []

    async def optimize(
        self,
        prompt_name: str,
        examples: list[dict],
        metric_fn: Callable | None = None,
    ) -> str:
        """Optimize a prompt using training examples.

        Currently a placeholder that creates a new prompt version by
        appending training guidance derived from the examples.

        Args:
            prompt_name: Name of the prompt template to optimize.
            examples: Training examples, each with ``"input"`` and
                ``"expected_output"`` keys.
            metric_fn: Optional metric function (reserved for DSPy).

        Returns:
            The new version identifier (e.g., ``"v2"``).

        Raises:
            KeyError: If the prompt_name is not registered.
        """
        # Retrieve the current prompt template
        current_prompt = self._prompt_manager.get_prompt(prompt_name)

        # Determine new version number
        all_prompts = self._prompt_manager.list_prompts()
        existing_versions = all_prompts.get(prompt_name, [])
        version_num = len(existing_versions) + 1
        new_version = f"v{version_num}"

        # Build optimized prompt (placeholder: append example guidance)
        if examples:
            example_hints = "\n\nOptimized with training examples:\n"
            for i, ex in enumerate(examples[:3], 1):  # Limit to 3 examples
                inp = ex.get("input", "")
                expected = ex.get("expected_output", "")
                if inp and expected:
                    example_hints += (
                        f"- Example {i}: For input like '{inp}', "
                        f"produce output similar to '{expected}'\n"
                    )
            optimized_prompt = current_prompt + example_hints
        else:
            optimized_prompt = current_prompt

        # Register the new version
        self._prompt_manager.register_prompt(prompt_name, optimized_prompt, new_version)

        # Evaluate if metric_fn is provided
        score = 0.0
        if metric_fn is not None and examples:
            try:
                score = metric_fn(examples)
            except Exception:
                logger.warning("Metric function failed during optimization")
                score = 0.0
        elif examples:
            # Simple heuristic score based on example count
            score = min(1.0, len(examples) / 10.0)

        # Record in history
        self._history.append(
            {
                "prompt_name": prompt_name,
                "version": new_version,
                "score": score,
                "timestamp": datetime.now(UTC).isoformat(),
                "num_examples": len(examples),
            }
        )

        logger.info(
            "Optimized prompt %r to %s (score=%.2f, examples=%d)",
            prompt_name,
            new_version,
            score,
            len(examples),
        )

        return new_version

    async def evaluate(
        self, prompt_name: str, test_cases: list[dict]
    ) -> float:
        """Evaluate a prompt against test cases.

        Simple evaluation: checks if the expected output substring is
        present in the rendered prompt output for each test case.

        Args:
            prompt_name: Name of the prompt template to evaluate.
            test_cases: Each dict should have ``"input"`` (dict of template
                variables) and ``"expected_output"`` (string to search for).

        Returns:
            Accuracy score between 0.0 and 1.0.
        """
        if not test_cases:
            return 1.0

        correct = 0
        for case in test_cases:
            input_vars = case.get("input", {})
            expected = case.get("expected_output", "")

            if not isinstance(input_vars, dict):
                input_vars = {}

            try:
                # Get the raw template and substitute manually to avoid
                # parameter name collisions with get_prompt's own args
                raw_template = self._prompt_manager.get_prompt(prompt_name)
                rendered = Template(raw_template).safe_substitute(**input_vars)
                if expected and expected in rendered:
                    correct += 1
                elif not expected:
                    # No expected output means we just check rendering works
                    correct += 1
            except Exception:
                logger.debug("Test case failed for prompt %r", prompt_name)

        accuracy = correct / len(test_cases)

        logger.info(
            "Evaluated prompt %r: %.1f%% accuracy (%d/%d)",
            prompt_name,
            accuracy * 100,
            correct,
            len(test_cases),
        )

        return accuracy

    def get_optimization_history(self) -> list[dict]:
        """Return the full optimization history.

        Returns:
            List of dicts with keys: prompt_name, version, score,
            timestamp, num_examples.
        """
        return list(self._history)
