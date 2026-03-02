"""Prompt optimization — heuristic or MetaPromptOptimizer refinement."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from src.kb.manager import KBManager
from src.llm.router import LLMRouter

logger = logging.getLogger(__name__)

_MIN_RUNS = 25

_HEURISTIC_PROMPT = """Analyze these web automation run results and suggest
improvements to the task prompt.

Domain: {domain}
URL pattern: {url_pattern}
Current prompts: {current_prompts}

Run history (last {run_count} runs, success_rate={success_rate:.1%}):
{run_summary}

Common failure types: {failure_summary}

Suggest an improved version of the task prompt that addresses the
most frequent failures. Focus on:
1. Clearer step descriptions
2. Better selector hints
3. Explicit wait conditions
4. Obstacle handling instructions

Respond with JSON: {{
  "improved_prompt": "<new prompt text>",
  "changes": ["<change 1>", "<change 2>"],
  "expected_improvement": "<brief explanation>"
}}"""


@dataclass
class OptimizationResult:
    """Outcome of prompt optimization."""

    optimized: bool = False
    new_prompt_version: int | None = None
    method: str = "none"  # "skip" | "heuristic" | "meta_prompt"
    score_improvement: float = 0.0
    detail: str = ""


class PromptOptimizer:
    """Optimize task prompts based on run history.

    Strategy:
        1. If fewer than MIN_RUNS runs exist, skip (insufficient data).
        2. If opik-optimizer is available, use MetaPromptOptimizer.
        3. Otherwise, use simple heuristic refinement via LLM.
    """

    def __init__(self, min_runs: int = _MIN_RUNS) -> None:
        self._min_runs = min_runs

    async def optimize(
        self,
        domain: str,
        url_pattern: str,
        kb: KBManager,
        llm: LLMRouter,
    ) -> OptimizationResult:
        """Run prompt optimization for a domain/url_pattern.

        Args:
            domain: Site domain.
            url_pattern: URL pattern in KB.
            kb: Knowledge Base manager.
            llm: LLM router for heuristic refinement.

        Returns:
            OptimizationResult describing what was done.
        """
        runs = _load_run_history(kb, domain)
        if len(runs) < self._min_runs:
            return OptimizationResult(
                optimized=False,
                method="skip",
                detail=(
                    f"Insufficient data: {len(runs)} runs "
                    f"(need {self._min_runs})"
                ),
            )

        # Try opik-optimizer first
        if _opik_available():
            return await self._optimize_meta(
                domain, url_pattern, kb, llm, runs,
            )

        # Fallback: heuristic LLM refinement
        return await self._optimize_heuristic(
            domain, url_pattern, kb, llm, runs,
        )

    async def _optimize_meta(
        self,
        domain: str,
        url_pattern: str,
        kb: KBManager,
        llm: LLMRouter,
        runs: list[dict[str, Any]],
    ) -> OptimizationResult:
        """Use opik MetaPromptOptimizer for data-driven optimization."""
        try:
            from opik_optimizer import MetaPromptOptimizer

            current_prompts = kb.load_prompts(domain, url_pattern) or {}
            task_prompt = current_prompts.get(
                "task", current_prompts.get("main", ""),
            )
            if not task_prompt:
                return OptimizationResult(
                    optimized=False,
                    method="meta_prompt",
                    detail="No task prompt found in KB.",
                )

            optimizer = MetaPromptOptimizer(
                model=llm.resolve_model("strong"),
            )
            # Build dataset from runs
            dataset = _runs_to_dataset(runs)
            result = optimizer.optimize(
                prompt=task_prompt,
                dataset=dataset,
            )

            new_prompt = getattr(result, "prompt", task_prompt)
            score_before = _compute_success_rate(runs)
            score_improvement = getattr(
                result, "score", score_before,
            ) - score_before

            # Save optimized prompt
            prompts = dict(current_prompts)
            prompts["task"] = new_prompt
            new_ver = kb.save_prompts(domain, url_pattern, prompts)

            return OptimizationResult(
                optimized=True,
                new_prompt_version=new_ver,
                method="meta_prompt",
                score_improvement=score_improvement,
                detail="Optimized via MetaPromptOptimizer.",
            )
        except Exception as exc:
            logger.warning("MetaPromptOptimizer failed: %s", exc)
            return await self._optimize_heuristic(
                domain, url_pattern, kb, llm, runs,
            )

    async def _optimize_heuristic(
        self,
        domain: str,
        url_pattern: str,
        kb: KBManager,
        llm: LLMRouter,
        runs: list[dict[str, Any]],
    ) -> OptimizationResult:
        """Simple LLM-based heuristic prompt refinement."""
        current_prompts = kb.load_prompts(domain, url_pattern) or {}
        success_rate = _compute_success_rate(runs)
        failures = [r for r in runs if not r.get("success", False)]
        failure_types = _summarize_failures(failures)
        run_summary = _summarize_runs(runs[-10:])

        prompt = _HEURISTIC_PROMPT.format(
            domain=domain,
            url_pattern=url_pattern,
            current_prompts=json.dumps(
                current_prompts, ensure_ascii=False,
            )[:1000],
            run_count=len(runs),
            success_rate=success_rate,
            run_summary=run_summary,
            failure_summary=failure_types,
        )

        raw = await llm.complete(
            "fast",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.2,
        )
        data = _parse_json_safe(raw)
        improved = data.get("improved_prompt", "")
        if not improved:
            return OptimizationResult(
                optimized=False,
                method="heuristic",
                detail="LLM did not produce an improved prompt.",
            )

        prompts = dict(current_prompts)
        prompts["task"] = improved
        new_ver = kb.save_prompts(domain, url_pattern, prompts)

        return OptimizationResult(
            optimized=True,
            new_prompt_version=new_ver,
            method="heuristic",
            score_improvement=0.0,
            detail=f"Heuristic refinement: {data.get('changes', [])}",
        )


# ── Helpers ──


def _load_run_history(
    kb: KBManager, domain: str,
) -> list[dict[str, Any]]:
    """Load run history from KB's runs.jsonl."""
    runs_file = kb.base_dir / domain / "history" / "runs.jsonl"
    if not runs_file.exists():
        return []
    results: list[dict[str, Any]] = []
    for line in runs_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return results


