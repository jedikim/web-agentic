#!/usr/bin/env python3
"""Performance benchmark for the adaptive web automation engine.

Runs the Naver Shopping workflow multiple times and collects metrics
matching the PRD success criteria:

  - E2E success rate (target: >= 80%)
  - LLM call reduction trend (target: decreasing over iterations)
  - Per-task cost (target: <= $0.01)
  - Execution time (target: <= 90s)

Usage:
    python scripts/benchmark.py [--iterations N] [--headless] [--workflow PATH]
    python scripts/benchmark.py --iterations 20 --headless

Output:
    data/benchmark_results.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from src.core.types import StepResult  # noqa: E402
from src.workflow.dsl_parser import parse_workflow  # noqa: E402

logger = logging.getLogger(__name__)

# Default workflow path.
_DEFAULT_WORKFLOW = _PROJECT_ROOT / "config" / "workflows" / "naver_shopping.yaml"


async def _run_single_iteration(
    iteration: int,
    steps: list,
    headless: bool,
) -> dict[str, Any]:
    """Run a single benchmark iteration.

    Args:
        iteration: 1-based iteration number.
        steps: Parsed step definitions.
        headless: Whether to run headless.

    Returns:
        Metrics dict for this iteration.
    """
    # Import here to avoid circular issues and ensure fresh engine each time.
    from scripts.run_poc import create_engine

    start_time = time.time()
    metrics: dict[str, Any] = {"iteration": iteration}

    orchestrator, executor, memory = await create_engine(headless)
    try:
        results = await orchestrator.run(steps)
        wall_time = time.time() - start_time

        # Compute metrics.
        total_steps = len(results)
        success_count = sum(1 for r in results if r.success)
        failure_count = total_steps - success_count
        success_rate = success_count / total_steps if total_steps > 0 else 0.0

        total_tokens = sum(r.tokens_used for r in results)
        total_cost = sum(r.cost_usd for r in results)
        total_latency_ms = sum(r.latency_ms for r in results)

        # Count methods used.
        method_counts: dict[str, int] = {}
        for r in results:
            method_counts[r.method] = method_counts.get(r.method, 0) + 1

        # LLM call count (L1 = heuristic, L2 = LLM, R = rule).
        llm_calls = method_counts.get("L2", 0)
        rule_matches = method_counts.get("R", 0)
        rule_match_rate = rule_matches / total_steps if total_steps > 0 else 0.0

        metrics.update({
            "total_steps": total_steps,
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": success_rate,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "total_latency_ms": total_latency_ms,
            "wall_time_s": wall_time,
            "llm_calls": llm_calls,
            "rule_matches": rule_matches,
            "rule_match_rate": rule_match_rate,
            "method_counts": method_counts,
            "step_results": [_result_to_dict(r) for r in results],
        })

    except Exception as exc:
        wall_time = time.time() - start_time
        logger.error("Iteration %d failed: %s", iteration, exc, exc_info=True)
        metrics.update({
            "error": str(exc),
            "wall_time_s": wall_time,
            "success_rate": 0.0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "llm_calls": 0,
            "rule_matches": 0,
            "rule_match_rate": 0.0,
        })
    finally:
        await executor.close()

    return metrics


def _result_to_dict(result: StepResult) -> dict[str, Any]:
    """Convert StepResult to a JSON-serializable dict."""
    d = asdict(result)
    if d.get("failure_code") is not None:
        d["failure_code"] = str(d["failure_code"])
    return d


async def run_benchmark(
    workflow_path: Path,
    headless: bool,
    iterations: int,
) -> dict[str, Any]:
    """Run the full benchmark.

    Args:
        workflow_path: Path to workflow YAML.
        headless: Whether to run headless.
        iterations: Total iterations to run.

    Returns:
        Full benchmark results dict.
    """
    logger.info("Loading workflow from %s", workflow_path)
    steps = parse_workflow(workflow_path)
    logger.info("Parsed %d steps, running %d iterations", len(steps), iterations)

    iteration_results: list[dict[str, Any]] = []
    overall_start = time.time()

    for i in range(1, iterations + 1):
        logger.info("--- Benchmark iteration %d/%d ---", i, iterations)
        result = await _run_single_iteration(i, steps, headless)
        iteration_results.append(result)

        # Log progress.
        sr = result.get("success_rate", 0.0)
        tokens = result.get("total_tokens", 0)
        cost = result.get("total_cost_usd", 0.0)
        wt = result.get("wall_time_s", 0.0)
        logger.info(
            "Iter %d: success=%.1f%% tokens=%d cost=$%.4f wall_time=%.1fs",
            i, sr * 100, tokens, cost, wt,
        )

    overall_wall_time = time.time() - overall_start

    # Aggregate statistics.
    summary = _compute_summary(iteration_results, iterations)
    summary["overall_wall_time_s"] = overall_wall_time
    summary["workflow"] = str(workflow_path)
    summary["iterations_requested"] = iterations
    summary["poc_criteria"] = _check_poc_criteria(iteration_results)

    return {
        "summary": summary,
        "iterations": iteration_results,
    }


def _compute_summary(
    iteration_results: list[dict[str, Any]],
    iterations: int,
) -> dict[str, Any]:
    """Compute aggregate statistics from iteration results.

    Args:
        iteration_results: Per-iteration metrics.
        iterations: Total iterations requested.

    Returns:
        Summary statistics dict.
    """
    valid_results = [r for r in iteration_results if "error" not in r]

    if not valid_results:
        return {
            "total_iterations": iterations,
            "successful_iterations": 0,
            "avg_success_rate": 0.0,
        }

    success_rates = [r["success_rate"] for r in valid_results]
    token_counts = [r["total_tokens"] for r in valid_results]
    costs = [r["total_cost_usd"] for r in valid_results]
    wall_times = [r["wall_time_s"] for r in valid_results]
    llm_calls = [r.get("llm_calls", 0) for r in valid_results]
    rule_match_rates = [r.get("rule_match_rate", 0.0) for r in valid_results]

    summary: dict[str, Any] = {
        "total_iterations": iterations,
        "successful_iterations": len(valid_results),
        "failed_iterations": iterations - len(valid_results),
    }

    # Success rate stats.
    summary["avg_success_rate"] = statistics.mean(success_rates)
    summary["min_success_rate"] = min(success_rates)
    summary["max_success_rate"] = max(success_rates)
    if len(success_rates) >= 2:
        summary["stdev_success_rate"] = statistics.stdev(success_rates)

    # Token stats.
    summary["avg_tokens"] = statistics.mean(token_counts)
    summary["total_tokens"] = sum(token_counts)

    # Cost stats.
    summary["avg_cost_usd"] = statistics.mean(costs)
    summary["total_cost_usd"] = sum(costs)
    summary["max_cost_usd"] = max(costs)

    # Timing stats.
    summary["avg_wall_time_s"] = statistics.mean(wall_times)
    summary["max_wall_time_s"] = max(wall_times)

    # LLM call trend.
    summary["avg_llm_calls"] = statistics.mean(llm_calls)
    summary["llm_calls_per_iteration"] = llm_calls

    # Rule match rate trend (should increase).
    summary["avg_rule_match_rate"] = statistics.mean(rule_match_rates)
    summary["rule_match_rates"] = rule_match_rates

    # Trend analysis.
    if len(llm_calls) >= 4:
        mid = len(llm_calls) // 2
        first_half_avg = statistics.mean(llm_calls[:mid])
        second_half_avg = statistics.mean(llm_calls[mid:])
        summary["llm_trend_first_half_avg"] = first_half_avg
        summary["llm_trend_second_half_avg"] = second_half_avg
        summary["llm_calls_decreasing"] = second_half_avg <= first_half_avg

    if len(rule_match_rates) >= 4:
        mid = len(rule_match_rates) // 2
        first_half_avg = statistics.mean(rule_match_rates[:mid])
        second_half_avg = statistics.mean(rule_match_rates[mid:])
        summary["rule_match_trend_first_half_avg"] = first_half_avg
        summary["rule_match_trend_second_half_avg"] = second_half_avg
        summary["rule_match_increasing"] = second_half_avg >= first_half_avg

    return summary


def _check_poc_criteria(iteration_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Check results against PRD PoC success criteria.

    PRD criteria:
    - E2E success rate >= 80% (20 runs, 16+ pass)
    - LLM call decrease trend after 10 iterations
    - Per-task cost <= $0.01
    - Execution time <= 90s

    Args:
        iteration_results: Per-iteration metrics.

    Returns:
        Dict with pass/fail for each criterion.
    """
    valid = [r for r in iteration_results if "error" not in r]

    criteria: dict[str, Any] = {}

    # 1. Success rate.
    if valid:
        avg_sr = statistics.mean([r["success_rate"] for r in valid])
        criteria["success_rate_target"] = 0.80
        criteria["success_rate_actual"] = avg_sr
        criteria["success_rate_pass"] = avg_sr >= 0.80

    # 2. Per-task cost.
    if valid:
        avg_cost = statistics.mean([r["total_cost_usd"] for r in valid])
        criteria["cost_target_usd"] = 0.01
        criteria["cost_actual_usd"] = avg_cost
        criteria["cost_pass"] = avg_cost <= 0.01

    # 3. Execution time.
    if valid:
        avg_time = statistics.mean([r["wall_time_s"] for r in valid])
        criteria["time_target_s"] = 90.0
        criteria["time_actual_s"] = avg_time
        criteria["time_pass"] = avg_time <= 90.0

    # 4. LLM call trend.
    llm_calls = [r.get("llm_calls", 0) for r in valid]
    if len(llm_calls) >= 4:
        mid = len(llm_calls) // 2
        first_avg = statistics.mean(llm_calls[:mid])
        second_avg = statistics.mean(llm_calls[mid:])
        criteria["llm_trend_first_avg"] = first_avg
        criteria["llm_trend_second_avg"] = second_avg
        criteria["llm_trend_pass"] = second_avg <= first_avg

    # Overall.
    criteria["all_pass"] = all(
        criteria.get(k, False) for k in [
            "success_rate_pass", "cost_pass", "time_pass",
        ] if k in criteria
    )

    return criteria


