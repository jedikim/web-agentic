"""Version manager — handles approval, merge, tagging, and rollback.

Manages the version lifecycle:
1. Approve: merge evolution branch → tag → create version record
2. Rollback: checkout previous tag → create new version record
"""
from __future__ import annotations

import logging
from typing import Any

from src.evolution.db import EvolutionDB
from src.evolution.notifier import Notifier
from src.evolution.sandbox import Sandbox

logger = logging.getLogger(__name__)


def _bump_patch(version: str) -> str:
    """Bump the patch version: 0.1.0 → 0.1.1."""
    parts = version.split(".")
    if len(parts) != 3:
        parts = ["0", "1", "0"]
    parts[2] = str(int(parts[2]) + 1)
    return ".".join(parts)


class VersionManager:
    """Handles version creation, merge, and rollback."""

    def __init__(
        self,
        db: EvolutionDB,
        notifier: Notifier,
    ) -> None:
        self._db = db
        self._notifier = notifier
        self._sandbox = Sandbox()

    async def approve_and_merge(self, run_id: str) -> str:
        """Approve an evolution run: merge branch, tag, create version record.

        Args:
            run_id: Evolution run ID.

        Returns:
            New version string.

        Raises:
            RuntimeError: If merge fails.
        """
        run = await self._db.get_evolution_run(run_id)
        if not run:
            raise RuntimeError(f"Evolution run {run_id} not found")

        branch_name = run.get("branch_name")
        if not branch_name:
            raise RuntimeError(f"No branch for evolution run {run_id}")

        # Determine new version
        current_version = await self._db.get_latest_version()
        new_version = _bump_patch(current_version)

        # Merge
        code, out, err = await self._sandbox._run(
            "git", "merge", "--no-ff", branch_name, "-m",
            f"evolution: merge {branch_name} as v{new_version}",
        )
        if code != 0:
            raise RuntimeError(f"Merge failed: {err}")

        # Tag
        code, _, err = await self._sandbox._run(
            "git", "tag", f"v{new_version}",
        )
        if code != 0:
            logger.warning("Tag creation failed: %s", err)

        # Get commit hash
        _, commit_hash, _ = await self._sandbox._run("git", "rev-parse", "HEAD")
        commit_hash = commit_hash.strip()

        # Build changelog from evolution changes
        changes = await self._db.get_evolution_changes(run_id)
        changelog = self._build_changelog(run, changes)

        # Create version record
        await self._db.create_version_record(
            version=new_version,
            previous_version=current_version,
            evolution_run_id=run_id,
            changelog=changelog,
            test_results={},
            git_tag=f"v{new_version}",
            git_commit=commit_hash,
        )

        # Update evolution run status
        await self._db.update_evolution_run(run_id, status="merged")

        # Resolve relevant failure patterns
        analysis = run.get("analysis_summary", "")
        if analysis:
            patterns = await self._db.list_failure_patterns(unresolved_only=True)
            pattern_keys = [p["pattern_key"] for p in patterns]
            if pattern_keys:
                resolved = await self._db.resolve_failure_patterns(pattern_keys, new_version)
                logger.info("Resolved %d failure pattern(s) in version %s", resolved, new_version)

        # Delete the evolution branch (merged)
        await self._sandbox.delete_branch(branch_name)

        # Notify
        await self._notifier.publish("version_created", {
            "version": new_version,
            "previous_version": current_version,
            "evolution_run_id": run_id,
            "changelog": changelog,
        })
        await self._notifier.publish("evolution_status", {
            "run_id": run_id,
            "status": "merged",
            "version": new_version,
        })

        logger.info("Merged evolution %s as version %s", run_id, new_version)
        return new_version

    async def rollback(self, target_version: str) -> str:
        """Rollback to a previous version.

        Creates a new version record for the rollback.

        Args:
            target_version: Version string to rollback to.

        Returns:
            New version string (rollback version).
        """
        target = await self._db.get_version_record(target_version)
        if not target:
            raise RuntimeError(f"Version {target_version} not found")

        git_tag = target.get("git_tag")
        if not git_tag:
            raise RuntimeError(f"No git tag for version {target_version}")

        # Checkout the tag
        code, _, err = await self._sandbox._run("git", "checkout", git_tag)
        if code != 0:
            raise RuntimeError(f"Checkout failed: {err}")

        # Create new version
        current_version = await self._db.get_latest_version()
        new_version = _bump_patch(current_version)

        _, commit_hash, _ = await self._sandbox._run("git", "rev-parse", "HEAD")

        await self._db.create_version_record(
            version=new_version,
            previous_version=current_version,
            changelog=f"Rollback to version {target_version}",
            git_tag=f"v{new_version}",
            git_commit=commit_hash.strip(),
        )

        # Tag the rollback
        await self._sandbox._run("git", "tag", f"v{new_version}")

        # Return to main
        await self._sandbox._run("git", "checkout", "main")

        await self._notifier.publish("version_created", {
            "version": new_version,
            "rollback_from": current_version,
            "rollback_to": target_version,
        })

        logger.info("Rolled back to %s as version %s", target_version, new_version)
        return new_version

    def _build_changelog(
        self,
        run: dict[str, Any],
        changes: list[dict[str, Any]],
    ) -> str:
        """Build a changelog string from evolution run and changes."""
        lines: list[str] = []
        summary = run.get("analysis_summary", "")
        if summary:
            lines.append(f"## Analysis\n{summary}\n")

        if changes:
            lines.append("## Changes")
            for c in changes:
                lines.append(f"- **{c['file_path']}** ({c['change_type']}): {c['description']}")

        return "\n".join(lines) if lines else "No changelog available"
