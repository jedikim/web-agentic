"""StrategyDecider — heuristic + runtime-stats strategy selection.

Scores 5 strategies per page type based on SiteProfile fields
(text_node_ratio, aria_coverage, canvas, image_density, thumbnail grids)
and overrides with runtime performance stats when available.
"""

from __future__ import annotations

import logging
from typing import Any

from src.models.bundle import StrategyAssignment
from src.models.site_profile import ContentPattern, SiteProfile

logger = logging.getLogger(__name__)

STRATEGIES = [
    "dom_only",
    "dom_with_objdet_backup",
    "objdet_dom_hybrid",
    "grid_vlm",
    "vlm_only",
]

# strategy → required tools
_TOOL_MAP: dict[str, list[str]] = {
    "dom_only": ["playwright", "cdp"],
    "dom_with_objdet_backup": ["playwright", "cdp", "obj_detector"],
    "objdet_dom_hybrid": ["playwright", "cdp", "obj_detector"],
    "grid_vlm": ["playwright", "obj_detector", "vlm", "grid_composer"],
    "vlm_only": ["playwright", "vlm", "obj_detector"],
}


class StrategyDecider:
    """SiteProfile + runtime performance metrics based strategy decider."""

    def decide(
        self,
        profile: SiteProfile,
        task_type: str,
        runtime_stats: dict[str, dict[str, Any]] | None = None,
    ) -> list[StrategyAssignment]:
        """Decide strategy for each content page type.

        Args:
            profile: Site reconnaissance profile.
            task_type: Task category (e.g. "search", "purchase", "navigate").
            runtime_stats: Per-strategy runtime metrics. Keys are strategy
                names, values are dicts with ``success_rate``, ``avg_cost``,
                ``p95_latency_ms``.

        Returns:
            List of StrategyAssignment, one per content_type in the profile.
            If no content_types exist, a single default assignment is returned.
        """
        stats = runtime_stats or {}
        assignments: list[StrategyAssignment] = []

        if not profile.content_types:
            strategy = self._score_and_pick(
                ContentPattern(), profile, stats,
            )
            assignments.append(StrategyAssignment(
                page_type="default",
                url_pattern="/",
                strategy=strategy,
                tools_needed=self._required_tools(strategy),
            ))
            return assignments

        for content in profile.content_types:
            strategy = self._score_and_pick(content, profile, stats)
            assignments.append(StrategyAssignment(
                page_type=content.page_type,
                url_pattern=content.url_pattern,
                strategy=strategy,
                tools_needed=self._required_tools(strategy),
            ))

        logger.info(
            "Strategy decisions for %s: %s",
            profile.domain,
            [(a.page_type, a.strategy) for a in assignments],
        )
        return assignments

    # ── internals ──

    def _score_and_pick(
        self,
        content: ContentPattern,
        profile: SiteProfile,
        runtime_stats: dict[str, dict[str, Any]],
    ) -> str:
        """Compute heuristic base scores + runtime bonus, return winner."""
        base = self._base_scores(content, profile)
        final: dict[str, float] = {}
        for strategy in STRATEGIES:
            perf = runtime_stats.get(strategy, {})
            success = float(perf.get("success_rate", 0.5))
            cost = float(perf.get("avg_cost", 0.003))
            latency = float(perf.get("p95_latency_ms", 3000))
            perf_bonus = (success * 1.5) - (cost * 40.0) - (latency / 10000.0)
            final[strategy] = base[strategy] + perf_bonus

        winner = max(final, key=lambda s: final[s])
        return winner

    def _base_scores(
        self,
        content: ContentPattern,
        profile: SiteProfile,
    ) -> dict[str, float]:
        """Heuristic scores from SiteProfile fields."""
        scores: dict[str, float] = {s: 0.0 for s in STRATEGIES}

        # Canvas → VLM required
        if profile.canvas_usage.requires_vision_only:
            scores["vlm_only"] += 2.0

        # DOM-readable with good text/aria → DOM strategies
        if (
            content.dom_readable
            and profile.dom_complexity.text_node_ratio > 0.35
            and profile.dom_complexity.aria_coverage > 0.20
        ):
            scores["dom_only"] += 1.5
            scores["dom_with_objdet_backup"] += 0.5

        # Thumbnail grids matching this page
        for thumb in profile.thumbnail_structures:
            if thumb.page_url_pattern == content.url_pattern:
                if thumb.card_has_text:
                    scores["dom_with_objdet_backup"] += 1.0
                else:
                    scores["grid_vlm"] += 1.2

        # High image density → hybrid / grid
        if profile.image_density == "high":
            scores["objdet_dom_hybrid"] += 0.8
            scores["grid_vlm"] += 0.4

        # Canvas presence (not vision-only) → hybrid / vlm
        if profile.canvas_usage.has_canvas:
            scores["objdet_dom_hybrid"] += 0.6
            scores["vlm_only"] += 0.4

        return scores

    @staticmethod
    def _required_tools(strategy: str) -> list[str]:
        """Map strategy name to required tool list."""
        return list(_TOOL_MAP.get(strategy, ["playwright", "cdp"]))
