from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.gepa.eval_harness import EvalHarness
from app.gepa.optimizer import GEPAOptimizer, OptimizationResult
from app.storage.profiles_repo import ProfilesRepo
from app.storage.task_specs_repo import TaskSpecsRepo

router = APIRouter()

# Shared state for tracking background optimization jobs
_optimization_jobs: dict[str, dict] = {}


class OptimizeRequest(BaseModel):
    request_id: str = Field(alias="requestId")
    profile_id: str
    task_specs: list[dict] | None = None
    max_rounds: int = 5

    model_config = {"populate_by_name": True}


class OptimizeResponse(BaseModel):
    request_id: str = Field(alias="requestId")
    status: str  # queued | running | completed | failed

    model_config = {"populate_by_name": True}


class OptimizeStatusResponse(BaseModel):
    request_id: str = Field(alias="requestId")
    status: str
    result: dict | None = None

    model_config = {"populate_by_name": True}


def _run_optimization(request_id: str, profile_id: str, max_rounds: int, task_specs: list[dict] | None) -> None:
    """Background task that runs GEPA optimization."""
    _optimization_jobs[request_id] = {"status": "running"}

    try:
        profiles_repo = ProfilesRepo()
        task_specs_repo = TaskSpecsRepo()

        # If task specs were provided in the request, add them
        if task_specs:
            for spec in task_specs:
                task_specs_repo.add_spec(spec)

        eval_harness = EvalHarness()
        optimizer = GEPAOptimizer(profiles_repo, task_specs_repo, eval_harness)
        result = optimizer.optimize(profile_id, max_rounds=max_rounds)

        _optimization_jobs[request_id] = {
            "status": "completed",
            "result": {
                "profile_id": result.profile_id,
                "rounds": result.rounds,
                "final_score": result.final_score,
                "promoted": result.promoted,
                "promoted_version": result.promoted_version,
            },
        }
    except Exception as e:
        _optimization_jobs[request_id] = {
            "status": "failed",
            "result": {"error": str(e)},
        }


@router.post("", response_model=OptimizeResponse)
async def optimize_profile(request: OptimizeRequest, background_tasks: BackgroundTasks):
    _optimization_jobs[request.request_id] = {"status": "queued"}
    background_tasks.add_task(
        _run_optimization,
        request.request_id,
        request.profile_id,
        request.max_rounds,
        request.task_specs,
    )
    return OptimizeResponse(requestId=request.request_id, status="queued")


@router.get("/status/{request_id}", response_model=OptimizeStatusResponse)
async def optimization_status(request_id: str):
    job = _optimization_jobs.get(request_id)
    if job is None:
        return OptimizeStatusResponse(requestId=request_id, status="not_found")
    return OptimizeStatusResponse(
        requestId=request_id,
        status=job["status"],
        result=job.get("result"),
    )
