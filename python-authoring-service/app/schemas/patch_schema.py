from pydantic import BaseModel, Field


class PatchOp(BaseModel):
    op: str  # actions.replace | actions.add | selectors.add | selectors.replace | workflow.update_expect | policies.update
    key: str | None = None
    step: str | None = None
    value: object


class PlanPatchRequest(BaseModel):
    request_id: str = Field(alias="requestId")
    step_id: str
    error_type: str
    url: str
    title: str | None = None
    failed_selector: str | None = None
    failed_action: dict | None = None
    dom_snippet: str | None = None
    screenshot_base64: str | None = None

    model_config = {"populate_by_name": True}


class PlanPatchResponse(BaseModel):
    request_id: str = Field(alias="requestId")
    patch: list[PatchOp]
    reason: str

    model_config = {"populate_by_name": True}
