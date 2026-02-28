#!/usr/bin/env python3
"""Proof-of-Concept runner for the adaptive web automation engine.

Wires all modules together and runs the Naver Shopping workflow
(or any custom YAML workflow) through the full orchestration pipeline.

Usage:
    python scripts/run_poc.py [--headless] [--workflow PATH] [--iterations N]
    python scripts/run_poc.py --headless --iterations 5
    python scripts/run_poc.py --workflow config/workflows/naver_shopping.yaml

Environment variables:
    GEMINI_API_KEY  — Google Gemini API key (optional, enables LLM planner)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Ensure project root is on sys.path.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from src.core.executor import Executor, create_executor  # noqa: E402
from src.core.executor_pool import ExecutorPool  # noqa: E402
from src.core.extractor import DOMExtractor  # noqa: E402
from src.core.fallback_router import create_fallback_router  # noqa: E402
from src.core.orchestrator import Orchestrator  # noqa: E402
from src.core.rule_engine import RuleEngine  # noqa: E402
from src.core.types import StepResult  # noqa: E402
from src.core.verifier import Verifier  # noqa: E402
from src.learning.memory_manager import MemoryManager, create_memory_manager  # noqa: E402
from src.learning.pattern_db import PatternDB  # noqa: E402
from src.learning.rule_promoter import RulePromoter  # noqa: E402
from src.workflow.dsl_parser import parse_workflow  # noqa: E402

logger = logging.getLogger(__name__)

# Default workflow path.
_DEFAULT_WORKFLOW = _PROJECT_ROOT / "config" / "workflows" / "naver_shopping.yaml"


async def create_engine(
    headless: bool = True,
    executor: Executor | None = None,
) -> tuple[Orchestrator, Executor, MemoryManager]:
    """Create and wire all engine modules.

    Args:
        headless: Whether to run the browser in headless mode.
        executor: Optional pre-created Executor (e.g. from an ExecutorPool).
            If None, a new browser+executor is created.

    Returns:
        Tuple of (orchestrator, executor, memory_manager).
        Caller is responsible for calling ``executor.close()`` when done.
    """
    # Core modules (token cost = 0).
    if executor is None:
        executor = await create_executor(headless=headless)
    extractor = DOMExtractor()
    rule_engine = RuleEngine()
    verifier = Verifier()
    fallback_router = create_fallback_router()

    # Optional LLM planner (only if API key is available).
    planner = None
    if os.environ.get("GEMINI_API_KEY"):
        try:
            from src.ai.llm_planner import create_llm_planner
            planner = create_llm_planner()
            logger.info("LLM Planner enabled (GEMINI_API_KEY found)")
        except Exception as exc:
            logger.warning("Failed to create LLM planner: %s", exc)
    else:
        logger.info("LLM Planner disabled (no GEMINI_API_KEY)")

    # Memory manager.
    data_dir = _PROJECT_ROOT / "data"
    memory = await create_memory_manager(str(data_dir))

    # Learning modules (G2).
    pattern_db = PatternDB(data_dir / "patterns.db")
    await pattern_db.init_db()
    rule_promoter = RulePromoter(pattern_db, rule_engine)

    # Optional vision modules (G1).
    yolo_detector = None
    vlm_client = None
    coord_mapper = None
    if os.environ.get("ENABLE_VISION"):
        try:
            from src.vision.coord_mapper import CoordMapper
            from src.vision.vlm_client import create_vlm_client
            from src.vision.yolo_detector import create_yolo_detector

            yolo_detector = create_yolo_detector()
            vlm_client = create_vlm_client()
            coord_mapper = CoordMapper()
            logger.info("Vision modules enabled")
        except Exception as exc:
            logger.warning("Failed to create vision modules: %s", exc)

    # Wire into orchestrator.
    orchestrator = Orchestrator(
        executor=executor,
        extractor=extractor,
        rule_engine=rule_engine,
        verifier=verifier,
        fallback_router=fallback_router,
        planner=planner,
        memory=memory,
        pattern_db=pattern_db,
        rule_promoter=rule_promoter,
        yolo_detector=yolo_detector,
        vlm_client=vlm_client,
        coord_mapper=coord_mapper,
    )

    return orchestrator, executor, memory


def _step_result_to_dict(result: StepResult) -> dict:
    """Serialize a StepResult to a JSON-safe dict.

    Args:
        result: The step result to serialize.

    Returns:
        Dictionary with all fields serialized.
    """
    d = asdict(result)
    # Convert FailureCode enum to string.
    if d.get("failure_code") is not None:
        d["failure_code"] = str(d["failure_code"])
    return d


async def run_poc(
    workflow_path: Path,
    headless: bool,
    iterations: int,
) -> list[dict]:
    """Run the PoC workflow for the specified number of iterations.

    Args:
        workflow_path: Path to the YAML workflow file.
        headless: Whether to run the browser in headless mode.
        iterations: Number of iterations to run.

    Returns:
        List of iteration result dicts.
    """
    logger.info("Loading workflow from %s", workflow_path)
    steps = parse_workflow(workflow_path)
    logger.info("Parsed %d steps from workflow", len(steps))

    all_results: list[dict] = []

    # Use ExecutorPool for multi-iteration runs (reuse browser, new context per iter).
    pool: ExecutorPool | None = None
    if iterations > 1:
        pool = await ExecutorPool.create(headless=headless)
        logger.info("ExecutorPool created for %d iterations", iterations)

    try:
        for i in range(iterations):
            logger.info("=== Iteration %d/%d ===", i + 1, iterations)
            start_time = time.time()

            # Acquire executor from pool or create standalone.
            if pool is not None:
                executor = await pool.acquire()
                orchestrator, executor, memory = await create_engine(headless, executor=executor)
            else:
                orchestrator, executor, memory = await create_engine(headless)

            try:
                results = await orchestrator.run(steps)

                total_tokens = sum(r.tokens_used for r in results)
                total_cost = sum(r.cost_usd for r in results)
                total_latency = sum(r.latency_ms for r in results)
                success_count = sum(1 for r in results if r.success)
                success_rate = success_count / len(results) if results else 0.0

                iteration_result = {
                    "iteration": i + 1,
                    "results": [_step_result_to_dict(r) for r in results],
                    "total_steps": len(results),
                    "successful_steps": success_count,
                    "failed_steps": len(results) - success_count,
                    "total_tokens": total_tokens,
                    "total_cost_usd": total_cost,
                    "total_latency_ms": total_latency,
                    "wall_time_s": time.time() - start_time,
                    "success_rate": success_rate,
                    "methods_used": _count_methods(results),
                }

                all_results.append(iteration_result)
                logger.info(
                    "Iteration %d: success_rate=%.1f%% tokens=%d cost=$%.4f latency=%.0fms",
                    i + 1,
                    success_rate * 100,
                    total_tokens,
                    total_cost,
                    total_latency,
                )

            except Exception as exc:
                logger.error("Iteration %d failed: %s", i + 1, exc, exc_info=True)
                all_results.append({
                    "iteration": i + 1,
                    "error": str(exc),
                    "wall_time_s": time.time() - start_time,
                })
            finally:
                if pool is not None:
                    await pool.release(executor)
                else:
                    await executor.close()
    finally:
        if pool is not None:
            await pool.close()
            logger.info("ExecutorPool closed")

    return all_results


def _count_methods(results: list[StepResult]) -> dict[str, int]:
    """Count how many times each method was used.

    Args:
        results: List of step results.

    Returns:
        Dict mapping method name to count.
    """
    counts: dict[str, int] = {}
    for r in results:
        counts[r.method] = counts.get(r.method, 0) + 1
    return counts


def print_summary(all_results: list[dict]) -> None:
    """Print a formatted summary of all iteration results.

    Args:
        all_results: List of iteration result dicts.
    """
    print("\n" + "=" * 70)
    print("  PoC Results Summary")
    print("=" * 70)

    total_iterations = len(all_results)
    successful_iterations = sum(
        1 for r in all_results if "error" not in r and r.get("success_rate", 0) > 0
    )

    print(f"\n  Iterations: {total_iterations}")
    print(f"  Successful: {successful_iterations}")

    if not all_results:
        print("  No results to display.\n")
        return

    # Aggregate metrics.
    success_rates: list[float] = []
    total_tokens_all: list[int] = []
    total_costs: list[float] = []
    wall_times: list[float] = []

    for r in all_results:
        if "error" in r:
            continue
        success_rates.append(r.get("success_rate", 0.0))
        total_tokens_all.append(r.get("total_tokens", 0))
        total_costs.append(r.get("total_cost_usd", 0.0))
        wall_times.append(r.get("wall_time_s", 0.0))

    if success_rates:
        avg_success = sum(success_rates) / len(success_rates)
        avg_tokens = sum(total_tokens_all) / len(total_tokens_all)
        avg_cost = sum(total_costs) / len(total_costs)
        avg_wall_time = sum(wall_times) / len(wall_times)

        print(f"\n  Avg success rate:  {avg_success:.1%}")
        print(f"  Avg tokens/iter:   {avg_tokens:.0f}")
        print(f"  Avg cost/iter:     ${avg_cost:.4f}")
        print(f"  Avg wall time:     {avg_wall_time:.1f}s")

    # Per-iteration table.
    print(f"\n  {'Iter':>4}  {'Success':>8}  {'Tokens':>8}  {'Cost':>8}  {'Time':>8}")
    print(f"  {'----':>4}  {'-------':>8}  {'------':>8}  {'----':>8}  {'----':>8}")

    for r in all_results:
        if "error" in r:
            print(
                f"  {r['iteration']:>4}  {'ERROR':>8}"
                f"  {'--':>8}  {'--':>8}  {r['wall_time_s']:>7.1f}s"
            )
        else:
            sr = r.get("success_rate", 0.0)
            print(
                f"  {r['iteration']:>4}  {sr:>7.1%}  {r.get('total_tokens', 0):>8d}  "
                f"${r.get('total_cost_usd', 0.0):>6.4f}  {r.get('wall_time_s', 0.0):>7.1f}s"
            )

    # PoC criteria check.
    print("\n  --- PoC Success Criteria ---")
    if success_rates:
        avg_sr = sum(success_rates) / len(success_rates)
        meets_sr = avg_sr >= 0.80
        print(f"  E2E success rate >= 80%:  {'PASS' if meets_sr else 'FAIL'} ({avg_sr:.1%})")
    if total_costs:
        avg_c = sum(total_costs) / len(total_costs)
        meets_cost = avg_c <= 0.01
        print(f"  Per-task cost <= $0.01:   {'PASS' if meets_cost else 'FAIL'} (${avg_c:.4f})")
    if wall_times:
        avg_wt = sum(wall_times) / len(wall_times)
        meets_time = avg_wt <= 90
        print(f"  Execution time <= 90s:    {'PASS' if meets_time else 'FAIL'} ({avg_wt:.1f}s)")
    if len(total_tokens_all) >= 2:
        first_half = total_tokens_all[: len(total_tokens_all) // 2]
        second_half = total_tokens_all[len(total_tokens_all) // 2 :]
        avg_first = sum(first_half) / len(first_half) if first_half else 0
        avg_second = sum(second_half) / len(second_half) if second_half else 0
        decreasing = avg_second <= avg_first
        print(
            f"  LLM calls decreasing:    {'PASS' if decreasing else 'FAIL'} "
            f"(first_half_avg={avg_first:.0f}, second_half_avg={avg_second:.0f})"
        )

    print("\n" + "=" * 70)


def main() -> None:
    """Entry point for the PoC runner."""
    parser = argparse.ArgumentParser(
        description="Run the adaptive web automation engine PoC.",
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
        help="Run browser in headed mode (visible)",
    )
    parser.add_argument(
        "--workflow",
        type=Path,
        default=_DEFAULT_WORKFLOW,
        help=f"Path to workflow YAML file (default: {_DEFAULT_WORKFLOW})",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of iterations to run (default: 1)",
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

    # Run the PoC.
    all_results = asyncio.run(
        run_poc(
            workflow_path=args.workflow,
            headless=headless,
            iterations=args.iterations,
        )
    )

    # Print summary.
    print_summary(all_results)

    # Save results to file.
    output_path = _PROJECT_ROOT / "data" / "poc_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
