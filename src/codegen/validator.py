"""CodeValidator — 5-stage validation gate for generated bundles.

Stages:
1. DSL schema validation (required keys: steps, strategy, domain)
2. Macro lint check (placeholder — returns True)
3. Selector existence check (placeholder — returns True)
4. HAR replay verification (placeholder — returns True)
5. Canary site verification (placeholder — returns True)

Stages 2-5 return placeholder True; real implementations require a
live browser context and will be wired in the Runtime phase.
"""

from __future__ import annotations

import logging
from typing import Any

from src.models.bundle import GeneratedBundle, ValidationResult
from src.models.site_profile import SiteProfile

logger = logging.getLogger(__name__)

_REQUIRED_DSL_KEYS = {"steps", "strategy", "domain"}


class CodeValidator:
    """Validate generated bundles through a 5-stage gate."""

    async def validate(
        self,
        bundle: GeneratedBundle,
        profile: SiteProfile,
    ) -> ValidationResult:
        """Run all validation stages and return combined result.

        Args:
            bundle: Generated execution bundle to validate.
            profile: Site profile for context-aware validation.

        Returns:
            ValidationResult with per-stage pass/fail and error list.
        """
        errors: list[str] = []

        # Stage 1: DSL schema validation
        dsl_ok = self._validate_dsl_schema(bundle.workflow_dsl, errors)

        # Stage 2: Macro lint (placeholder)
        macro_ok = self._lint_check(bundle, errors)

        # Stage 3: Selector existence (placeholder — needs browser)
        selector_ok = self._selector_check(bundle, profile, errors)

        # Stage 4: HAR replay (placeholder — needs HAR + browser)
        har_replay_ok = self._har_replay_check(bundle, profile, errors)

        # Stage 5: Canary run (placeholder — needs live browser)
        canary_ok = self._canary_check(bundle, profile, errors)

        result = ValidationResult(
            dsl_ok=dsl_ok,
            macro_ok=macro_ok,
            selector_ok=selector_ok,
            har_replay_ok=har_replay_ok,
            canary_ok=canary_ok,
            trace_ok=True,
            trace_path=None,
            errors=errors,
        )

        logger.info(
            "Validation for %s: overall=%s (dsl=%s, macro=%s, "
            "selector=%s, har=%s, canary=%s)",
            profile.domain, result.overall, dsl_ok, macro_ok,
            selector_ok, har_replay_ok, canary_ok,
        )
        return result

    # ── Stage 1: DSL schema ──

    @staticmethod
    def _validate_dsl_schema(
        dsl: dict[str, Any],
        errors: list[str],
    ) -> bool:
        """Check that required top-level keys exist in the DSL."""
        if not isinstance(dsl, dict):
            errors.append("workflow_dsl is not a dict")
            return False

        missing = _REQUIRED_DSL_KEYS - set(dsl.keys())
        if missing:
            errors.append(f"DSL missing required keys: {sorted(missing)}")
            return False

        steps = dsl.get("steps")
        if not isinstance(steps, list):
            errors.append("DSL 'steps' must be a list")
            return False

        if len(steps) == 0:
            errors.append("DSL 'steps' is empty")
            return False

        return True

    # ── Stage 2: Macro lint (placeholder) ──

    @staticmethod
    def _lint_check(
        bundle: GeneratedBundle,
        errors: list[str],
    ) -> bool:
        """Placeholder lint check for macro code.

        Real implementation would run ruff/mypy on bundle.python_macro.
        """
        if bundle.python_macro is not None:
            # Basic syntax check via compile
            try:
                compile(bundle.python_macro, "<macro>", "exec")
            except SyntaxError as e:
                errors.append(f"Python macro syntax error: {e}")
                return False
        return True

    # ── Stage 3: Selector check (placeholder) ──

    @staticmethod
    def _selector_check(
        bundle: GeneratedBundle,
        profile: SiteProfile,
        errors: list[str],
    ) -> bool:
        """Placeholder selector existence check.

        Real implementation would use a live browser to verify
        document.querySelector(sel) for each selector in the DSL.
        """
        _ = bundle, profile, errors
        return True

    # ── Stage 4: HAR replay (placeholder) ──

    @staticmethod
    def _har_replay_check(
        bundle: GeneratedBundle,
        profile: SiteProfile,
        errors: list[str],
    ) -> bool:
        """Placeholder HAR replay verification.

        Real implementation would replay recorded HAR network fixtures
        and assert the DSL steps succeed against canned responses.
        """
        _ = bundle, profile, errors
        return True

    # ── Stage 5: Canary (placeholder) ──

    @staticmethod
    def _canary_check(
        bundle: GeneratedBundle,
        profile: SiteProfile,
        errors: list[str],
    ) -> bool:
        """Placeholder canary verification.

        Real implementation would execute the bundle against the live
        site, collect Playwright traces, and assert success.
        """
        _ = bundle, profile, errors
        return True
