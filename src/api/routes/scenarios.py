"""Scenario API routes — run scenarios, view results, trends."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter

from src.api.dependencies import get_db, get_notifier
from src.api.models import (
    ScenarioResultItem,
    ScenarioRunRequest,
    ScenarioTrendItem,
    StatusResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


async def _run_scenarios_background(
    headless: bool, max_cost: float, filter_name: str | None,
) -> None:
    """Run scenarios in background and save results to DB."""
    from pathlib import Path

    from scripts.run_scenarios import run_single_scenario
    from scripts.scenario_types import load_scenarios

    db = get_db()
    notifier = get_notifier()
    version = await db.get_latest_version()

    definitions_path = "testing/scenarios/definitions.yaml"
    output_dir = Path("testing")

    try:
        scenarios = load_scenarios(definitions_path)
    except FileNotFoundError:
        logger.error("Scenario definitions not found: %s", definitions_path)
        return

    if filter_name:
        scenarios = [s for s in scenarios if filter_name in s.name]

    cost_so_far = 0.0
    for scenario in scenarios:
        if cost_so_far >= max_cost:
            break

        await notifier.publish("scenario_progress", {
            "scenario_name": scenario.name,
            "status": "running",
        })

        try:
            result = await run_single_scenario(
                scenario,
                headless=headless,
                output_dir=output_dir,
                cost_so_far=cost_so_far,
                max_cost=max_cost,
            )

            # Build phase details for DB
            phase_details = []
            for pr in result.phase_results:
                pd: dict[str, Any] = {
                    "phase_name": pr.phase.name,
                    "success": pr.run_result.success if pr.run_result else False,
                    "wall_time_s": pr.wall_time_s,
                }
                if pr.error:
                    pd["error"] = pr.error
                if pr.timed_out:
                    pd["timed_out"] = True
                if pr.run_result:
                    pd["steps_ok"] = sum(
                        1 for sr in pr.run_result.step_results if sr.success
                    )
                    pd["steps_all"] = len(pr.run_result.step_results)
                    pd["cost_usd"] = pr.run_result.total_cost_usd
                phase_details.append(pd)

            error_summary = None
            if not result.overall_success:
                errors = []
                for pr in result.phase_results:
                    if pr.error:
                        errors.append(f"{pr.phase.name}: {pr.error}")
                    elif pr.run_result and not pr.run_result.success:
                        failed = [
                            sr for sr in pr.run_result.step_results if not sr.success
                        ]
                        if failed:
                            errors.append(
                                f"{pr.phase.name}: {len(failed)} step(s) failed"
                            )
                error_summary = "; ".join(errors) if errors else "Unknown failure"

            await db.save_scenario_result(
                scenario_name=scenario.name,
                overall_success=result.overall_success,
                total_steps_ok=result.total_steps_ok,
                total_steps_all=result.total_steps_all,
                total_cost_usd=result.total_cost_usd,
                total_tokens=result.total_tokens,
                wall_time_s=result.total_wall_time_s,
                phase_details=phase_details,
                error_summary=error_summary,
                version=version,
            )

            cost_so_far += result.total_cost_usd

            await notifier.publish("scenario_progress", {
                "scenario_name": scenario.name,
                "status": "completed",
                "success": result.overall_success,
                "cost_usd": result.total_cost_usd,
            })

        except Exception as exc:
            logger.error("Scenario %s failed: %s", scenario.name, exc)
            await db.save_scenario_result(
                scenario_name=scenario.name,
                overall_success=False,
                error_summary=str(exc),
                version=version,
            )
            await notifier.publish("scenario_progress", {
                "scenario_name": scenario.name,
                "status": "error",
                "error": str(exc),
            })

    # Run failure analysis after scenarios
    from src.evolution.analyzer import FailureAnalyzer
    analyzer = FailureAnalyzer(db=db)
    await analyzer.analyze_latest_results()


@router.post("/run", response_model=StatusResponse)
async def run_scenarios(req: ScenarioRunRequest) -> StatusResponse:
    """Trigger scenario execution (async — returns immediately)."""
    asyncio.create_task(
        _run_scenarios_background(req.headless, req.max_cost, req.filter_name),
    )
    return StatusResponse(
        status="accepted",
        message="Scenario run started in background",
        data={"headless": req.headless, "max_cost": req.max_cost},
    )


@router.get("/results", response_model=list[ScenarioResultItem])
async def list_results(
    scenario_name: str | None = None, limit: int = 100,
) -> list[dict[str, Any]]:
    """List scenario results."""
    db = get_db()
    return await db.list_scenario_results(scenario_name=scenario_name, limit=limit)


@router.get("/trends", response_model=list[ScenarioTrendItem])
async def get_trends() -> list[dict[str, Any]]:
    """Get scenario success rate trends."""
    db = get_db()
    raw = await db.get_scenario_trends()
    for item in raw:
        total = item.get("total_runs", 0)
        item["success_rate"] = (item.get("successes", 0) / total * 100) if total else 0.0
    return raw
