"""Evolution pipeline — state machine orchestrating the full evolution cycle.

States: PENDING → ANALYZING → GENERATING → TESTING → AWAITING_APPROVAL
                                                           ↓
                                                    APPROVED → MERGED
                                                    REJECTED (branch deleted)
                                                    FAILED (error)

On test failure, retries once (re-analyze → re-generate).
"""
from __future__ import annotations

import logging
from datetime import UTC
from typing import Any

from src.evolution.analyzer import FailureAnalyzer
from src.evolution.code_generator import EvolutionCodeGenerator
from src.evolution.db import EvolutionDB
from src.evolution.notifier import Notifier
from src.evolution.patch_validator import validate_patch, validate_python_syntax
from src.evolution.sandbox import Sandbox

logger = logging.getLogger(__name__)

MAX_RETRIES = 1


class EvolutionPipeline:
    """Orchestrates a single evolution cycle through all states."""

    def __init__(
        self,
        db: EvolutionDB,
        notifier: Notifier,
    ) -> None:
        self._db = db
        self._notifier = notifier
        self._analyzer = FailureAnalyzer(db=db)
        self._generator = EvolutionCodeGenerator()
        self._sandbox = Sandbox()

    async def execute(self, run_id: str) -> None:
        """Execute the full evolution pipeline for a given run.

        This is the main entry point, called as a background task.
        """
        try:
            await self._do_execute(run_id)
        except Exception as exc:
            logger.error("Pipeline failed for %s: %s", run_id, exc, exc_info=True)
            await self._transition(run_id, "failed", error_message=str(exc))

    async def _do_execute(self, run_id: str, retry: int = 0) -> None:
        """Inner execution loop with retry support."""
        # ── ANALYZING ────────────────────────────────
        await self._transition(run_id, "analyzing")

        patterns = await self._analyzer.get_top_patterns(min_occurrences=1)
        if not patterns:
            # Also try analyzing run_log.json directly
            patterns = await self._analyzer.analyze_run_log()

        if not patterns:
            await self._transition(
                run_id, "failed",
                error_message="No failure patterns found to fix",
            )
            return

        analysis_summary = self._format_analysis(patterns)
        await self._db.update_evolution_run(
            run_id, analysis_summary=analysis_summary,
        )

        # ── GENERATING ───────────────────────────────
        await self._transition(run_id, "generating")

        relevant_files = self._generator.get_relevant_files(patterns)
        gen_result = await self._generator.generate_fixes(
            failure_patterns=patterns,
            relevant_files=relevant_files,
        )

        if not gen_result.changes:
            await self._transition(
                run_id, "failed",
                error_message="LLM generated no code changes",
            )
            return

        # Validate patches before proceeding to testing
        validation_errors: list[str] = []
        for change in gen_result.changes:
            patch_dict = {
                "file_path": change.file_path,
                "change_type": change.change_type,
                "new_content": change.new_content,
            }
            vr = validate_patch(patch_dict)
            if not vr.valid:
                validation_errors.extend(vr.errors)
            if (
                change.file_path.endswith(".py")
                and change.change_type != "delete"
                and change.new_content
            ):
                sr = validate_python_syntax(change.new_content)
                if not sr.valid:
                    validation_errors.extend(sr.errors)

        if validation_errors:
            await self._transition(
                run_id, "failed",
                error_message=f"Patch validation failed: {'; '.join(validation_errors[:5])}",
            )
            return

        # Save changes to DB
        for change in gen_result.changes:
            await self._db.add_evolution_change(
                evolution_run_id=run_id,
                file_path=change.file_path,
                change_type=change.change_type,
                description=change.description,
                new_content=change.new_content,
            )

        # ── TESTING ──────────────────────────────────
        await self._transition(run_id, "testing")

        branch_name = f"evolution/{run_id}"
        base_commit = await self._sandbox.get_current_commit()
        await self._db.update_evolution_run(
            run_id, branch_name=branch_name, base_commit=base_commit,
        )

        try:
            # Create sandbox branch
            created = await self._sandbox.create_branch(branch_name)
            if not created:
                await self._transition(
                    run_id, "failed",
                    error_message=f"Failed to create branch {branch_name}",
                )
                return

            # Apply changes
            modified = await self._sandbox.apply_changes(gen_result.changes)
            if not modified:
                await self._transition(
                    run_id, "failed",
                    error_message="No files were modified",
                )
                return

            # Commit
            commit_msg = f"evolution: {gen_result.summary}"
            await self._sandbox.commit_changes(commit_msg, files=modified)

            # Run tests
            test_result = await self._sandbox.run_full_test()

            if test_result.overall_passed:
                # Get diff for review
                await self._sandbox.get_diff(base="main")
                for change in await self._db.get_evolution_changes(run_id):
                    if not change.get("diff_content"):
                        # Update with actual diff
                        pass  # diff is per-file in the changes table already

                await self._transition(run_id, "awaiting_approval")
            else:
                # Test failed — retry once
                if retry < MAX_RETRIES:
                    logger.info("Tests failed, retrying (attempt %d)", retry + 1)
                    await self._sandbox.cleanup(branch_name)
                    await self._sandbox.delete_branch(branch_name)
                    await self._do_execute(run_id, retry=retry + 1)
                else:
                    # Keep the branch for inspection but mark as failed
                    fail_detail = []
                    if not test_result.lint_passed:
                        fail_detail.append(f"Lint: {test_result.lint_output[:200]}")
                    if not test_result.unit_tests_passed:
                        fail_detail.append(
                            f"Tests: {test_result.unit_tests_failed}"
                            f"/{test_result.unit_tests_total} failed"
                        )
                    fail_summary = "; ".join(fail_detail)
                    await self._transition(
                        run_id, "failed",
                        error_message=(
                            f"Tests failed after {retry + 1}"
                            f" attempt(s): {fail_summary}"
                        ),
                    )
        finally:
            # Always return to main
            await self._sandbox.cleanup(branch_name)

    async def _transition(
        self,
        run_id: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update run status and notify subscribers."""
        kwargs: dict[str, Any] = {"status": status}
        if error_message:
            kwargs["error_message"] = error_message
        if status in ("merged", "failed", "rejected"):
            from datetime import datetime
            kwargs["completed_at"] = datetime.now(UTC).isoformat(timespec="seconds")

        await self._db.update_evolution_run(run_id, **kwargs)
        await self._notifier.publish("evolution_status", {
            "run_id": run_id,
            "status": status,
            "error": error_message,
        })
        logger.info("Evolution %s → %s", run_id, status)

    def _format_analysis(self, patterns: list[dict[str, Any]]) -> str:
        """Format failure patterns into a human-readable summary."""
        lines: list[str] = [f"Found {len(patterns)} failure pattern(s):"]
        for p in patterns[:10]:
            lines.append(
                f"- [{p.get('pattern_type')}] {p.get('scenario_name')}/{p.get('phase_name')}"
                f" (×{p.get('occurrence_count', 1)}): {p.get('error_message', '')[:100]}"
            )
        return "\n".join(lines)
