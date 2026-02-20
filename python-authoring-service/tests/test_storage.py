import tempfile

import pytest

from app.storage.profiles_repo import ProfilesRepo
from app.storage.task_specs_repo import TaskSpecsRepo


def test_profiles_repo_get_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        repo = ProfilesRepo(base_dir=tmp)
        result = repo.get("nonexistent")
        assert result is None


def test_profiles_repo_save_does_not_raise():
    with tempfile.TemporaryDirectory() as tmp:
        repo = ProfilesRepo(base_dir=tmp)
        repo.save("profile-1", {"key": "value"})


def test_task_specs_repo_get_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        repo = TaskSpecsRepo(base_dir=tmp)
        result = repo.get_specs()
        assert result == []


def test_task_specs_repo_add_does_not_raise():
    with tempfile.TemporaryDirectory() as tmp:
        repo = TaskSpecsRepo(base_dir=tmp)
        repo.add_spec({"goal": "test", "procedure": "step1"})
