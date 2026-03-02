"""Knowledge Base manager — read/write/version site artifacts.

Directory layout::

    knowledge_base/sites/{domain}/
    ├── profile.json
    ├── profile_history/v{n}.json
    ├── url_patterns/{pattern}/
    │   ├── pattern.json
    │   ├── workflows/v{n}.dsl.json + current symlink
    │   ├── macros/v{n}/macro.py + current symlink
    │   └── prompts/v{n}/*.yaml + current symlink
    ├── screenshots/
    └── history/runs.jsonl
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.kb.cache_key import CacheKey
from src.models.site_profile import SiteProfile

logger = logging.getLogger(__name__)

_DEFAULT_BASE = Path("knowledge_base/sites")


@dataclass
class CacheLookupResult:
    """Result of KB lookup."""

    hit: bool = False
    stage: str = "cold"  # "cold" | "warm" | "hot"
    reason: str = ""
    profile: SiteProfile | None = None
    workflow: dict[str, Any] | None = None
    prompts: dict[str, str] | None = None


class KBManager:
    """Knowledge Base read/write/version manager."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = base_dir or _DEFAULT_BASE

    @property
    def base_dir(self) -> Path:
        return self._base

    # ── Profile ──

    def load_profile(self, domain: str) -> SiteProfile | None:
        """Load current SiteProfile for a domain."""
        p = self._base / domain / "profile.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            return SiteProfile.from_dict(data)
        except Exception:
            logger.warning("Failed to load profile for %s", domain)
            return None

    def save_profile(self, profile: SiteProfile) -> int:
        """Save SiteProfile with version history.

        Returns:
            New version number.
        """
        domain_dir = self._base / profile.domain
        domain_dir.mkdir(parents=True, exist_ok=True)

        # Write current
        current = domain_dir / "profile.json"
        data = profile.to_dict()
        current.write_text(json.dumps(data, ensure_ascii=False, indent=2))

        # Write version history
        history_dir = domain_dir / "profile_history"
        history_dir.mkdir(exist_ok=True)
        version = profile.recon_version
        version_file = history_dir / f"v{version}.json"
        version_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))

        logger.info("Saved profile %s v%d", profile.domain, version)
        return version

    def is_profile_expired(
        self, profile: SiteProfile, max_age_hours: int = 168
    ) -> bool:
        """Check if a profile is too old (default: 7 days)."""
        age = datetime.now() - profile.last_recon_at
        return age.total_seconds() > max_age_hours * 3600

    # ── URL Patterns ──

    def _pattern_dir(self, domain: str, url_pattern: str) -> Path:
        key = CacheKey(domain=domain, url_pattern=url_pattern, artifact_type="")
        return self._base / domain / "url_patterns" / key.pattern_dir

    def save_pattern_meta(
        self, domain: str, url_pattern: str, page_type: str
    ) -> None:
        """Save URL pattern metadata."""
        p_dir = self._pattern_dir(domain, url_pattern)
        p_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "url_pattern": url_pattern,
            "page_type": page_type,
            "created_at": datetime.now().isoformat(),
        }
        (p_dir / "pattern.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )

    # ── Workflows ──

    def save_workflow(
        self,
        domain: str,
        url_pattern: str,
        dsl: dict[str, Any],
        version: int | None = None,
    ) -> int:
        """Save a workflow DSL with version.

        Returns:
            Version number.
        """
        p_dir = self._pattern_dir(domain, url_pattern) / "workflows"
        p_dir.mkdir(parents=True, exist_ok=True)

        if version is None:
            version = self._next_version(p_dir, "v", ".dsl.json")

        fname = f"v{version}.dsl.json"
        (p_dir / fname).write_text(
            json.dumps(dsl, ensure_ascii=False, indent=2)
        )

        # Update current symlink
        current = p_dir / "current"
        if current.is_symlink() or current.exists():
            current.unlink()
        current.symlink_to(fname)

        return version

    def load_workflow(
        self, domain: str, url_pattern: str
    ) -> dict[str, Any] | None:
        """Load the current workflow DSL."""
        p_dir = self._pattern_dir(domain, url_pattern) / "workflows"
        current = p_dir / "current"
        if not current.exists():
            return None
        target = p_dir / current.resolve().name
        if not target.exists():
            return None
        try:
            return json.loads(target.read_text())
        except Exception:
            return None

    # ── Prompts ──

    def save_prompts(
        self,
        domain: str,
        url_pattern: str,
        prompts: dict[str, str],
        version: int | None = None,
    ) -> int:
        """Save prompt YAML files with version.

        Returns:
            Version number.
        """
        p_dir = self._pattern_dir(domain, url_pattern) / "prompts"
        p_dir.mkdir(parents=True, exist_ok=True)

        if version is None:
            version = self._next_version(p_dir, "v", "")

        v_dir = p_dir / f"v{version}"
        v_dir.mkdir(exist_ok=True)

        for name, content in prompts.items():
            (v_dir / f"{name}.yaml").write_text(content)

        metadata = {
            "version": version,
            "created_at": datetime.now().isoformat(),
            "prompt_count": len(prompts),
        }
        (v_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2)
        )

        # Update current symlink
        current = p_dir / "current"
        if current.is_symlink() or current.exists():
            if current.is_symlink():
                current.unlink()
            else:
                shutil.rmtree(current)
        current.symlink_to(f"v{version}")

        return version

    def load_prompts(
        self, domain: str, url_pattern: str
    ) -> dict[str, str] | None:
        """Load current prompt set."""
        p_dir = self._pattern_dir(domain, url_pattern) / "prompts" / "current"
        if not p_dir.exists():
            return None
        result: dict[str, str] = {}
        try:
            for f in p_dir.iterdir():
                if f.suffix == ".yaml":
                    result[f.stem] = f.read_text()
        except Exception:
            return None
        return result if result else None

    # ── Macros ──

    def save_macro(
        self,
        domain: str,
        url_pattern: str,
        python_code: str | None = None,
        ts_code: str | None = None,
        version: int | None = None,
    ) -> int:
        """Save macro code with version."""
        p_dir = self._pattern_dir(domain, url_pattern) / "macros"
        p_dir.mkdir(parents=True, exist_ok=True)

        if version is None:
            version = self._next_version(p_dir, "v", "")

        v_dir = p_dir / f"v{version}"
        v_dir.mkdir(exist_ok=True)

        if python_code:
            (v_dir / "macro.py").write_text(python_code)
        if ts_code:
            (v_dir / "macro.ts").write_text(ts_code)

        metadata = {
            "version": version,
            "created_at": datetime.now().isoformat(),
            "has_python": python_code is not None,
            "has_ts": ts_code is not None,
        }
        (v_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2)
        )

        # Update current symlink
        current = p_dir / "current"
        if current.is_symlink() or current.exists():
            if current.is_symlink():
                current.unlink()
            else:
                shutil.rmtree(current)
        current.symlink_to(f"v{version}")

        return version

    # ── Screenshots ──

    def save_screenshot(
        self, domain: str, name: str, data: bytes
    ) -> Path:
        """Save a screenshot to the domain's screenshots directory."""
        ss_dir = self._base / domain / "screenshots"
        ss_dir.mkdir(parents=True, exist_ok=True)
        path = ss_dir / name
        path.write_bytes(data)
        return path

    # ── Run History ──

    def append_run(self, domain: str, record: dict[str, Any]) -> None:
        """Append to runs.jsonl."""
        history_dir = self._base / domain / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        runs_file = history_dir / "runs.jsonl"
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with runs_file.open("a") as f:
            f.write(line)

    # ── Lookup ──

    def lookup(self, domain: str, url: str) -> CacheLookupResult:
        """Determine cache state for a domain + URL.

        Returns:
            CacheLookupResult with hit/stage/artifacts.
        """
        profile = self.load_profile(domain)
        if not profile:
            return CacheLookupResult(hit=False, stage="cold", reason="no_profile")

        pattern = self._match_url_pattern(domain, url)
        if not pattern:
            return CacheLookupResult(
                hit=False, stage="cold", reason="no_pattern", profile=profile
            )

        workflow = self.load_workflow(domain, pattern)
        prompts = self.load_prompts(domain, pattern)

        if not workflow:
            return CacheLookupResult(
                hit=False,
                stage="cold",
                reason="no_workflow",
                profile=profile,
            )
        if not prompts:
            return CacheLookupResult(
                hit=True,
                stage="warm",
                reason="workflow_only",
                profile=profile,
                workflow=workflow,
            )
        return CacheLookupResult(
            hit=True,
            stage="hot",
            reason="full_cache",
            profile=profile,
            workflow=workflow,
            prompts=prompts,
        )

    def _match_url_pattern(self, domain: str, url: str) -> str | None:
        """Match a URL to registered patterns."""
        patterns_dir = self._base / domain / "url_patterns"
        if not patterns_dir.exists():
            return None
        for p_dir in patterns_dir.iterdir():
            if not p_dir.is_dir():
                continue
            meta_file = p_dir / "pattern.json"
            if not meta_file.exists():
                continue
            try:
                meta = json.loads(meta_file.read_text())
                if self._url_matches(url, meta.get("url_pattern", "")):
                    return meta["url_pattern"]
            except Exception:
                continue
        return None

    @staticmethod
    def _url_matches(url: str, pattern: str) -> bool:
        """Simple URL pattern matching.

        Supports * wildcard at the end of path segments or query values.
        """
        if not pattern:
            return False
        # Normalize
        url_path = url.split("?")[0].rstrip("/")
        pat_path = pattern.split("?")[0].rstrip("/")

        if pat_path.endswith("*"):
            return url_path.startswith(pat_path[:-1])
        return url_path == pat_path

    # ── Helpers ──

    @staticmethod
    def _next_version(directory: Path, prefix: str, suffix: str) -> int:
        """Find the next version number in a directory."""
        if not directory.exists():
            return 1
        max_v = 0
        for item in directory.iterdir():
            name = item.name
            if name.startswith(prefix) and (not suffix or name.endswith(suffix)):
                try:
                    v_str = name[len(prefix) :]
                    if suffix:
                        v_str = v_str[: -len(suffix)]
                    v = int(v_str)
                    max_v = max(max_v, v)
                except ValueError:
                    continue
        return max_v + 1


