"""Failure pattern analyzer — detects recurring failures from scenario results.

Reads scenario results from DB and run_log.json, classifies failure patterns,
and upserts them into the failure_patterns table.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from src.evolution.db import EvolutionDB

logger = logging.getLogger(__name__)

# ── Pattern Types ────────────────────────────────────

PATTERN_TYPES = {
    "selector_not_found": ["SelectorNotFound", "selector", "element not found", "locator"],
    "timeout": ["timeout", "TimeoutError", "timed out", "timed_out"],
    "parse_error": ["parse", "JSON", "json.decoder", "parsing"],
    "budget_exceeded": ["budget", "cost", "BudgetExceeded"],
    "captcha": ["captcha", "CAPTCHA", "CaptchaDetected"],
    "network_error": ["NetworkError", "network", "ERR_"],
    "auth_required": ["AuthRequired", "login", "auth"],
    "not_interactable": ["NotInteractable", "not interactable", "disabled"],
    "state_not_changed": ["StateNotChanged", "state", "unchanged"],
    "bot_detected": [
        "BotDetected", "bot detected", "access denied",
        "403 Forbidden", "429", "blocked",
    ],
    "navigation_blocked": [
        "NavigationBlocked", "robots.txt", "navigation blocked", "disallowed",
    ],
}


def _classify_error(error_text: str) -> str:
    """Classify an error string into a pattern type."""
    lower = error_text.lower()
    for pattern_type, keywords in PATTERN_TYPES.items():
        for kw in keywords:
            if kw.lower() in lower:
                return pattern_type
    return "unknown"


def _make_pattern_key(scenario_name: str, phase_name: str, pattern_type: str) -> str:
    """Generate a deterministic key for a failure pattern."""
    raw = f"{scenario_name}|{phase_name}|{pattern_type}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class FailureAnalyzer:
    """Analyzes scenario results and detects recurring failure patterns."""

    def __init__(self, db: EvolutionDB) -> None:
        self._db = db

    async def analyze_latest_results(self) -> list[dict[str, Any]]:
        """Analyze the most recent scenario results and detect patterns.

        Returns:
            List of detected/updated failure patterns.
        """
        results = await self._db.list_scenario_results(limit=20)
        failed = [r for r in results if not r["overall_success"]]

        if not failed:
            logger.info("No failed scenarios to analyze")
            return []

        patterns: list[dict[str, Any]] = []
        for result in failed:
            new_patterns = await self._analyze_single_result(result)
            patterns.extend(new_patterns)

        logger.info(
            "Detected %d failure pattern(s) from %d failed run(s)",
            len(patterns), len(failed),
        )
        return patterns

    async def _analyze_single_result(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        """Analyze a single scenario result for failure patterns."""
        patterns: list[dict[str, Any]] = []
        scenario_name = result["scenario_name"]

        # Analyze phase details
        phase_details = result.get("phase_details", [])
        if isinstance(phase_details, str):
            phase_details = json.loads(phase_details)

        for phase in phase_details:
            phase_name = phase.get("phase_name", "unknown")
            success = phase.get("success", False)

            if success:
                continue

            error = phase.get("error", "")
            timed_out = phase.get("timed_out", False)

            if timed_out:
                pattern_type = "timeout"
                error_msg = f"Phase timed out: {phase_name}"
            elif error:
                pattern_type = _classify_error(error)
                error_msg = error[:500]
            else:
                pattern_type = "unknown"
                error_msg = f"Phase failed without explicit error: {phase_name}"

            pattern_key = _make_pattern_key(scenario_name, phase_name, pattern_type)
            p = await self._db.upsert_failure_pattern(
                pattern_key=pattern_key,
                pattern_type=pattern_type,
                scenario_name=scenario_name,
                phase_name=phase_name,
                failure_code=pattern_type,
                error_message=error_msg,
            )
            patterns.append(p)

        # Also analyze the error_summary field
        if result.get("error_summary") and not phase_details:
            error = result["error_summary"]
            pattern_type = _classify_error(error)
            pattern_key = _make_pattern_key(scenario_name, "scenario", pattern_type)
            p = await self._db.upsert_failure_pattern(
                pattern_key=pattern_key,
                pattern_type=pattern_type,
                scenario_name=scenario_name,
                phase_name="scenario",
                failure_code=pattern_type,
                error_message=error[:500],
            )
            patterns.append(p)

        return patterns

    async def analyze_run_log(self, log_path: str = "testing/run_log.json") -> list[dict[str, Any]]:
        """Analyze a run_log.json file directly."""
        path = Path(log_path)
        if not path.exists():
            logger.warning("Run log not found: %s", log_path)
            return []

        with path.open("r", encoding="utf-8") as f:
            log_data = json.load(f)

        scenarios = log_data.get("scenarios", [])
        patterns: list[dict[str, Any]] = []

        for scenario in scenarios:
            scenario_name = scenario.get("name", "unknown")
            if scenario.get("overall_success"):
                continue

            for phase in scenario.get("phases", []):
                phase_name = phase.get("name", "unknown")
                if phase.get("success"):
                    continue

                error = phase.get("error", "")
                timed_out = phase.get("timed_out", False)

                if timed_out:
                    pattern_type = "timeout"
                    error_msg = "Phase timed out"
                elif error:
                    pattern_type = _classify_error(error)
                    error_msg = error[:500]
                else:
                    # Check step-level failures
                    failed_steps = [
                        s for s in phase.get("steps", [])
                        if not s.get("success", False)
                    ]
                    if failed_steps:
                        step_errors = [s.get("failure_code", "unknown") for s in failed_steps]
                        pattern_type = _classify_error(" ".join(step_errors))
                        error_msg = f"Steps failed: {step_errors}"
                    else:
                        pattern_type = "unknown"
                        error_msg = "Phase failed"

                pattern_key = _make_pattern_key(scenario_name, phase_name, pattern_type)
                p = await self._db.upsert_failure_pattern(
                    pattern_key=pattern_key,
                    pattern_type=pattern_type,
                    scenario_name=scenario_name,
                    phase_name=phase_name,
                    failure_code=pattern_type,
                    error_message=error_msg,
                )
                patterns.append(p)

        return patterns

    async def analyze_fallback_stats(
        self,
        stats: dict[str, Any],
        scenario_name: str = "session",
    ) -> list[dict[str, Any]]:
        """Convert FallbackRouter stats into failure patterns.

        Args:
            stats: Dict from ``FallbackRouter.get_stats()``
                   mapping failure code names to {total, recovered, failed, recovery_rate}.
            scenario_name: Scenario name for the generated patterns.

        Returns:
            List of created/updated failure pattern dicts.
        """
        patterns: list[dict[str, Any]] = []
        for failure_code_name, counts in stats.items():
            if counts.get("failed", 0) == 0:
                continue  # Only track unrecovered failures

            pattern_type = _classify_error(failure_code_name)
            pattern_key = _make_pattern_key(
                scenario_name, "fallback_router", pattern_type,
            )
            error_msg = (
                f"FallbackRouter: {failure_code_name} "
                f"total={counts['total']}, recovered={counts['recovered']}, "
                f"failed={counts['failed']}, rate={counts.get('recovery_rate', 0):.2f}"
            )
            p = await self._db.upsert_failure_pattern(
                pattern_key=pattern_key,
                pattern_type=pattern_type,
                scenario_name=scenario_name,
                phase_name="fallback_router",
                failure_code=failure_code_name,
                error_message=error_msg,
            )
            patterns.append(p)

        return patterns

    async def get_top_patterns(self, min_occurrences: int = 2) -> list[dict[str, Any]]:
        """Get the most common unresolved failure patterns."""
        return await self._db.list_failure_patterns(
            unresolved_only=True,
            min_occurrences=min_occurrences,
        )
