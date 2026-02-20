import pytest
from app.storage.profiles_repo import ProfilesRepo
from app.storage.task_specs_repo import TaskSpecsRepo


@pytest.mark.asyncio
async def test_profiles_repo_get_returns_none():
    repo = ProfilesRepo()
    result = await repo.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_profiles_repo_save_does_not_raise():
    repo = ProfilesRepo()
    await repo.save("profile-1", {"key": "value"})


@pytest.mark.asyncio
async def test_task_specs_repo_get_returns_empty():
    repo = TaskSpecsRepo()
    result = await repo.get_specs()
    assert result == []


@pytest.mark.asyncio
async def test_task_specs_repo_add_does_not_raise():
    repo = TaskSpecsRepo()
    await repo.add_spec({"goal": "test", "procedure": "step1"})
