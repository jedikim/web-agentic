"""RetryHandler — LLM-assisted retry on action failure.

When an action fails (selector not found, wrong element clicked, etc.),
the RetryHandler:
1. Takes a screenshot of current page
2. Re-extracts DOM nodes
3. Asks VLM to analyze what went wrong and pick a different target
4. Returns a new Action for the orchestrator to try

This is the "_retry_with_llm" from the architecture doc.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Protocol

from src.core.types import Action, StepPlan

logger = logging.getLogger(__name__)

_RETRY_PROMPT_TEMPLATE = """\
이전 액션이 실패했습니다. 스크린샷과 DOM 정보를 보고 다른 요소를 선택하세요.

## 실패 정보
- selector: {selector}
- viewport_xy: {viewport_xy}
- action: {action_type}
- 시도: {attempt}/{max_attempts}
- 원래 목표: {target_description}

## 현재 페이지 DOM (상위 인터랙티브 요소)
{dom_summary}

다른 대상 요소를 선택하세요. selector와 viewport 좌표 둘 다 제공하세요.

JSON으로 답하세요:
{{"selector": "css_selector", "action": "click" | "type",
  "value": "..." | null, "viewport_xy": [x, y]}}"""


class IRetryVLM(Protocol):
    """VLM interface for retry — accepts text + image."""

    async def generate_with_image(self, prompt: str, image: bytes) -> str: ...


class RetryHandler:
    """Handle action retries using VLM to pick alternative targets.

    Usage:
        handler = RetryHandler(vlm=gemini_flash)
        new_action = await handler.suggest_retry(
            failed_action, step, screenshot, dom_summary, attempt=1,
        )
    """

    def __init__(self, vlm: IRetryVLM) -> None:
        self._vlm = vlm

    async def suggest_retry(
        self,
        failed_action: Action,
        step: StepPlan,
        screenshot: bytes,
        dom_summary: str,
        attempt: int = 1,
        max_attempts: int = 3,
    ) -> Action:
        """Suggest a retry action after failure.

        Args:
            failed_action: The action that failed.
            step: The original step plan.
            screenshot: Current page screenshot.
            dom_summary: Formatted DOM nodes summary.
            attempt: Current attempt number.
            max_attempts: Maximum retry attempts.

        Returns:
            A new Action to try.
        """
        prompt = _RETRY_PROMPT_TEMPLATE.format(
            selector=failed_action.selector or "None",
            viewport_xy=failed_action.viewport_xy,
            action_type=failed_action.action_type,
            attempt=attempt,
            max_attempts=max_attempts,
            target_description=step.target_description,
            dom_summary=dom_summary,
        )

        response = await self._vlm.generate_with_image(prompt, screenshot)
        return self._parse_response(response, step)

    def _parse_response(self, response: str, step: StepPlan) -> Action:
        """Parse VLM retry response into an Action."""
        # Try to extract JSON from response
        json_match = re.search(r"\{[^}]+\}", response)
        if json_match:
            try:
                data = json.loads(json_match.group())
                xy = data.get("viewport_xy")
                if isinstance(xy, list) and len(xy) == 2:
                    try:
                        xy = (float(xy[0]), float(xy[1]))
                    except (ValueError, TypeError):
                        xy = step.target_viewport_xy
                else:
                    xy = step.target_viewport_xy

                return Action(
                    selector=data.get("selector"),
                    action_type=data.get("action", step.action_type),
                    value=data.get("value") or step.value,
                    viewport_xy=xy,
                )
            except (json.JSONDecodeError, KeyError):
                pass

        # Fallback: use step's viewport_xy with no selector
        logger.warning("RetryHandler: failed to parse VLM response, using viewport fallback")
        return Action(
            selector=None,
            action_type=step.action_type,
            value=step.value,
            viewport_xy=step.target_viewport_xy,
        )

    @staticmethod
    def format_dom_nodes(nodes: list) -> str:  # type: ignore[type-arg]
        """Format DOM nodes as compact text for the retry prompt.

        Args:
            nodes: List of DOMNode objects.

        Returns:
            Compact text representation of top 30 nodes.
        """
        lines: list[str] = []
        for i, node in enumerate(nodes[:30]):
            tag = getattr(node, "tag", "?")
            text = getattr(node, "text", "")[:60]
            attrs = getattr(node, "attrs", {})
            parts = [f"{i}: <{tag}>"]
            if text:
                parts.append(f'"{text}"')
            for attr in ("id", "name", "aria-label", "placeholder", "href"):
                if attr in attrs:
                    parts.append(f'{attr}="{attrs[attr][:40]}"')
            lines.append(" ".join(parts))
        return "\n".join(lines)
