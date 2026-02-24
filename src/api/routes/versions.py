"""Version API routes — list, detail, rollback."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.dependencies import get_db, get_notifier
from src.api.models import RollbackRequest, StatusResponse, VersionRecord

router = APIRouter(prefix="/api/versions", tags=["versions"])


@router.get("/", response_model=list[VersionRecord])
async def list_versions(limit: int = 50) -> list[dict[str, Any]]:
    """List version records."""
    db = get_db()
    return await db.list_version_records(limit=limit)


@router.get("/current")
async def get_current_version() -> dict[str, str]:
    """Get the current (latest) version."""
    db = get_db()
    version = await db.get_latest_version()
    return {"version": version}


@router.get("/{version}", response_model=VersionRecord)
async def get_version(version: str) -> dict[str, Any]:
    """Get version detail."""
    db = get_db()
    record = await db.get_version_record(version)
    if not record:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")
    return record


@router.post("/rollback", response_model=StatusResponse)
async def rollback_version(req: RollbackRequest) -> StatusResponse:
    """Rollback to a previous version."""
    db = get_db()
    notifier = get_notifier()
    target = await db.get_version_record(req.target_version)
    if not target:
        raise HTTPException(
            status_code=404, detail=f"Version {req.target_version} not found",
        )

    from src.evolution.version_manager import VersionManager
    vm = VersionManager(db=db, notifier=notifier)
    try:
        new_version = await vm.rollback(req.target_version)
        return StatusResponse(
            status="rolled_back",
            message=f"Rolled back to {req.target_version} as version {new_version}",
            data={"new_version": new_version, "target_version": req.target_version},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
