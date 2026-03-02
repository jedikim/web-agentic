"""PromptGenerator — task-specific YAML prompt generation.

Generates customized YAML prompts for extract, navigate, verify,
and fallback actions based on SiteProfile and chosen strategy.
"""

from __future__ import annotations

import logging

from src.models.site_profile import SiteProfile

logger = logging.getLogger(__name__)


class PromptGenerator:
    """Generate task-specific YAML prompts from SiteProfile."""

    def generate(
        self,
        profile: SiteProfile,
        task_type: str,
        strategy: str,
        *,
        intent: str = "",
    ) -> dict[str, str]:
        """Produce prompt YAML strings keyed by prompt name.

        Args:
            profile: Site reconnaissance profile.
            task_type: Task category (e.g. "search", "purchase").
            strategy: Chosen automation strategy name.
            intent: Natural language task description.

        Returns:
            Dict mapping prompt name to YAML content string.
            Keys: "extract", "navigate", "verify", "fallback".
        """
        prompts: dict[str, str] = {
            "extract": self._extract_prompt(profile, task_type, strategy),
            "navigate": self._navigate_prompt(profile, task_type, intent=intent),
            "verify": self._verify_prompt(profile, task_type),
            "fallback": self._fallback_prompt(profile, strategy),
        }

        logger.info(
            "Generated %d prompts for %s (task=%s, strategy=%s)",
            len(prompts), profile.domain, task_type, strategy,
        )
        return prompts

    # ── prompt builders ──

    def _extract_prompt(
        self, profile: SiteProfile, task_type: str, strategy: str,
    ) -> str:
        """Prompt for extracting data from page DOM/vision."""
        selectors = self._collect_key_selectors(profile)
        obstacles = self._obstacle_section(profile)

        return (
            f"name: extract\n"
            f"domain: {profile.domain}\n"
            f"task_type: {task_type}\n"
            f"strategy: {strategy}\n"
            f"description: >\n"
            f"  Extract target content from {profile.domain}.\n"
            f"  Site purpose: {profile.purpose}.\n"
            f"  DOM text_node_ratio: "
            f"{profile.dom_complexity.text_node_ratio:.2f}.\n"
            f"  Image density: {profile.image_density}.\n"
            f"key_selectors:\n{selectors}"
            f"obstacles:\n{obstacles}"
            f"instructions:\n"
            f"  - Prefer CSS selectors over XPath\n"
            f"  - Use aria attributes when available "
            f"(coverage: {profile.dom_complexity.aria_coverage:.0%})\n"
            f"  - Return structured JSON with extracted fields\n"
        )

    def _navigate_prompt(
        self, profile: SiteProfile, task_type: str, *, intent: str = "",
    ) -> str:
        """Prompt for site navigation actions."""
        nav = profile.navigation
        intent_section = f"task_description: {intent}\n" if intent else ""
        search_info = ""
        if profile.search_functionality:
            sf = profile.search_functionality
            search_info = (
                f"search:\n"
                f"  input_selector: {sf.input_selector}\n"
                f"  submit_method: {sf.submit_method}\n"
                f"  autocomplete: {sf.autocomplete}\n"
            )

        return (
            f"name: navigate\n"
            f"domain: {profile.domain}\n"
            f"task_type: {task_type}\n"
            f"{intent_section}"
            f"description: >\n"
            f"  Navigate within {profile.domain}.\n"
            f"  Menu depth: {nav.menu_depth}.\n"
            f"  Requires hover: {nav.menu_requires_hover}.\n"
            f"  Has breadcrumb: {nav.has_breadcrumb}.\n"
            f"menu_selector: {nav.menu_selector or '(auto-detect)'}\n"
            f"{search_info}"
            f"instructions:\n"
            f"  - Wait for navigation complete after clicks\n"
            f"  - Handle hover menus with explicit hover actions\n"
            f"  - Verify URL change after navigation\n"
        )

    def _verify_prompt(
        self, profile: SiteProfile, task_type: str,
    ) -> str:
        """Prompt for post-action verification."""
        return (
            f"name: verify\n"
            f"domain: {profile.domain}\n"
            f"task_type: {task_type}\n"
            f"description: >\n"
            f"  Verify that an action succeeded on {profile.domain}.\n"
            f"  SPA: {profile.is_spa}.\n"
            f"  Dynamic content: "
            f"{any(c.dynamic_content for c in profile.content_types)}.\n"
            f"instructions:\n"
            f"  - Check URL change for navigation actions\n"
            f"  - Check DOM mutations for in-page actions\n"
            f"  - For SPA sites use MutationObserver or waitForSelector\n"
            f"  - Return {{success: bool, evidence: str}}\n"
        )

    def _fallback_prompt(
        self, profile: SiteProfile, strategy: str,
    ) -> str:
        """Prompt for fallback recovery when primary action fails."""
        vision_note = ""
        if strategy in ("grid_vlm", "vlm_only", "objdet_dom_hybrid"):
            vision_note = (
                "  - Use vision grounding as fallback for selector failure\n"
            )

        return (
            f"name: fallback\n"
            f"domain: {profile.domain}\n"
            f"strategy: {strategy}\n"
            f"description: >\n"
            f"  Recovery actions when primary strategy fails.\n"
            f"  Framework: {profile.framework or 'vanilla'}.\n"
            f"instructions:\n"
            f"  - Try alternative selectors (data-testid, aria-label)\n"
            f"  - Fall back to viewport coordinate click\n"
            f"{vision_note}"
            f"  - Log failure reason for strategy refinement\n"
            f"  - Max 2 retry attempts before escalation\n"
        )

    # ── helpers ──

    @staticmethod
    def _collect_key_selectors(profile: SiteProfile) -> str:
        """Format key selectors from content patterns as YAML."""
        lines: list[str] = []
        for ct in profile.content_types:
            for name, sel in ct.key_selectors.items():
                lines.append(f"  {name}: \"{sel}\"")
        return "\n".join(lines) + "\n" if lines else "  (none)\n"

    @staticmethod
    def _obstacle_section(profile: SiteProfile) -> str:
        """Format obstacle info as YAML."""
        if not profile.obstacles:
            return "  (none)\n"
        lines: list[str] = []
        for obs in profile.obstacles:
            lines.append(
                f"  - type: {obs.type}\n"
                f"    trigger: {obs.trigger}\n"
                f"    dismiss: {obs.dismiss_method}\n"
                f"    selector: {obs.selector or '(auto-detect)'}"
            )
        return "\n".join(lines) + "\n"
