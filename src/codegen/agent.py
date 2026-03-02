"""CodeGenAgent — orchestrates the full code generation pipeline.

Pipeline: StrategyDecider → DSLGenerator → PromptGenerator → Validator → KB save.
"""

from __future__ import annotations

import logging
from typing import Any

from src.codegen.dsl_generator import DSLGenerator
from src.codegen.prompt_generator import PromptGenerator
from src.codegen.strategy_decider import StrategyDecider
from src.codegen.validator import CodeValidator
from src.kb.manager import KBManager
from src.llm.router import LLMRouter
from src.models.bundle import GeneratedBundle, ValidationResult
from src.models.site_profile import SiteProfile

logger = logging.getLogger(__name__)

_MAX_REGEN_ATTEMPTS = 2


class CodeGenAgent:
    """Orchestrate code generation for a given site and task type.

    Executes sequentially:
    1. StrategyDecider — pick strategy per page type
    2. DSLGenerator — produce workflow DSL via LLM
    3. PromptGenerator — produce task-specific YAML prompts
    4. CodeValidator — validate the bundle (5-stage gate)
    5. KBManager — persist to Knowledge Base on success
    """

    def __init__(
        self,
        *,
        strategy_decider: StrategyDecider | None = None,
        dsl_generator: DSLGenerator | None = None,
        prompt_generator: PromptGenerator | None = None,
        validator: CodeValidator | None = None,
    ) -> None:
        self._strategy_decider = strategy_decider or StrategyDecider()
        self._dsl_generator = dsl_generator or DSLGenerator()
        self._prompt_generator = prompt_generator or PromptGenerator()
        self._validator = validator or CodeValidator()

    async def generate_bundle(
        self,
        domain: str,
        profile: SiteProfile,
        task_type: str,
        kb: KBManager,
        llm: LLMRouter,
        *,
        intent: str = "",
        runtime_stats: dict[str, dict[str, Any]] | None = None,
    ) -> GeneratedBundle:
        """Run the full code-gen pipeline and return a validated bundle.

        Args:
            domain: Target site domain.
            profile: SiteProfile from Phase 1 (Recon).
            task_type: Task category (e.g. "search", "purchase").
            kb: Knowledge Base manager for persistence.
            llm: LLM router for generation calls.
            runtime_stats: Optional per-strategy runtime metrics.

        Returns:
            A validated GeneratedBundle. If validation fails after
            retries, returns the last generated bundle with errors.
        """
        logger.info("CodeGen pipeline start: %s (task=%s)", domain, task_type)

        # Step 1: Strategy decision
        assignments = self._strategy_decider.decide(
            profile, task_type, runtime_stats,
        )
        primary_strategy = assignments[0].strategy if assignments else "dom_only"
        logger.info("Strategy decided: %s", primary_strategy)

        # Steps 2-4: Generate + validate (with retry on failure)
        bundle: GeneratedBundle | None = None
        validation: ValidationResult | None = None

        for attempt in range(1, _MAX_REGEN_ATTEMPTS + 1):
            # Step 2: DSL generation
            workflow_dsl = await self._dsl_generator.generate(
                profile, assignments, task_type, llm, intent=intent,
            )

            # Step 3: Prompt generation
            prompts = self._prompt_generator.generate(
                profile, task_type, primary_strategy, intent=intent,
            )

            # Assemble bundle
            bundle = GeneratedBundle(
                workflow_dsl=workflow_dsl,
                prompts=prompts,
                strategy=primary_strategy,
                dependencies=self._collect_dependencies(assignments),
                version=attempt,
            )

            # Step 4: Validation
            validation = await self._validator.validate(bundle, profile)

            if validation.overall:
                logger.info(
                    "Validation passed on attempt %d for %s",
                    attempt, domain,
                )
                break

            logger.warning(
                "Validation failed (attempt %d/%d) for %s: %s",
                attempt, _MAX_REGEN_ATTEMPTS, domain, validation.errors,
            )

        assert bundle is not None  # At least one attempt always runs.

        # Step 5: Save to KB (even on validation failure — for debugging)
        url_pattern = self._primary_url_pattern(assignments)
        self._save_to_kb(kb, domain, url_pattern, bundle, task_type)

        logger.info(
            "CodeGen pipeline complete: %s (strategy=%s, valid=%s)",
            domain, primary_strategy,
            validation.overall if validation else "unknown",
        )
        return bundle

    # ── helpers ──

    @staticmethod
    def _collect_dependencies(
        assignments: list[Any],
    ) -> list[str]:
        """Collect unique tool dependencies from all assignments."""
        seen: set[str] = set()
        deps: list[str] = []
        for a in assignments:
            for tool in a.tools_needed:
                if tool not in seen:
                    seen.add(tool)
                    deps.append(tool)
        return deps

    @staticmethod
    def _primary_url_pattern(
        assignments: list[Any],
    ) -> str:
        """Extract the first url_pattern or default to '/'."""
        if assignments and assignments[0].url_pattern:
            return assignments[0].url_pattern
        return "/"

    @staticmethod
    def _save_to_kb(
        kb: KBManager,
        domain: str,
        url_pattern: str,
        bundle: GeneratedBundle,
        task_type: str,
    ) -> None:
        """Persist bundle artifacts to the Knowledge Base."""
        try:
            kb.save_pattern_meta(domain, url_pattern, task_type)
            kb.save_workflow(domain, url_pattern, bundle.workflow_dsl)
            if bundle.prompts:
                kb.save_prompts(domain, url_pattern, bundle.prompts)
            if bundle.python_macro:
                kb.save_macro(
                    domain, url_pattern, python_code=bundle.python_macro,
                )
            logger.info("Bundle saved to KB: %s/%s", domain, url_pattern)
        except Exception:
            logger.exception("Failed to save bundle to KB for %s", domain)
