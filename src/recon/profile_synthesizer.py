"""Profile Synthesizer — combine 3-stage recon into SiteProfile.

Takes DOM + Visual + Nav scan results and synthesizes a complete
SiteProfile. Uses LLM for final synthesis when needed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Protocol

from src.models.site_profile import (
    CanvasUsage,
    ContentPattern,
    DOMComplexity,
    FormPattern,
    InteractionPattern,
    NavigationStructure,
    ObstaclePattern,
    RepeatingPattern,
    SearchConfig,
    SiteProfile,
    ThumbnailGrid,
    VisualStructure,
)

logger = logging.getLogger(__name__)


class LLMLike(Protocol):
    """LLM interface for synthesis."""

    async def complete(
        self,
        alias: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str: ...


class ProfileSynthesizer:
    """Synthesize recon results into a SiteProfile."""

    async def synthesize(
        self,
        domain: str,
        dom_result: dict[str, Any],
        visual_result: dict[str, Any],
        nav_result: dict[str, Any],
        llm: LLMLike | None = None,
        existing_version: int = 0,
    ) -> SiteProfile:
        """Build SiteProfile from scan results.

        When LLM is available, it refines the profile.
        Without LLM, uses heuristic assembly.

        Args:
            domain: Site domain.
            dom_result: DOM scanner output.
            visual_result: Visual scanner output.
            nav_result: Navigation scanner output.
            llm: Optional LLM router for synthesis refinement.
            existing_version: Current profile version (0 if new).

        Returns:
            Complete SiteProfile.
        """
        profile = self._heuristic_assembly(
            domain, dom_result, visual_result, nav_result, existing_version
        )

        if llm is not None:
            profile = await self._llm_refine(
                profile, dom_result, visual_result, nav_result, llm
            )

        return profile

    def _heuristic_assembly(
        self,
        domain: str,
        dom: dict[str, Any],
        visual: dict[str, Any],
        nav: dict[str, Any],
        existing_version: int,
    ) -> SiteProfile:
        """Assemble SiteProfile from raw data using heuristics."""
        now = datetime.now()

        # DOM complexity
        dom_complexity = DOMComplexity(
            total_elements=dom.get("total_elements", 0),
            interactive_elements=dom.get("interactive_elements", 0),
            max_depth=dom.get("max_depth", 0),
            unique_selectors_ratio=dom.get("unique_selectors_ratio", 0.0),
            text_node_ratio=dom.get("text_node_ratio", 0.0),
            aria_coverage=dom.get("aria_coverage", 0.0),
        )

        # Visual structure
        menu_type = dom.get("menu_type", "unknown")
        visual_structure = VisualStructure(
            menu_type=menu_type,
        )

        # Canvas
        canvas_count = dom.get("canvas_count", 0)
        canvas_area = dom.get("canvas_area_ratio", 0.0)
        canvas_usage = CanvasUsage(
            has_canvas=canvas_count > 0,
            canvas_count=canvas_count,
            canvas_area_ratio=canvas_area,
            requires_vision_only=canvas_area > 0.5,
        )

        # Repeating patterns (whitelist content recognition)
        repeating = [
            RepeatingPattern(**rp)
            for rp in dom.get("repeating_patterns", [])
        ]

        # Obstacles
        obstacles = [
            ObstaclePattern(
                type=o.get("type", "popup"),
                selector=o.get("selector"),
                dismiss_method="click_close" if o.get("close_selector") else "press_esc",
            )
            for o in dom.get("obstacles", [])
        ]

        # Navigation
        has_search = dom.get("search") is not None
        search_config = None
        if has_search and dom.get("search"):
            s = dom["search"]
            search_config = SearchConfig(
                input_selector=s.get("input_selector", ""),
                autocomplete=s.get("has_autocomplete", False),
            )

        navigation = NavigationStructure(
            menu_items=dom.get("menu_items", []),
            menu_requires_hover=dom.get("menu_requires_hover", False),
            has_search=has_search,
            has_breadcrumb=dom.get("has_breadcrumb", False),
        )

        # Interaction patterns
        interaction_patterns = [
            InteractionPattern(
                type=p.get("type", ""),
                description=f"{p.get('type', '')} x{p.get('count', 0)}",
            )
            for p in dom.get("interaction_patterns", [])
        ]

        # Forms
        form_types = [
            FormPattern(
                form_selector=f.get("selector", ""),
                fields=f.get("fields", []),
                submit_method="click" if f.get("submit") else "enter",
            )
            for f in dom.get("forms", [])
        ]

        # Filter input groups (input+button outside <form>)
        for fg in dom.get("filter_groups", []):
            submit = fg.get("submit", {})
            form_types.append(FormPattern(
                form_selector=fg.get("selector", ""),
                fields=fg.get("fields", []),
                submit_selector=submit.get("selector", ""),
                submit_method="filter",
            ))

        # Content patterns from nav samples
        content_types = [
            ContentPattern(
                page_type=s.get("page_type", "other"),
                url_pattern=s.get("url", ""),
                dom_readable=True,
                requires_scroll=s.get("has_scroll_content", False),
            )
            for s in nav.get("page_samples", [])
        ]

        # Thumbnail grids from object detection
        thumbnail_structures: list[ThumbnailGrid] = []
        for det in visual.get("obj_detections", []):
            if det.get("category") == "card":
                thumbnail_structures.append(
                    ThumbnailGrid(grid_type="product_card", card_has_text=True)
                )
                break

        # DOM hash
        dom_hash_data = json.dumps(
            {
                "total_elements": dom_complexity.total_elements,
                "max_depth": dom_complexity.max_depth,
                "framework": dom.get("framework"),
            },
            sort_keys=True,
        )
        dom_hash = hashlib.sha256(dom_hash_data.encode()).hexdigest()[:16]

        return SiteProfile(
            domain=domain,
            language="ko" if dom.get("total_elements", 0) > 0 else "en",
            created_at=now,
            last_recon_at=now,
            recon_version=existing_version + 1,
            dom_hash=dom_hash,
            dom_complexity=dom_complexity,
            framework=dom.get("framework"),
            has_shadow_dom=dom.get("has_shadow_dom", False),
            iframe_count=dom.get("iframe_count", 0),
            is_spa=dom.get("is_spa", False),
            visual_structure=visual_structure,
            canvas_usage=canvas_usage,
            image_density=dom.get("image_density", "low"),
            thumbnail_structures=thumbnail_structures,
            content_types=content_types,
            repeating_patterns=repeating,
            obstacles=obstacles,
            navigation=navigation,
            search_functionality=search_config,
            interaction_patterns=interaction_patterns,
            form_types=form_types,
            hover_dependent_menus=dom.get("menu_requires_hover", False),
        )

    async def _llm_refine(
        self,
        profile: SiteProfile,
        dom: dict[str, Any],
        visual: dict[str, Any],
        nav: dict[str, Any],
        llm: LLMLike,
    ) -> SiteProfile:
        """Refine profile using LLM synthesis."""
        try:
            summary = {
                "domain": profile.domain,
                "dom": {
                    k: v
                    for k, v in dom.items()
                    if k not in ("repeating_patterns", "forms", "obstacles")
                },
                "visual_detections": len(visual.get("obj_detections", [])),
                "vlm_analysis": visual.get("vlm_analysis"),
                "nav_url_patterns": nav.get("url_patterns", []),
                "nav_page_types": [
                    s.get("page_type") for s in nav.get("page_samples", [])
                ],
            }
            resp = await llm.complete(
                "fast",
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a web automation expert. "
                            "Given recon data, determine: "
                            "1) site purpose (ecommerce/news/portal/community/saas), "
                            "2) language (ko/en/ja/zh), "
                            "3) region (KR/US/JP). "
                            "Respond with JSON: {purpose, language, region}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(summary, ensure_ascii=False),
                    },
                ],
                max_tokens=200,
                temperature=0.0,
            )
            refined = json.loads(resp)
            profile.purpose = refined.get("purpose", profile.purpose)
            profile.language = refined.get("language", profile.language)
            profile.region = refined.get("region", profile.region)
        except Exception as e:
            logger.warning("LLM refinement failed: %s", e)

        return profile
