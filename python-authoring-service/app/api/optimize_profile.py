from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

router = APIRouter()


class OptimizeRequest(BaseModel):
    request_id: str = Field(alias="requestId")
    profile_id: str
    task_specs: list[dict] | None = None

    model_config = {"populate_by_name": True}


class OptimizeResponse(BaseModel):
    request_id: str = Field(alias="requestId")
    status: str  # queued

    model_config = {"populate_by_name": True}


@router.post("", response_model=OptimizeResponse)
async def optimize_profile(request: OptimizeRequest, background_tasks: BackgroundTasks):
    # TODO: Queue optimization job
    background_tasks.add_task(lambda: None)  # stub
    return OptimizeResponse(requestId=request.request_id, status="queued")
