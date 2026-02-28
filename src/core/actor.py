"""Actor — LLM selects target element from filtered candidates.

Given a list of ScoredNode candidates from ElementFilter, the Actor:
1. Formats candidates as YAML for token efficiency
2. Asks LLM to pick the best match (index + selector + action)
3. Computes viewport-relative coordinates for the selected element

The Actor outputs an Action with both selector and viewport_xy.
Falls back to planner coordinates if element can't be located.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from src.core.browser import Browser
from src.core.types import Action, ScoredNode, StepPlan

logger = logging.getLogger(__name__)


class IActorLLM(Protocol):
    """LLM interface for Actor element selection."""

    async def generate(self, prompt: str) -> str: ...


class Actor:
    """Select target element from candidates using LLM.

    Usage:
        actor = Actor(llm=gemini_flash)
        action = await actor.decide(step, candidates, browser)
    """

    def __init__(self, llm: IActorLLM) -> None:
        self._llm = llm

    async def decide(
        self,
        step: StepPlan,
        candidates: list[ScoredNode],
        browser: Browser,
    ) -> Action:
        """Ask LLM to select the best candidate and return an Action.

        Args:
            step: The planned step with target description and action type.
            candidates: Filtered DOM node candidates with scores.
            browser: Browser instance for coordinate computation.

        Returns:
            Action with selector, action_type, value, and viewport coordinates.
        """
        if not candidates:
            # No candidates — return viewport-only action from step plan
            return Action(
                selector=None,
                action_type=step.action_type,
                value=step.value,
                viewport_xy=step.target_viewport_xy,
            )

        # Format candidates as compact YAML
        yaml_text = self._to_yaml(candidates)

        prompt = (
            f"Task step: {step.action_type} - {step.target_description}\n"
            f"Candidates:\n{yaml_text}\n\n"
            f'Output JSON: {{"index": N, "selector": "css_selector", '
            f'"action": "click" or "type", "value": "..."}}'
        )

        response = await self._llm.generate(prompt)
        parsed = self._parse_response(response, candidates)

        # Compute viewport-relative coordinates
        viewport_xy, viewport_bbox = await self._get_viewport_coords(
            browser, parsed["selector"],
        )

        # If selector couldn't be located in page, fall back to planner xy
        if viewport_xy is None and step.target_viewport_xy is not None:
            logger.info(
                "Selector %s not found in page, using planner xy %s",
                parsed["selector"], step.target_viewport_xy,
            )
            viewport_xy = step.target_viewport_xy

        # For type/fill actions, always use step.value from planner.
        # The planner decides WHAT to type; the actor decides WHERE.
        action_type = parsed["action"]
        value = step.value if action_type in ("type", "fill") else parsed.get("value") or step.value

        return Action(
            selector=parsed["selector"],
            action_type=action_type,
            value=value,
            viewport_xy=viewport_xy,
            viewport_bbox=viewport_bbox,
        )

    def _to_yaml(self, candidates: list[ScoredNode]) -> str:
        """Format candidates as compact YAML for LLM prompt."""
        lines: list[str] = []
        for i, scored in enumerate(candidates):
            node = scored.node
            parts = [f"  tag: {node.tag}"]
            if node.text:
                parts.append(f"  text: {node.text[:100]}")
            if node.ax_name:
                parts.append(f"  name: {node.ax_name}")
            if node.ax_role:
                parts.append(f"  role: {node.ax_role}")
            # Include key attributes
            for attr in ("id", "name", "placeholder", "type", "href", "aria-label"):
                if attr in node.attrs:
                    parts.append(f"  {attr}: {node.attrs[attr][:80]}")
            parts.append(f"  score: {scored.score:.2f}")
            lines.append(f"- index: {i}\n" + "\n".join(parts))
        return "\n".join(lines)

    def _parse_response(
        self,
        response: str,
        candidates: list[ScoredNode],
    ) -> dict[str, Any]:
        """Parse LLM response into structured data.

        Extracts JSON from the response and validates the index.
        Falls back to the highest-scored candidate on parse failure.
        """
        # Try to extract JSON from response
        json_match = re.search(r"\{[^}]+\}", response)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                idx = parsed.get("index", 0)
                if 0 <= idx < len(candidates):
                    # Build selector from candidate if not provided
                    if "selector" not in parsed or not parsed["selector"]:
                        parsed["selector"] = self._build_selector(candidates[idx].node)
                    return {
                        "index": idx,
                        "selector": parsed.get("selector", ""),
                        "action": parsed.get("action", "click"),
                        "value": parsed.get("value"),
                    }
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        # Fallback: use highest-scored candidate
        best = candidates[0]
        return {
            "index": 0,
            "selector": self._build_selector(best.node),
            "action": "click",
            "value": None,
        }

    def _build_selector(self, node: Any) -> str:
        """Build a CSS selector from a DOMNode's attributes."""
        attrs = node.attrs
        tag = node.tag

        # Priority: id > name > aria-label > placeholder > tag:nth
        if "id" in attrs and attrs["id"]:
            return f"#{attrs['id']}"
        if "name" in attrs and attrs["name"]:
            return f'{tag}[name="{attrs["name"]}"]'
        if "aria-label" in attrs and attrs["aria-label"]:
            label = attrs["aria-label"].replace('"', '\\"')
            return f'{tag}[aria-label="{label}"]'
        if "placeholder" in attrs and attrs["placeholder"]:
            ph = attrs["placeholder"][:30].replace('"', '\\"')
            return f'{tag}[placeholder*="{ph}"]'
        if "href" in attrs and attrs["href"]:
            href = attrs["href"].replace('"', '\\"')
            return f'{tag}[href="{href}"]'

        return tag

    async def _get_viewport_coords(
        self,
        browser: Browser,
        selector: str | None,
    ) -> tuple[tuple[float, float] | None, tuple[float, float, float, float] | None]:
        """Get viewport-relative coordinates (0.0~1.0) for an element."""
        if not selector:
            return None, None

        try:
            # Escape selector for JS string literal
            safe = selector.replace("\\", "\\\\").replace("'", "\\'")
            result = await browser.evaluate(f"""(() => {{
                const el = document.querySelector('{safe}');
                if (!el) return null;
                const r = el.getBoundingClientRect();
                const vw = window.innerWidth;
                const vh = window.innerHeight;
                return {{
                    cx: (r.left + r.right) / 2 / vw,
                    cy: (r.top + r.bottom) / 2 / vh,
                    x1: r.left / vw, y1: r.top / vh,
                    x2: r.right / vw, y2: r.bottom / vh,
                }};
            }})()""")
        except Exception:
            return None, None

        if not result:
            return None, None

        return (
            (result["cx"], result["cy"]),
            (result["x1"], result["y1"], result["x2"], result["y2"]),
        )
