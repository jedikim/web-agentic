"""Unit tests for v4 Knowledge Base system.

Covers CacheKey, KBManager, and MaturityTracker.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.kb.cache_key import CacheKey
from src.kb.manager import KBManager
from src.kb.maturity import MaturityTracker
from src.models.maturity import MaturityState
from src.models.site_profile import SiteProfile

# ── CacheKey ──


def test_pattern_dir_search() -> None:
    """/search?query=* -> 'search'."""
    key = CacheKey(domain="example.com", url_pattern="/search?query=*", artifact_type="workflow")
    assert key.pattern_dir == "search"


def test_pattern_dir_catalog() -> None:
    """/catalog/* -> 'catalog'."""
    key = CacheKey(domain="example.com", url_pattern="/catalog/*", artifact_type="workflow")
    assert key.pattern_dir == "catalog"


def test_pattern_dir_root() -> None:
    """/ -> 'root'."""
    key = CacheKey(domain="example.com", url_pattern="/", artifact_type="profile")
    assert key.pattern_dir == "root"


def test_cache_key_str() -> None:
    key = CacheKey(domain="shop.example.com", url_pattern="/catalog/*", artifact_type="macro")
    assert str(key) == "shop.example.com/catalog/macro"


# ── KBManager — Profile ──


def _make_profile(domain: str = "example.com", version: int = 1) -> SiteProfile:
    return SiteProfile(
        domain=domain,
        purpose="ecommerce",
        language="ko",
        region="KR",
        recon_version=version,
        created_at=datetime.now(),
        last_recon_at=datetime.now(),
    )


def test_save_and_load_profile(tmp_path: Path) -> None:
    """Profile roundtrip: save then load."""
    mgr = KBManager(base_dir=tmp_path)
    profile = _make_profile()

    ver = mgr.save_profile(profile)
    assert ver == 1

    loaded = mgr.load_profile("example.com")
    assert loaded is not None
    assert loaded.domain == "example.com"
    assert loaded.purpose == "ecommerce"
    assert loaded.language == "ko"


def test_load_missing_profile(tmp_path: Path) -> None:
    """Loading a non-existent profile returns None."""
    mgr = KBManager(base_dir=tmp_path)
    assert mgr.load_profile("nonexistent.com") is None


def test_profile_versioning(tmp_path: Path) -> None:
    """Saving v1, v2 creates separate history files."""
    mgr = KBManager(base_dir=tmp_path)

    p1 = _make_profile(version=1)
    mgr.save_profile(p1)

    p2 = _make_profile(version=2)
    p2.purpose = "portal"
    mgr.save_profile(p2)

    history_dir = tmp_path / "example.com" / "profile_history"
    assert (history_dir / "v1.json").exists()
    assert (history_dir / "v2.json").exists()

    # Current profile should be v2
    loaded = mgr.load_profile("example.com")
    assert loaded is not None
    assert loaded.purpose == "portal"
    assert loaded.recon_version == 2

    # v1 history preserved
    v1_data = json.loads((history_dir / "v1.json").read_text())
    assert v1_data["purpose"] == "ecommerce"


def test_is_profile_expired(tmp_path: Path) -> None:
    mgr = KBManager(base_dir=tmp_path)

    fresh = _make_profile()
    assert not mgr.is_profile_expired(fresh, max_age_hours=168)

    old = _make_profile()
    old.last_recon_at = datetime.now() - timedelta(hours=200)
    assert mgr.is_profile_expired(old, max_age_hours=168)


# ── KBManager — Workflow ──


def test_save_and_load_workflow(tmp_path: Path) -> None:
    """Workflow DSL roundtrip with current symlink."""
    mgr = KBManager(base_dir=tmp_path)
    domain = "shop.example.com"
    pattern = "/search?query=*"
    dsl = {"steps": [{"action": "click", "selector": "#btn"}]}

    mgr.save_pattern_meta(domain, pattern, "search")
    ver = mgr.save_workflow(domain, pattern, dsl)
    assert ver == 1

    loaded = mgr.load_workflow(domain, pattern)
    assert loaded is not None
    assert loaded["steps"][0]["action"] == "click"

    # current symlink exists
    wf_dir = tmp_path / domain / "url_patterns" / "search" / "workflows"
    current = wf_dir / "current"
    assert current.is_symlink()


# ── KBManager — Prompts ──


def test_save_and_load_prompts(tmp_path: Path) -> None:
    """Prompts roundtrip with current symlink."""
    mgr = KBManager(base_dir=tmp_path)
    domain = "shop.example.com"
    pattern = "/catalog/*"
    prompts = {"plan": "Plan the task: $task", "select": "Select element for: $goal"}

    mgr.save_pattern_meta(domain, pattern, "catalog")
    ver = mgr.save_prompts(domain, pattern, prompts)
    assert ver == 1

    loaded = mgr.load_prompts(domain, pattern)
    assert loaded is not None
    assert loaded["plan"] == "Plan the task: $task"
    assert loaded["select"] == "Select element for: $goal"

    # current symlink exists
    prompts_dir = tmp_path / domain / "url_patterns" / "catalog" / "prompts"
    current = prompts_dir / "current"
    assert current.is_symlink()


# ── KBManager — Lookup ──


def test_lookup_cold_no_profile(tmp_path: Path) -> None:
    """Lookup with no profile at all returns cold."""
    mgr = KBManager(base_dir=tmp_path)
    result = mgr.lookup("unknown.com", "/")
    assert not result.hit
    assert result.stage == "cold"
    assert result.reason == "no_profile"
    assert result.profile is None


def test_lookup_warm_workflow_only(tmp_path: Path) -> None:
    """Profile + workflow but no prompts -> warm."""
    mgr = KBManager(base_dir=tmp_path)
    domain = "shop.example.com"
    pattern = "/search?query=*"

    mgr.save_profile(_make_profile(domain=domain))
    mgr.save_pattern_meta(domain, pattern, "search")
    mgr.save_workflow(domain, pattern, {"steps": []})

    result = mgr.lookup(domain, "/search?query=laptop")
    assert result.hit
    assert result.stage == "warm"
    assert result.reason == "workflow_only"
    assert result.profile is not None
    assert result.workflow is not None
    assert result.prompts is None


def test_lookup_hot_full_cache(tmp_path: Path) -> None:
    """Profile + workflow + prompts -> hot."""
    mgr = KBManager(base_dir=tmp_path)
    domain = "shop.example.com"
    pattern = "/search?query=*"

    mgr.save_profile(_make_profile(domain=domain))
    mgr.save_pattern_meta(domain, pattern, "search")
    mgr.save_workflow(domain, pattern, {"steps": [{"action": "type"}]})
    mgr.save_prompts(domain, pattern, {"plan": "do it"})

    result = mgr.lookup(domain, "/search?query=shoes")
    assert result.hit
    assert result.stage == "hot"
    assert result.reason == "full_cache"
    assert result.profile is not None
    assert result.workflow is not None
    assert result.prompts is not None
    assert result.prompts["plan"] == "do it"


# ── KBManager — URL matching ──


def test_url_matches_wildcard() -> None:
    """Wildcard URL pattern matching."""
    assert KBManager._url_matches("/catalog/123", "/catalog/*")
    assert KBManager._url_matches("/catalog/abc/def", "/catalog/*")
    assert not KBManager._url_matches("/products/123", "/catalog/*")

    # Exact match (no wildcard)
    assert KBManager._url_matches("/about", "/about")
    assert not KBManager._url_matches("/about/team", "/about")

    # Query-string patterns: path portion matches
    assert KBManager._url_matches("/search?query=laptop", "/search?query=*")

    # Empty pattern
    assert not KBManager._url_matches("/anything", "")


# ── KBManager — Run History ──


def test_append_run(tmp_path: Path) -> None:
    mgr = KBManager(base_dir=tmp_path)
    domain = "example.com"

    mgr.append_run(domain, {"task": "search", "success": True, "cost": 0.003})
    mgr.append_run(domain, {"task": "filter", "success": False, "cost": 0.001})

    runs_file = tmp_path / domain / "history" / "runs.jsonl"
    assert runs_file.exists()

    lines = runs_file.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["task"] == "search"
    assert json.loads(lines[1])["success"] is False


# ── MaturityTracker ──


def test_load_missing_returns_cold(tmp_path: Path) -> None:
    """Loading maturity for unknown domain returns cold state."""
    tracker = MaturityTracker(base_dir=tmp_path)
    state = tracker.load("unknown.com")
    assert state.domain == "unknown.com"
    assert state.stage == "cold"
    assert state.total_runs == 0


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """MaturityState save/load roundtrip."""
    tracker = MaturityTracker(base_dir=tmp_path)
    state = MaturityState(
        domain="example.com",
        stage="warm",
        total_runs=5,
        recent_success_rate=0.8,
        consecutive_successes=3,
        llm_calls_last_10=2,
    )
    tracker.save(state)

    loaded = tracker.load("example.com")
    assert loaded.domain == "example.com"
    assert loaded.stage == "warm"
    assert loaded.total_runs == 5
    assert loaded.recent_success_rate == pytest.approx(0.8)
    assert loaded.consecutive_successes == 3
    assert loaded.llm_calls_last_10 == 2


def test_record_run(tmp_path: Path) -> None:
    """record_run updates metrics and persists."""
    tracker = MaturityTracker(base_dir=tmp_path)

    state = tracker.record_run("example.com", success=True, llm_calls=3)
    assert state.total_runs == 1
    assert state.consecutive_successes == 1
    assert state.llm_calls_last_10 == 3

    state = tracker.record_run("example.com", success=True, llm_calls=1)
    assert state.total_runs == 2
    assert state.consecutive_successes == 2

    state = tracker.record_run("example.com", success=False, llm_calls=5)
    assert state.total_runs == 3
    assert state.consecutive_successes == 0
    assert state.llm_calls_last_10 == 5

    # Verify persisted
    loaded = tracker.load("example.com")
    assert loaded.total_runs == 3
    assert loaded.consecutive_successes == 0
