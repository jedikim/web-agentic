"""Tests for file-based storage implementations."""

import json
import tempfile
from pathlib import Path

import pytest

from app.storage.profiles_repo import ProfilesRepo
from app.storage.task_specs_repo import TaskSpecsRepo


class TestProfilesRepo:
    @pytest.fixture
    def repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield ProfilesRepo(base_dir=tmp)

    def test_save_and_get(self, repo):
        data = {"id": "test-1", "version": 1, "instructions": "do stuff"}
        repo.save("test-1", data)
        loaded = repo.get("test-1")
        assert loaded == data

    def test_get_nonexistent_returns_none(self, repo):
        assert repo.get("nonexistent") is None

    def test_list_profiles(self, repo):
        repo.save("alpha", {"id": "alpha"})
        repo.save("beta", {"id": "beta"})
        profiles = repo.list()
        assert "alpha" in profiles
        assert "beta" in profiles

    def test_list_excludes_promoted_versions(self, repo):
        repo.save("prof", {"id": "prof"})
        repo.promote("prof", 1)
        repo.promote("prof", 2)
        profiles = repo.list()
        assert "prof" in profiles
        assert "prof_v1" not in profiles
        assert "prof_v2" not in profiles

    def test_delete(self, repo):
        repo.save("to-delete", {"id": "to-delete"})
        assert repo.delete("to-delete") is True
        assert repo.get("to-delete") is None
        assert repo.delete("to-delete") is False

    def test_promote(self, repo):
        repo.save("p1", {"id": "p1", "score": 0.9})
        promoted_id = repo.promote("p1", 1)
        assert promoted_id == "p1_v1"

        promoted_data = repo.get("p1_v1")
        assert promoted_data["version"] == 1
        assert promoted_data["promoted"] is True
        assert promoted_data["score"] == 0.9

    def test_promote_nonexistent_raises(self, repo):
        with pytest.raises(FileNotFoundError):
            repo.promote("nonexistent", 1)

    def test_list_versions(self, repo):
        repo.save("p2", {"id": "p2"})
        repo.promote("p2", 1)
        repo.promote("p2", 3)
        repo.promote("p2", 2)
        versions = repo.list_versions("p2")
        assert versions == [1, 2, 3]

    def test_list_versions_empty(self, repo):
        repo.save("p3", {"id": "p3"})
        assert repo.list_versions("p3") == []

    def test_creates_directory_on_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            subdir = Path(tmp) / "nested" / "profiles"
            repo = ProfilesRepo(base_dir=subdir)
            assert subdir.exists()

    def test_save_unicode(self, repo):
        data = {"id": "unicode", "name": "flight booking"}
        repo.save("unicode", data)
        loaded = repo.get("unicode")
        assert loaded["name"] == "flight booking"


class TestTaskSpecsRepo:
    @pytest.fixture
    def repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield TaskSpecsRepo(base_dir=tmp)

    def test_add_and_get_spec(self, repo):
        spec = {"id": "spec-1", "goal": "book flight", "domain": "airline.com"}
        spec_id = repo.add_spec(spec)
        assert spec_id == "spec-1"

        loaded = repo.get_spec("spec-1")
        assert loaded["goal"] == "book flight"

    def test_add_spec_auto_id(self, repo):
        spec = {"goal": "test"}
        spec_id = repo.add_spec(spec)
        assert spec_id  # should be a UUID
        loaded = repo.get_spec(spec_id)
        assert loaded["goal"] == "test"
        assert loaded["id"] == spec_id

    def test_get_specs_all(self, repo):
        repo.add_spec({"id": "s1", "goal": "task 1"})
        repo.add_spec({"id": "s2", "goal": "task 2"})
        specs = repo.get_specs()
        assert len(specs) == 2
        goals = {s["goal"] for s in specs}
        assert goals == {"task 1", "task 2"}

    def test_get_specs_empty(self, repo):
        assert repo.get_specs() == []

    def test_get_spec_nonexistent(self, repo):
        assert repo.get_spec("nonexistent") is None

    def test_delete_spec(self, repo):
        repo.add_spec({"id": "to-rm", "goal": "delete me"})
        assert repo.delete_spec("to-rm") is True
        assert repo.get_spec("to-rm") is None
        assert repo.delete_spec("to-rm") is False

    def test_creates_directory_on_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            subdir = Path(tmp) / "nested" / "task_specs"
            repo = TaskSpecsRepo(base_dir=subdir)
            assert subdir.exists()

    def test_handles_corrupt_json(self, repo):
        # Write an invalid JSON file
        bad_path = Path(repo.base_dir) / "bad.json"
        bad_path.write_text("{invalid json", encoding="utf-8")
        specs = repo.get_specs()
        assert len(specs) == 0  # should skip corrupt files

    def test_adds_id_if_missing_in_file(self, repo):
        # Write a file without an id field
        path = Path(repo.base_dir) / "no_id.json"
        path.write_text(json.dumps({"goal": "test"}), encoding="utf-8")
        specs = repo.get_specs()
        assert len(specs) == 1
        assert specs[0]["id"] == "no_id"  # stem of file
