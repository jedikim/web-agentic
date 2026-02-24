"""Evolution API routes — trigger, status, approve/reject."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.dependencies import get_db, get_notifier
from src.api.models import (
    ApproveRejectRequest,
    EvolutionChangeItem,
    EvolutionRunDetail,
    EvolutionRunSummary,
    EvolutionTriggerRequest,
    StatusResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evolution", tags=["evolution"])


@router.post("/trigger", response_model=StatusResponse)
async def trigger_evolution(req: EvolutionTriggerRequest) -> StatusResponse:
    """Trigger a new evolution cycle."""
    db = get_db()
    notifier = get_notifier()
    run = await db.create_evolution_run(
        trigger_reason=req.reason,
        trigger_data={"scenario_filter": req.scenario_filter},
    )

    # Launch pipeline in background
    from src.evolution.pipeline import EvolutionPipeline
    pipeline = EvolutionPipeline(db=db, notifier=notifier)
    asyncio.create_task(pipeline.execute(run["id"]))

    return StatusResponse(
        status="accepted",
        message=f"Evolution run {run['id']} started",
        data={"run_id": run["id"]},
    )


@router.get("/", response_model=list[EvolutionRunSummary])
async def list_evolutions(
    limit: int = 50, status: str | None = None,
) -> list[dict[str, Any]]:
    """List evolution runs."""
    db = get_db()
    return await db.list_evolution_runs(limit=limit, status=status)


@router.get("/{run_id}", response_model=EvolutionRunDetail)
async def get_evolution(run_id: str) -> dict[str, Any]:
    """Get evolution run detail with changes."""
    db = get_db()
    run = await db.get_evolution_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Evolution run not found")
    changes = await db.get_evolution_changes(run_id)
    run["changes"] = changes
    return run


@router.get("/{run_id}/diff")
async def get_evolution_diff(run_id: str) -> dict[str, Any]:
    """Get code diff for an evolution run."""
    db = get_db()
    run = await db.get_evolution_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Evolution run not found")
    changes = await db.get_evolution_changes(run_id)
    return {
        "run_id": run_id,
        "branch_name": run.get("branch_name"),
        "changes": [
            {
                "file_path": c["file_path"],
                "change_type": c["change_type"],
                "diff_content": c.get("diff_content"),
                "description": c["description"],
            }
            for c in changes
        ],
    }


@router.post("/{run_id}/approve", response_model=StatusResponse)
async def approve_evolution(run_id: str, req: ApproveRejectRequest) -> StatusResponse:
    """Approve an evolution run — merges the branch and creates a version."""
    db = get_db()
    notifier = get_notifier()
    run = await db.get_evolution_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Evolution run not found")
    if run["status"] != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Run status is '{run['status']}', expected 'awaiting_approval'",
        )

    from src.evolution.version_manager import VersionManager
    vm = VersionManager(db=db, notifier=notifier)
    try:
        version = await vm.approve_and_merge(run_id)
        return StatusResponse(
            status="merged",
            message=f"Merged as version {version}",
            data={"version": version, "run_id": run_id},
        )
    except Exception as exc:
        logger.error("Approve failed for %s: %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{run_id}/reject", response_model=StatusResponse)
async def reject_evolution(run_id: str, req: ApproveRejectRequest) -> StatusResponse:
    """Reject an evolution run — deletes the branch."""
    db = get_db()
    notifier = get_notifier()
    run = await db.get_evolution_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Evolution run not found")
    if run["status"] != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Run status is '{run['status']}', expected 'awaiting_approval'",
        )

    from src.evolution.sandbox import Sandbox
    sandbox = Sandbox()
    branch = run.get("branch_name")
    if branch:
        await sandbox.delete_branch(branch)

    await db.update_evolution_run(run_id, status="rejected")
    await notifier.publish("evolution_status", {
        "run_id": run_id, "status": "rejected",
    })
    return StatusResponse(
        status="rejected",
        message=f"Evolution run {run_id} rejected",
        data={"run_id": run_id},
    )
