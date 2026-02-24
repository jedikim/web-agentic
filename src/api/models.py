"""Pydantic v2 request/response models for the Evolution API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── Evolution ────────────────────────────────────────


class EvolutionTriggerRequest(BaseModel):
    """Request to trigger a new evolution cycle."""
    reason: str = Field(default="manual", description="Trigger reason")
    scenario_filter: str | None = Field(default=None, description="Only analyze this scenario")


class EvolutionRunSummary(BaseModel):
    """Summary of an evolution run."""
    id: str
    status: str
    trigger_reason: str
    branch_name: str | None = None
    analysis_summary: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None
    error_message: str | None = None


class EvolutionRunDetail(EvolutionRunSummary):
    """Detailed evolution run with changes."""
    trigger_data: str = "{}"
    base_commit: str | None = None
    changes: list[EvolutionChangeItem] = []


class EvolutionChangeItem(BaseModel):
    """A single file change in an evolution run."""
    id: str
    file_path: str
    change_type: str
    diff_content: str | None = None
    description: str
    created_at: str


# Forward ref resolution
EvolutionRunDetail.model_rebuild()


class ApproveRejectRequest(BaseModel):
    """Request to approve or reject an evolution run."""
    comment: str | None = Field(default=None, description="Optional comment")


# ── Scenarios ────────────────────────────────────────


class ScenarioRunRequest(BaseModel):
    """Request to run scenarios."""
    headless: bool = Field(default=True, description="Run browser headless")
    max_cost: float = Field(default=0.50, description="Max cost in USD")
    filter_name: str | None = Field(default=None, description="Filter scenario by name")


class ScenarioResultItem(BaseModel):
    """A single scenario result."""
    id: str
    scenario_name: str
    version: str | None = None
    overall_success: bool
    total_steps_ok: int = 0
    total_steps_all: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    wall_time_s: float = 0.0
    error_summary: str | None = None
    created_at: str


class ScenarioTrendItem(BaseModel):
    """Trend data for a scenario."""
    scenario_name: str
    total_runs: int
    successes: int
    avg_cost: float
    avg_time: float
    success_rate: float = 0.0


# ── Versions ─────────────────────────────────────────


class VersionRecord(BaseModel):
    """A version record."""
    id: str
    version: str
    previous_version: str | None = None
    evolution_run_id: str | None = None
    changelog: str
    test_results: dict = {}  # noqa: RUF012
    git_tag: str | None = None
    git_commit: str | None = None
    created_at: str


class RollbackRequest(BaseModel):
    """Request to rollback to a specific version."""
    target_version: str = Field(description="Version to rollback to")


# ── Generic ──────────────────────────────────────────


class StatusResponse(BaseModel):
    """Generic status response."""
    status: str
    message: str
    data: dict = {}  # noqa: RUF012


# ── Sessions ────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    """Request to create a new browser session."""
    url: str | None = None
    headless: bool = True
    context: dict[str, Any] = Field(default_factory=dict)


class CreateSessionResponse(BaseModel):
    """Response after creating a session."""
    session_id: str
    status: str
    headless: bool
    created_at: str


class AttachmentData(BaseModel):
    """An attached file (image) sent with a turn request."""
    filename: str
    mime_type: str
    base64_data: str


class ExecuteTurnRequest(BaseModel):
    """Request to execute a turn within a session."""
    intent: str
    attachments: list[AttachmentData] = Field(default_factory=list)


class ExecuteTurnResponse(BaseModel):
    """Response after executing a turn."""
    turn_id: str
    turn_num: int
    session_id: str
    success: bool
    steps_total: int
    steps_ok: int
    cost_usd: float
    tokens_used: int
    error_msg: str | None = None
    screenshots: list[str]
    current_url: str | None = None
    pending_handoffs: int = 0


class SessionListItem(BaseModel):
    """Summary item for listing sessions."""
    id: str
    status: str
    headless: bool
    initial_url: str | None
    current_url: str | None
    total_cost_usd: float
    turn_count: int
    created_at: str
    last_activity: str


class SessionTurnItem(BaseModel):
    """A single turn within a session."""
    id: str
    turn_num: int
    intent: str
    success: bool
    cost_usd: float
    tokens_used: int
    steps_total: int
    steps_ok: int
    error_msg: str | None = None
    started_at: str
    completed_at: str | None = None


class SessionDetail(BaseModel):
    """Detailed session info with turns."""
    id: str
    status: str
    headless: bool
    initial_url: str | None
    current_url: str | None
    total_cost_usd: float
    total_tokens: int
    turn_count: int
    context: dict[str, Any]
    created_at: str
    last_activity: str
    closed_at: str | None = None
    turns: list[SessionTurnItem]


class HandoffItem(BaseModel):
    """A pending handoff request."""
    request_id: str
    reason: str
    url: str
    title: str
    message: str
    has_screenshot: bool
    created_at: str


class ResolveHandoffRequest(BaseModel):
    """Request to resolve a handoff."""
    action_taken: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class OneShotRequest(BaseModel):
    """Request for one-shot execution."""
    intent: str
    url: str | None = None
    headless: bool = True


class OneShotResponse(BaseModel):
    """Response from one-shot execution."""
    success: bool
    steps_total: int
    steps_ok: int
    cost_usd: float
    tokens_used: int
    error_msg: str | None = None
    screenshots: list[str]
    final_url: str | None = None