def _compute_success_rate(runs: list[dict[str, Any]]) -> float:
    """Compute success rate from run records."""
    if not runs:
        return 0.0
    ok = sum(1 for r in runs if r.get("success", False))
    return ok / len(runs)


def _summarize_failures(
    failures: list[dict[str, Any]],
) -> str:
    """Summarize failure types into a brief string."""
    counts: dict[str, int] = {}
    for f in failures:
        ft = f.get("failure_type", "unknown")
        counts[ft] = counts.get(ft, 0) + 1
    parts = [f"{k}={v}" for k, v in sorted(
        counts.items(), key=lambda x: -x[1],
    )]
    return ", ".join(parts) if parts else "none"


def _summarize_runs(runs: list[dict[str, Any]]) -> str:
    """Summarize recent runs into a compact string."""
    lines: list[str] = []
    for r in runs:
        status = "OK" if r.get("success") else "FAIL"
        ft = r.get("failure_type", "")
        task = r.get("task", "")[:60]
        lines.append(f"  [{status}] {task} {ft}")
    return "\n".join(lines)


def _runs_to_dataset(
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert run history to opik dataset format."""
    dataset: list[dict[str, Any]] = []
    for r in runs:
        dataset.append({
            "input": r.get("task", ""),
            "expected_output": "success" if r.get("success") else "failure",
            "metadata": {
                "failure_type": r.get("failure_type", ""),
                "url": r.get("url", ""),
            },
        })
    return dataset


def _opik_available() -> bool:
    """Check if opik-optimizer package is importable."""
    try:
        import opik_optimizer  # noqa: F401
        return True
    except ImportError:
        return False


def _parse_json_safe(raw: str) -> dict[str, Any]:
    """Extract JSON from LLM response, tolerating markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM JSON: %s", text[:200])
        return {}
