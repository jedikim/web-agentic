import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_compile_intent_schema_validation(client):
    response = await client.post("/compile-intent", json={})
    assert response.status_code == 422  # validation error


@pytest.mark.asyncio
async def test_compile_intent_success(client):
    payload = {
        "requestId": "req-001",
        "goal": "Book a flight",
        "domain": "airline.com",
    }
    response = await client.post("/compile-intent", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["requestId"] == "req-001"
    assert data["workflow"]["id"] == "airline.com_flow"
    assert len(data["workflow"]["steps"]) == 2
    assert data["workflow"]["steps"][0]["op"] == "goto"
    assert data["actions"] == {}
    assert data["selectors"] == {}
    assert data["policies"] == {}
    assert data["fingerprints"] == {}


@pytest.mark.asyncio
async def test_plan_patch_schema_validation(client):
    response = await client.post("/plan-patch", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_plan_patch_success_with_dom_snippet(client):
    payload = {
        "requestId": "req-002",
        "step_id": "login",
        "error_type": "TargetNotFound",
        "url": "https://example.com/login",
        "dom_snippet": '<button id="sign-in-btn" class="primary">Sign In</button>',
    }
    response = await client.post("/plan-patch", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["requestId"] == "req-002"
    assert len(data["patch"]) == 1
    assert data["patch"][0]["op"] == "actions.replace"
    assert "reason" in data and len(data["reason"]) > 0


@pytest.mark.asyncio
async def test_plan_patch_no_context_returns_empty_patch(client):
    payload = {
        "requestId": "req-002b",
        "step_id": "login",
        "error_type": "TargetNotFound",
        "url": "https://example.com/login",
    }
    response = await client.post("/plan-patch", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["requestId"] == "req-002b"
    assert data["patch"] == []
    assert "reason" in data and len(data["reason"]) > 0


@pytest.mark.asyncio
async def test_plan_patch_unknown_error_type(client):
    payload = {
        "requestId": "req-002c",
        "step_id": "captcha",
        "error_type": "CaptchaOr2FA",
        "url": "https://example.com",
    }
    response = await client.post("/plan-patch", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["patch"] == []
    assert "No strategy" in data["reason"]


@pytest.mark.asyncio
async def test_optimize_profile_success(client):
    payload = {
        "requestId": "req-003",
        "profile_id": "profile-1",
    }
    response = await client.post("/optimize-profile", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["requestId"] == "req-003"
    assert data["status"] == "queued"


@pytest.mark.asyncio
async def test_optimize_profile_schema_validation(client):
    response = await client.post("/optimize-profile", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_profile_not_found(client):
    response = await client.get("/profiles/nonexistent")
    assert response.status_code == 404
    assert "nonexistent" in response.json()["detail"]
