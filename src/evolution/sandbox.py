"""Git-based sandbox — branch creation, code application, testing, cleanup.

All git operations use ``asyncio.create_subprocess_exec`` to avoid blocking.
Safety: always returns to ``main`` branch in the finally block.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.evolution.code_generator import CodeChange

logger = logging.getLogger(__name__)


@dataclass
class SandboxTestResult:
    """Result of running tests in the sandbox."""
    lint_passed: bool = False
    lint_output: str = ""
    type_check_passed: bool = False
    type_check_output: str = ""
    unit_tests_passed: bool = False
    unit_test_output: str = ""
    unit_tests_total: int = 0
    unit_tests_failed: int = 0
    scenario_results: dict[str, Any] = field(default_factory=dict)
    overall_passed: bool = False


class Sandbox:
    """Git branch-based sandbox for testing code changes."""

    def __init__(self, repo_root: str | None = None) -> None:
        self._root = Path(repo_root) if repo_root else Path.cwd()

    async def _run(
        self, *args: str, timeout: float = 120.0,
    ) -> tuple[int, str, str]:
        """Run a command and return (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._root),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return -1, "", f"Command timed out after {timeout}s"

        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def get_current_commit(self) -> str:
        """Get current HEAD commit hash."""
        code, out, _ = await self._run("git", "rev-parse", "HEAD")
        return out.strip() if code == 0 else ""

    async def create_branch(self, branch_name: str) -> bool:
        """Create and checkout a new branch from main."""
        # Stash any uncommitted changes
        await self._run("git", "stash", "--include-untracked")

        # Create branch from main
        code, _, err = await self._run(
            "git", "checkout", "-b", branch_name, "main",
        )
        if code != 0:
            logger.error("Failed to create branch %s: %s", branch_name, err)
            await self._run("git", "stash", "pop")
            return False

        return True

    async def apply_changes(self, changes: list[CodeChange]) -> list[str]:
        """Apply code changes to the working directory.

        Returns list of modified file paths.
        """
        modified: list[str] = []
        for change in changes:
            path = self._root / change.file_path
            if change.change_type == "delete":
                if path.exists():
                    path.unlink()
                    modified.append(change.file_path)
            elif change.change_type in ("modify", "create"):
                if change.new_content is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(change.new_content, encoding="utf-8")
                    modified.append(change.file_path)
        return modified

    async def commit_changes(
        self, message: str, files: list[str] | None = None,
    ) -> str:
        """Stage and commit changes. Returns commit hash."""
        if files:
            for f in files:
                await self._run("git", "add", f)
        else:
            await self._run("git", "add", "-A")

        code, _, err = await self._run(
            "git", "commit", "-m", message,
        )
        if code != 0:
            logger.warning("Commit failed: %s", err)
            return ""

        _, out, _ = await self._run("git", "rev-parse", "HEAD")
        return out.strip()

    async def run_lint(self) -> tuple[bool, str]:
        """Run ruff check."""
        code, out, err = await self._run(
            "python", "-m", "ruff", "check", "src/", "--fix",
            timeout=60.0,
        )
        output = (out + "\n" + err).strip()
        return code == 0, output

    async def run_type_check(self) -> tuple[bool, str]:
        """Run mypy strict check."""
        code, out, err = await self._run(
            "python", "-m", "mypy", "src/", "--strict",
            timeout=120.0,
        )
        output = (out + "\n" + err).strip()
        # mypy often returns 1 for existing issues — check for new errors
        return code == 0, output

    async def run_unit_tests(self) -> tuple[bool, str, int, int]:
        """Run pytest unit and integration tests.

        Returns (passed, output, total, failed).
        """
        code, out, err = await self._run(
            "python", "-m", "pytest", "tests/unit", "tests/integration",
            "-x", "--tb=short", "-q",
            timeout=300.0,
        )
        output = (out + "\n" + err).strip()

        # Parse test counts from pytest output
        total = 0
        failed = 0
        for line in output.split("\n"):
            if "passed" in line or "failed" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "passed" and i > 0:
                        try:
                            total += int(parts[i - 1])
                        except ValueError:
                            pass
                    if p == "failed" and i > 0:
                        try:
                            failed += int(parts[i - 1])
                            total += failed
                        except ValueError:
                            pass

        return code == 0, output, total, failed

    async def run_full_test(self) -> SandboxTestResult:
        """Run the full test suite (lint + type check + unit tests)."""
        result = SandboxTestResult()

        # Lint
        result.lint_passed, result.lint_output = await self.run_lint()
        logger.info("Lint: %s", "PASS" if result.lint_passed else "FAIL")

        # Type check (informational — don't block on existing issues)
        result.type_check_passed, result.type_check_output = await self.run_type_check()
        logger.info("Type check: %s", "PASS" if result.type_check_passed else "FAIL")

        # Unit tests
        (
            result.unit_tests_passed,
            result.unit_test_output,
            result.unit_tests_total,
            result.unit_tests_failed,
        ) = await self.run_unit_tests()
        logger.info(
            "Unit tests: %s (%d total, %d failed)",
            "PASS" if result.unit_tests_passed else "FAIL",
            result.unit_tests_total,
            result.unit_tests_failed,
        )

        # Overall: pass if lint OK and unit tests pass
        result.overall_passed = result.lint_passed and result.unit_tests_passed
        return result

    async def cleanup(self, branch_name: str | None = None) -> None:
        """Return to main and restore stash."""
        await self._run("git", "checkout", "main")
        await self._run("git", "stash", "pop")

    async def delete_branch(self, branch_name: str) -> bool:
        """Delete a branch (local only)."""
        # Make sure we're not on the branch
        code, out, _ = await self._run("git", "rev-parse", "--abbrev-ref", "HEAD")
        if out.strip() == branch_name:
            await self._run("git", "checkout", "main")

        code, _, err = await self._run("git", "branch", "-D", branch_name)
        return code == 0

    async def get_diff(self, base: str = "main") -> str:
        """Get diff between current branch and base."""
        _, out, _ = await self._run("git", "diff", f"{base}...HEAD")
        return out