def print_benchmark_report(results: dict[str, Any]) -> None:
    """Print a formatted benchmark report.

    Args:
        results: Full benchmark results dict.
    """
    summary = results["summary"]
    criteria = summary.get("poc_criteria", {})

    print("\n" + "=" * 70)
    print("  Performance Benchmark Report")
    print("=" * 70)

    print(f"\n  Workflow: {summary.get('workflow', 'N/A')}")
    print(f"  Iterations: {summary['total_iterations']}")
    print(f"  Successful: {summary['successful_iterations']}")
    print(f"  Total time: {summary.get('overall_wall_time_s', 0):.1f}s")

    print("\n  --- Aggregate Metrics ---")
    print(f"  Avg success rate:    {summary.get('avg_success_rate', 0):.1%}")
    print(f"  Avg tokens/iter:     {summary.get('avg_tokens', 0):.0f}")
    print(f"  Avg cost/iter:       ${summary.get('avg_cost_usd', 0):.4f}")
    print(f"  Total cost:          ${summary.get('total_cost_usd', 0):.4f}")
    print(f"  Avg wall time:       {summary.get('avg_wall_time_s', 0):.1f}s")
    print(f"  Avg LLM calls:       {summary.get('avg_llm_calls', 0):.1f}")
    print(f"  Avg rule match rate: {summary.get('avg_rule_match_rate', 0):.1%}")

    # Trend analysis.
    if "llm_calls_decreasing" in summary:
        trend = "DECREASING" if summary["llm_calls_decreasing"] else "INCREASING"
        print(f"\n  LLM call trend: {trend}")
        print(f"    First half avg:  {summary['llm_trend_first_half_avg']:.1f}")
        print(f"    Second half avg: {summary['llm_trend_second_half_avg']:.1f}")

    if "rule_match_increasing" in summary:
        trend = "INCREASING" if summary["rule_match_increasing"] else "FLAT/DECREASING"
        print(f"\n  Rule match trend: {trend}")
        print(f"    First half avg:  {summary['rule_match_trend_first_half_avg']:.1%}")
        print(f"    Second half avg: {summary['rule_match_trend_second_half_avg']:.1%}")

    # PoC criteria.
    print("\n  --- PoC Success Criteria ---")
    for key in ["success_rate", "cost", "time", "llm_trend"]:
        pass_key = f"{key}_pass"
        if pass_key in criteria:
            status = "PASS" if criteria[pass_key] else "FAIL"
            if key == "success_rate":
                print(f"  Success rate >= 80%:  {status} ({criteria['success_rate_actual']:.1%})")
            elif key == "cost":
                print(f"  Cost <= $0.01:        {status} (${criteria['cost_actual_usd']:.4f})")
            elif key == "time":
                print(f"  Time <= 90s:          {status} ({criteria['time_actual_s']:.1f}s)")
            elif key == "llm_trend":
                print(f"  LLM calls decreasing: {status}")

    overall = criteria.get("all_pass", False)
    print(f"\n  Overall: {'ALL CRITERIA MET' if overall else 'SOME CRITERIA NOT MET'}")

    # Per-iteration table.
    iterations = results.get("iterations", [])
    if iterations:
        print(f"\n  {'Iter':>4}  {'Success':>8}  {'Tokens':>8}  {'Cost':>8}  "
              f"{'LLM':>5}  {'Rule%':>6}  {'Time':>8}")
        print(f"  {'----':>4}  {'-------':>8}  {'------':>8}  {'----':>8}  "
              f"{'---':>5}  {'-----':>6}  {'----':>8}")

        for r in iterations:
            if "error" in r:
                print(f"  {r['iteration']:>4}  {'ERROR':>8}")
                continue
            print(
                f"  {r['iteration']:>4}  {r['success_rate']:>7.1%}  {r['total_tokens']:>8d}  "
                f"${r['total_cost_usd']:>6.4f}  {r.get('llm_calls', 0):>5d}  "
                f"{r.get('rule_match_rate', 0):>5.1%}  {r['wall_time_s']:>7.1f}s"
            )

    print("\n" + "=" * 70)


def main() -> None:
    """Entry point for the benchmark script."""
    parser = argparse.ArgumentParser(
        description="Run performance benchmark for the adaptive web automation engine.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Number of benchmark iterations (default: 5)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default: True)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser in headed mode",
    )
    parser.add_argument(
        "--workflow",
        type=Path,
        default=_DEFAULT_WORKFLOW,
        help=f"Path to workflow YAML file (default: {_DEFAULT_WORKFLOW})",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )
    args = parser.parse_args()

    # Configure logging.
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    headless = not args.no_headless if args.no_headless else args.headless

    # Run benchmark.
    results = asyncio.run(
        run_benchmark(
            workflow_path=args.workflow,
            headless=headless,
            iterations=args.iterations,
        )
    )

    # Print report.
    print_benchmark_report(results)

    # Save results.
    output_path = _PROJECT_ROOT / "data" / "benchmark_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
