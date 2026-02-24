"""Integration tests for the Evolution API — httpx AsyncClient.

Tests all endpoints with a real (temporary) SQLite DB.
No external services (LLM, browser) are called; background tasks
are patched or tested in isolation.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI

from src.api.dependencies import set_db, set_notifier
from src.api.routes import evolution, progress, scenarios, versions
from src.evolution.db import EvolutionDB
from src.evolution.notifier import Notifier


# ── Test App (no lifespan — we manage DI manually) ───


def _create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(evolution.router)
    app.include_router(scenarios.router)
    app.include_router(versions.router)
    app.include_router(progress.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "evolution-api"}

    return app


_app = _create_test_app()


@pytest.fixture
async def db() -> AsyncIterator[EvolutionDB]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    evo_db = EvolutionDB(db_path=path)
    await evo_db.init()
    set_db(evo_db)
    yield evo_db
    await evo_db.close()
    os.unlink(path)


@pytest.fixture
def notifier() -> Notifier:
    n = Notifier()
    set_notifier(n)
    return n


@pytest.fixture
async def client(
    db: EvolutionDB, notifier: Notifier,
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Health ───────────────────────────────────────────


async def test_health(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


# ── Evolution Routes ─────────────────────────────────


async def test_list_evolutions_empty(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/evolution/")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_trigger_evolution(client: httpx.AsyncClient) -> None:
    with patch("src.evolution.pipeline.EvolutionPipeline") as mock_cls:
        mock_cls.return_value = AsyncMock()
        resp = await client.post(
            "/api/evolution/trigger",
            json={"reason": "test_trigger"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert "run_id" in data["data"]


async def test_trigger_and_list_evolution(client: httpx.AsyncClient) -> None:
    with patch("src.evolution.pipeline.EvolutionPipeline") as mock_cls:
        mock_cls.return_value = AsyncMock()
        await client.post("/api/evolution/trigger", json={"reason": "from_test"})

    resp = await client.get("/api/evolution/")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    assert runs[0]["trigger_reason"] == "from_test"
    assert runs[0]["status"] == "pending"


async def test_get_evolution_detail(client: httpx.AsyncClient) -> None:
    with patch("src.evolution.pipeline.EvolutionPipeline") as mock_cls:
        mock_cls.return_value = AsyncMock()
        resp = await client.post("/api/evolution/trigger", json={"reason": "detail_test"})
        run_id = resp.json()["data"]["run_id"]

    resp = await client.get(f"/api/evolution/{run_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == run_id
    assert "changes" in detail


async def test_get_evolution_not_found(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/evolution/nonexistent")
    assert resp.status_code == 404


async def test_get_evolution_diff(client: httpx.AsyncClient) -> None:
    with patch("src.evolution.pipeline.EvolutionPipeline") as mock_cls:
        mock_cls.return_value = AsyncMock()
        resp = await client.post("/api/evolution/trigger", json={"reason": "diff_test"})
        run_id = resp.json()["data"]["run_id"]

    resp = await client.get(f"/api/evolution/{run_id}/diff")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == run_id
    assert "changes" in data


async def test_approve_wrong_status(client: httpx.AsyncClient) -> None:
    with patch("src.evolution.pipeline.EvolutionPipeline") as mock_cls:
        mock_cls.return_value = AsyncMock()
        resp = await client.post("/api/evolution/trigger", json={"reason": "approve_test"})
        run_id = resp.json()["data"]["run_id"]

    resp = await client.post(f"/api/evolution/{run_id}/approve", json={})
    assert resp.status_code == 400
    assert "awaiting_approval" in resp.json()["detail"]


async def test_reject_wrong_status(client: httpx.AsyncClient) -> None:
    with patch("src.evolution.pipeline.EvolutionPipeline") as mock_cls:
        mock_cls.return_value = AsyncMock()
        resp = await client.post("/api/evolution/trigger", json={"reason": "reject_test"})
        run_id = resp.json()["data"]["run_id"]

    resp = await client.post(f"/api/evolution/{run_id}/reject", json={})
    assert resp.status_code == 400


async def test_approve_awaiting_run(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    run = await db.create_evolution_run(trigger_reason="approve_ok")
    await db.update_evolution_run(
        run["id"], status="awaiting_approval", branch_name="evolution/test",
    )

    with patch("src.evolution.version_manager.VersionManager") as mock_vm_cls:
        mock_vm = AsyncMock()
        mock_vm.approve_and_merge.return_value = "0.1.1"
        mock_vm_cls.return_value = mock_vm
        resp = await client.post(f"/api/evolution/{run['id']}/approve", json={})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "merged"
    assert data["data"]["version"] == "0.1.1"


async def test_reject_awaiting_run(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    run = await db.create_evolution_run(trigger_reason="reject_ok")
    await db.update_evolution_run(
        run["id"], status="awaiting_approval", branch_name="evolution/rej",
    )

    with patch("src.evolution.sandbox.Sandbox.delete_branch", new_callable=AsyncMock):
        resp = await client.post(f"/api/evolution/{run['id']}/reject", json={})

    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    updated = await db.get_evolution_run(run["id"])
    assert updated is not None
    assert updated["status"] == "rejected"


# ── Scenario Routes ──────────────────────────────────


async def test_list_scenario_results_empty(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/scenarios/results")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_run_scenarios_accepted(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/scenarios/run",
        json={"headless": True, "max_cost": 0.10},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


async def test_list_scenario_results_with_data(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    await db.save_scenario_result(
        scenario_name="test_scenario",
        overall_success=True,
        total_steps_ok=5,
        total_steps_all=5,
        total_cost_usd=0.05,
        total_tokens=2000,
        wall_time_s=15.0,
    )

    resp = await client.get("/api/scenarios/results")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["scenario_name"] == "test_scenario"
    assert results[0]["overall_success"] is True


async def test_scenario_results_filtered(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    await db.save_scenario_result(scenario_name="alpha", overall_success=True)
    await db.save_scenario_result(scenario_name="beta", overall_success=False)

    resp = await client.get("/api/scenarios/results?scenario_name=alpha")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["scenario_name"] == "alpha"


async def test_scenario_trends(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    for i in range(5):
        await db.save_scenario_result(
            scenario_name="trend_test",
            overall_success=i % 2 == 0,
            total_cost_usd=0.1,
            wall_time_s=10.0,
        )

    resp = await client.get("/api/scenarios/trends")
    assert resp.status_code == 200
    trends = resp.json()
    assert len(trends) == 1
    assert trends[0]["scenario_name"] == "trend_test"
    assert trends[0]["success_rate"] == pytest.approx(60.0)


# ── Version Routes ───────────────────────────────────


async def test_list_versions_empty(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/versions/")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_current_version_default(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/versions/current")
    assert resp.status_code == 200
    assert resp.json()["version"] == "0.1.0"


async def test_list_versions_with_data(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    await db.create_version_record(version="0.1.1", changelog="Fix A")
    await db.create_version_record(version="0.1.2", changelog="Fix B")

    resp = await client.get("/api/versions/")
    assert resp.status_code == 200
    records = resp.json()
    assert len(records) == 2
    assert records[0]["version"] == "0.1.2"


async def test_get_version_detail(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    await db.create_version_record(
        version="0.2.0", changelog="Big release",
        git_tag="v0.2.0", git_commit="abc123",
    )

    resp = await client.get("/api/versions/0.2.0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "0.2.0"
    assert data["changelog"] == "Big release"
    assert data["git_tag"] == "v0.2.0"


async def test_get_version_not_found(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/versions/99.99.99")
    assert resp.status_code == 404


async def test_get_current_version_after_insert(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    await db.create_version_record(version="1.0.0", changelog="v1")

    resp = await client.get("/api/versions/current")
    assert resp.status_code == 200
    assert resp.json()["version"] == "1.0.0"


async def test_rollback_not_found(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/versions/rollback",
        json={"target_version": "0.0.0"},
    )
    assert resp.status_code == 404


# ── Cross-cutting ────────────────────────────────────


async def test_evolution_changes_in_detail(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    run = await db.create_evolution_run(trigger_reason="changes_test")
    await db.add_evolution_change(
        evolution_run_id=run["id"],
        file_path="src/core/executor.py",
        change_type="modify",
        description="Fixed timeout",
        new_content="# new content",
    )
    await db.add_evolution_change(
        evolution_run_id=run["id"],
        file_path="src/ai/llm_planner.py",
        change_type="modify",
        description="Improved parsing",
    )

    resp = await client.get(f"/api/evolution/{run['id']}")
    assert resp.status_code == 200
    detail = resp.json()
    assert len(detail["changes"]) == 2
    assert detail["changes"][0]["file_path"] == "src/core/executor.py"


async def test_evolution_diff_includes_changes(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    run = await db.create_evolution_run(trigger_reason="diff_changes")
    await db.update_evolution_run(run["id"], branch_name="evolution/diff123")
    await db.add_evolution_change(
        evolution_run_id=run["id"],
        file_path="src/test.py",
        change_type="create",
        description="New test file",
        diff_content="+# new file",
    )

    resp = await client.get(f"/api/evolution/{run['id']}/diff")
    assert resp.status_code == 200
    data = resp.json()
    assert data["branch_name"] == "evolution/diff123"
    assert len(data["changes"]) == 1
    assert data["changes"][0]["diff_content"] == "+# new file"


async def test_list_evolutions_by_status(
    db: EvolutionDB, client: httpx.AsyncClient,
) -> None:
    run1 = await db.create_evolution_run(trigger_reason="a")
    await db.create_evolution_run(trigger_reason="b")
    await db.update_evolution_run(run1["id"], status="merged")

    resp = await client.get("/api/evolution/?status=merged")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    assert runs[0]["status"] == "merged"

    resp = await client.get("/api/evolution/?status=pending")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    assert runs[0]["status"] == "pending"
