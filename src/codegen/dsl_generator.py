"""DSLGenerator — SiteProfile + strategy → workflow DSL via LLM.

Takes the SiteProfile and strategy assignments, builds a rich context,
and uses the LLM (fast alias) to produce a JSON workflow DSL.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.llm.router import LLMRouter
from src.models.bundle import StrategyAssignment
from src.models.site_profile import SiteProfile

logger = logging.getLogger(__name__)


class DSLGenerator:
    """Generate workflow DSL from SiteProfile and strategy assignments."""

    async def generate(
        self,
        profile: SiteProfile,
        assignments: list[StrategyAssignment],
        task_type: str,
        llm: LLMRouter,
    ) -> dict[str, Any]:
        """Produce a workflow_dsl dict via LLM structured output.

        Args:
            profile: Site reconnaissance profile.
            assignments: Strategy assignments per page type.
            task_type: Task category (e.g. "search", "purchase").
            llm: LLM router for generation calls.

        Returns:
            Workflow DSL as a JSON-compatible dict.
        """
        context = self._build_context(profile, assignments)
        system = self._system_prompt(profile)

        user_msg = (
            "Generate a workflow DSL for the following site and strategies.\n\n"
            f"## SiteProfile Summary\n{context['profile_summary']}\n\n"
            f"## Strategy Assignments\n{context['strategy_summary']}\n\n"
            f"## Task Type: {task_type}\n\n"
            "## Rules\n"
            "1. Use Playwright async API actions (goto, click, fill, evaluate)\n"
            "2. Include obstacle dismissal steps from SiteProfile\n"
            "3. Each step must have: action, selector (primary + fallbacks), "
            "verify condition\n"
            "4. Output a single JSON object with keys: domain, strategy, "
            "task_type, steps (array)\n"
            "5. Each step: {action, selector, fallback_selectors, value?, "
            "verify, timeout_ms}\n"
            "6. Return ONLY valid JSON — no markdown fences"
        )

        raw = await llm.complete(
            "fast",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=4000,
            temperature=0.1,
        )

        try:
            dsl = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON; wrapping as raw DSL")
            dsl = {
                "domain": profile.domain,
                "strategy": assignments[0].strategy if assignments else "dom_only",
                "task_type": task_type,
                "steps": [],
                "_raw": raw,
            }

        # Ensure required top-level keys
        dsl.setdefault("domain", profile.domain)
        dsl.setdefault("strategy", assignments[0].strategy if assignments else "dom_only")
        dsl.setdefault("task_type", task_type)
        dsl.setdefault("steps", [])

        logger.info(
            "DSL generated for %s: %d steps", profile.domain, len(dsl["steps"]),
        )
        return dsl

    # ── helpers ──

    @staticmethod
    def _build_context(
        profile: SiteProfile,
        assignments: list[StrategyAssignment],
    ) -> dict[str, str]:
        """Build LLM context strings from profile and assignments."""
        nav = profile.navigation
        obstacles = [
            f"- {o.type} ({o.trigger}): dismiss via {o.dismiss_method}"
            for o in profile.obstacles
        ]
        content_info = [
            f"- {c.page_type}: url={c.url_pattern}, "
            f"dom_readable={c.dom_readable}, dynamic={c.dynamic_content}"
            for c in profile.content_types
        ]
        strategy_info = [
            f"- {a.page_type} ({a.url_pattern}): strategy={a.strategy}, "
            f"tools={a.tools_needed}"
            for a in assignments
        ]

        profile_summary = (
            f"Domain: {profile.domain}\n"
            f"Purpose: {profile.purpose}\n"
            f"Framework: {profile.framework or 'vanilla'}\n"
            f"SPA: {profile.is_spa}\n"
            f"DOM elements: {profile.dom_complexity.total_elements}, "
            f"depth: {profile.dom_complexity.max_depth}\n"
            f"Text node ratio: {profile.dom_complexity.text_node_ratio:.2f}\n"
            f"Aria coverage: {profile.dom_complexity.aria_coverage:.2f}\n"
            f"Image density: {profile.image_density}\n"
            f"Canvas: {profile.canvas_usage.has_canvas}\n"
            f"Navigation: menu_depth={nav.menu_depth}, "
            f"hover={nav.menu_requires_hover}, search={nav.has_search}\n"
            f"Obstacles:\n" + ("\n".join(obstacles) or "  (none)") + "\n"
            "Content patterns:\n" + ("\n".join(content_info) or "  (none)")
        )

        strategy_summary = "\n".join(strategy_info) or "(no assignments)"

        return {
            "profile_summary": profile_summary,
            "strategy_summary": strategy_summary,
        }

    @staticmethod
    def _system_prompt(profile: SiteProfile) -> str:
        """Build system prompt describing the generator role."""
        return (
            "You are a web automation workflow DSL generator.\n\n"
            f"Target site: {profile.domain}\n"
            f"Site type: {profile.purpose}\n"
            f"Framework: {profile.framework or 'vanilla'}\n"
            f"SPA: {profile.is_spa}\n"
            f"DOM complexity: {profile.dom_complexity.total_elements} elements, "
            f"depth {profile.dom_complexity.max_depth}\n"
            f"Image density: {profile.image_density}\n"
            f"Canvas: {'present (VLM required)' if profile.canvas_usage.has_canvas else 'none'}\n\n"
            "Rules:\n"
            "- Use Playwright async API actions\n"
            "- Include obstacle dismiss strategies from the profile\n"
            "- Provide fallback selectors for every action step\n"
            "- Add low-cost verification after each action (URL/DOM change)\n"
            "- Output pure JSON only (no markdown, no comments)\n"
            "- If DSL can express the logic, do not use macro code"
        )
