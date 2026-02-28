#!/usr/bin/env python3
"""Multi-phase scenario runner — autonomous execution of complex scenarios.

Runs multi-phase scenarios where each phase is a single ``orch.run()`` call.
The browser session is maintained across phases so that Phase N+1 can
continue from the page state left by Phase N.

For parallel scenario execution with recovery and rollback logging, see
``src.core.resilience.ResilienceOrchestrator``.

Usage:
    # Run all scenarios (headful)
    python scripts/run_scenarios.py

    # Run specific scenario
    python scripts/run_scenarios.py --filter family_outing

    # Headless with cost limit
    python scripts/run_scenarios.py --headless --max-cost 0.30
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.scenario_reporter import (  # noqa: E402
    write_run_log,
    write_scenario_report,
    write_summary,
)
from scripts.scenario_types import (  # noqa: E402
    PhaseResult,
    ScenarioDefinition,
    ScenarioResult,
    load_scenarios,
)
from src.ai.llm_planner import create_llm_planner  # noqa: E402
from src.core.executor import create_executor  # noqa: E402
from src.core.extractor import DOMExtractor  # noqa: E402
from src.core.llm_orchestrator import LLMFirstOrchestrator  # noqa: E402
from src.core.selector_cache import SelectorCache  # noqa: E402
from src.core.verifier import Verifier  # noqa: E402

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────

DEFAULT_DEFINITIONS = "testing/scenarios/definitions.yaml"
DEFAULT_OUTPUT_DIR = "testing"
DEFAULT_MAX_COST = 0.50  # USD total across all scenarios


# ── Vision Module Helpers ────────────────────────────


def _create_vlm_client():
    """Create VLM client if dependencies available."""
    try:
        from src.vision.vlm_client import create_vlm_client
        return create_vlm_client()
    except ImportError:
        return None


def _create_yolo_detector():
    """Create YOLO detector if dependencies available."""
    try:
        from src.vision.yolo_detector import create_yolo_detector
        return create_yolo_detector()
    except (ImportError, Exception):
        return None


# ── Single Scenario Runner ───────────────────────────


async def run_single_scenario(
    scenario: ScenarioDefinition,
    *,
    headless: bool = False,
    output_dir: Path = Path(DEFAULT_OUTPUT_DIR),
    cost_so_far: float = 0.0,
    max_cost: float = DEFAULT_MAX_COST,
) -> ScenarioResult:
    """Execute a single multi-phase scenario autonomously.

    Creates a fresh browser session per scenario.  All phases share the
    same executor, orchestrator, and planner so that browser state and
    LLM usage stats carry across phases.

    Args:
        scenario: Scenario definition to execute.
        headless: Run browser headless.
        output_dir: Root testing directory.
        cost_so_far: Accumulated cost from previous scenarios (for budget guard).
        max_cost: Global cost cap.

    Returns:
        A ``ScenarioResult`` with per-phase details.
    """
    scenario_dir = output_dir / "scenarios" / scenario.name
    ss_dir = scenario_dir / "screenshots"
    ss_dir.mkdir(parents=True, exist_ok=True)
    cache_path = scenario_dir / "cache.db"

    started_at = datetime.now().isoformat(timespec="seconds")
    scenario_start = time.time()
    phase_results: list[PhaseResult] = []

    # Create modules — fresh per scenario
    executor = await create_executor(headless=headless)
    extractor = DOMExtractor()
    planner = create_llm_planner()
    verifier = Verifier()
    cache = SelectorCache(str(cache_path))
    await cache.init()

    vlm = _create_vlm_client()
    yolo = _create_yolo_detector()

    orch = LLMFirstOrchestrator(
        executor=executor,
        extractor=extractor,
        planner=planner,
        verifier=verifier,
        cache=cache,
        screenshot_dir=ss_dir,
        yolo_detector=yolo,
        vlm_client=vlm,
        max_cost_per_run=scenario.max_cost_usd / max(len(scenario.phases), 1),
    )

    try:
        for pi, phase in enumerate(scenario.phases):
            phase_num = pi + 1
            logger.info(
                "=== [%s] Phase %d/%d: %s ===",
                scenario.name, phase_num, len(scenario.phases), phase.name,
            )

            # Budget guard
            current_cost = cost_so_far + sum(_phase_cost(pr) for pr in phase_results)
            if current_cost >= max_cost:
                logger.warning(
                    "Cost limit reached ($%.4f >= $%.2f), stopping scenario",
                    current_cost, max_cost,
                )
                phase_results.append(PhaseResult(
                    phase=phase, run_result=None, wall_time_s=0.0,
                    error=f"Budget exceeded: ${current_cost:.4f}",
                ))
                break

            # Navigate to URL if specified
            if phase.url:
                logger.info("Navigating to: %s", phase.url)
                await executor.goto(phase.url)
                page = await executor.get_page()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)

            # Inject scenario context into intent
            full_intent = phase.intent
            if scenario.context:
                full_intent = f"[맥락: {scenario.context}] {phase.intent}"

            # The orchestrator names screenshots as step_{N}_{step_id}_{ts}.png
            # We'll rename/move them after the phase to add phase prefix

            phase_start = time.time()
            try:
                run_result = await asyncio.wait_for(
                    orch.run(full_intent),
                    timeout=phase.timeout_s,
                )
                # Rename screenshots to include phase prefix
                _rename_phase_screenshots(ss_dir, phase_num, run_result.screenshots)

                phase_results.append(PhaseResult(
                    phase=phase,
                    run_result=run_result,
                    wall_time_s=time.time() - phase_start,
                ))
                logger.info(
                    "Phase %s: %s (%d/%d steps)",
                    phase.name,
                    "OK" if run_result.success else "FAIL",
                    sum(1 for sr in run_result.step_results if sr.success),
                    len(run_result.step_results),
                )
            except TimeoutError:
                _rescue_orphaned_screenshots(ss_dir, phase_num)
                phase_results.append(PhaseResult(
                    phase=phase,
                    run_result=None,
                    wall_time_s=time.time() - phase_start,
                    timed_out=True,
                ))
                logger.warning("Phase %s timed out after %ds", phase.name, phase.timeout_s)
            except Exception as exc:
                _rescue_orphaned_screenshots(ss_dir, phase_num)
                phase_results.append(PhaseResult(
                    phase=phase,
                    run_result=None,
                    wall_time_s=time.time() - phase_start,
                    error=str(exc),
                ))
                logger.error("Phase %s failed: %s", phase.name, exc)

            # Inter-phase pause
            await asyncio.sleep(1)

    finally:
        await executor.close()

    finished_at = datetime.now().isoformat(timespec="seconds")
    total_wall = time.time() - scenario_start

    # Aggregate stats
    total_tokens = 0
    total_cost = 0.0
    total_steps_ok = 0
    total_steps_all = 0
    for pr in phase_results:
        total_tokens += _phase_tokens(pr)
        total_cost += _phase_cost(pr)
        total_steps_ok += _phase_steps_ok(pr)
        total_steps_all += _phase_steps_all(pr)

    result = ScenarioResult(
        scenario=scenario,
        phase_results=phase_results,
        total_wall_time_s=total_wall,
        started_at=started_at,
        finished_at=finished_at,
        overall_success=all(
            pr.run_result is not None and pr.run_result.success
            for pr in phase_results
        ),
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        total_steps_ok=total_steps_ok,
        total_steps_all=total_steps_all,
    )

    # Write per-scenario report
    write_scenario_report(result, scenario_dir)

    logger.info(
        "Scenario %s: %s | %d/%d steps | $%.4f | %.1fs",
        scenario.name,
        "PASS" if result.overall_success else "FAIL",
        total_steps_ok, total_steps_all,
        total_cost, total_wall,
    )

    return result


# ── Helpers ──────────────────────────────────────────


def _phase_cost(pr: PhaseResult) -> float:
    return pr.run_result.total_cost_usd if pr.run_result else 0.0


def _phase_tokens(pr: PhaseResult) -> int:
    return pr.run_result.total_tokens if pr.run_result else 0


def _phase_steps_ok(pr: PhaseResult) -> int:
    return sum(1 for sr in pr.run_result.step_results if sr.success) if pr.run_result else 0


def _phase_steps_all(pr: PhaseResult) -> int:
    return len(pr.run_result.step_results) if pr.run_result else 0


def _rename_phase_screenshots(
    ss_dir: Path, phase_num: int, screenshot_paths: list[str],
) -> None:
    """Rename screenshots to include phase prefix for organization."""
    for ss_path_str in screenshot_paths:
        ss_path = Path(ss_path_str)
        if ss_path.exists() and ss_path.parent == ss_dir:
            new_name = f"phase{phase_num}_{ss_path.name}"
            new_path = ss_dir / new_name
            ss_path.rename(new_path)


def _rescue_orphaned_screenshots(ss_dir: Path, phase_num: int) -> list[str]:
    """Find screenshots without phase prefix and rename them.

    Called on timeout/error when screenshots were saved by the orchestrator
    but never got phase-prefixed because run() didn't complete.

    Args:
        ss_dir: Screenshot directory.
        phase_num: Phase number to prefix.

    Returns:
        List of rescued screenshot paths (as strings).
    """
    rescued: list[str] = []
    for f in sorted(ss_dir.glob("step_*.png")):
        new_name = f"phase{phase_num}_{f.name}"
        new_path = ss_dir / new_name
        f.rename(new_path)
        rescued.append(str(new_path))
    # Also rescue captcha screenshots
    for f in sorted(ss_dir.glob("captcha_*.png")):
        new_name = f"phase{phase_num}_{f.name}"
        new_path = ss_dir / new_name
        f.rename(new_path)
        rescued.append(str(new_path))
    if rescued:
        logger.info("Rescued %d orphaned screenshots for phase %d", len(rescued), phase_num)
    return rescued


# ── Main ─────────────────────────────────────────────


async def main(
    definitions_path: str,
    output_dir: str,
    filter_name: str | None,
    headless: bool,
    max_cost: float,
) -> None:
    """Run all (or filtered) multi-phase scenarios."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    scenarios = load_scenarios(definitions_path)
    if filter_name:
        scenarios = [s for s in scenarios if filter_name in s.name]
        if not scenarios:
            logger.error("No scenarios matching filter: %s", filter_name)
            return

    logger.info("Loaded %d scenario(s)", len(scenarios))
    out = Path(output_dir)

    results: list[ScenarioResult] = []
    cost_so_far = 0.0

    for i, scenario in enumerate(scenarios):
        logger.info(
            "===== Scenario %d/%d: %s =====",
            i + 1, len(scenarios), scenario.name,
        )

        if cost_so_far >= max_cost:
            logger.warning(
                "Global cost limit reached ($%.4f >= $%.2f), stopping",
                cost_so_far, max_cost,
            )
            break

        result = await run_single_scenario(
            scenario,
            headless=headless,
            output_dir=out,
            cost_so_far=cost_so_far,
            max_cost=max_cost,
        )
        results.append(result)
        cost_so_far += result.total_cost_usd

    # Write global reports
    write_summary(results, out)
    write_run_log(results, out)

    # Final summary
    passed = sum(1 for r in results if r.overall_success)
    logger.info("=" * 60)
    logger.info(
        "ALL DONE: %d/%d scenarios passed | $%.4f total | %.1fs",
        passed, len(results), cost_so_far,
        sum(r.total_wall_time_s for r in results),
    )
    logger.info("Reports: %s/summary.md", out)
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Multi-phase scenario runner for autonomous web automation testing"
    )
    parser.add_argument(
        "--definitions", default=DEFAULT_DEFINITIONS,
        help="Path to scenarios YAML (default: %(default)s)",
    )
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT_DIR,
        help="Output directory (default: %(default)s)",
    )
    parser.add_argument(
        "--filter", default=None, dest="filter_name",
        help="Run only scenarios whose name contains this string",
    )
    parser.add_argument(
        "--headless", action="store_true", default=False,
        help="Run browser in headless mode",
    )
    parser.add_argument(
        "--max-cost", type=float, default=DEFAULT_MAX_COST,
        help="Maximum total cost in USD (default: %(default)s)",
    )
    args = parser.parse_args()

    asyncio.run(main(
        definitions_path=args.definitions,
        output_dir=args.output,
        filter_name=args.filter_name,
        headless=args.headless,
        max_cost=args.max_cost,
    ))
