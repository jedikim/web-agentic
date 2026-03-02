"""Self-improvement dispatcher — remediate failures by patching KB artifacts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.kb.manager import KBManager
from src.llm.router import LLMRouter
from src.models.failure import FailureEvidence, RemediationAction

logger = logging.getLogger(__name__)

# ── Prompts ──

_SELECTOR_PATCH_PROMPT = """The following workflow step failed because the CSS selector
no longer matches. Suggest a replacement selector.

Failed selector: {selector}
Error: {error_message}
Current workflow step:
{step_json}

Page URL: {url}

Respond with JSON: {{"new_selector": "<css>", "reason": "<why>"}}"""

_OBSTACLE_DISMISS_PROMPT = """Generate a Playwright code snippet to dismiss this obstacle.

Obstacle type: {obstacle_type}
Error: {error_message}
URL: {url}

Respond with JSON: {{
  "dismiss_code": "<playwright python snippet>",
  "obstacle_type": "<type>",
  "reason": "<explanation>"
}}"""

_STRATEGY_PROMPT = """The current automation strategy is failing for this page.

Current strategy: {strategy}
Error: {error_message}
URL: {url}

Available strategies: dom_only, dom_with_objdet_backup, objdet_dom_hybrid,
grid_vlm, vlm_only.

Respond with JSON: {{
  "new_strategy": "<strategy>",
  "reason": "<why>"
}}"""

_WAIT_PROMPT = """This automation step is timing out. Suggest where to insert
a wait and how long.

Error: {error_message}
URL: {url}
Step: {step_json}

Respond with JSON: {{
  "wait_ms": <integer>,
  "wait_for": "<selector or condition>",
  "insert_before_step": <step_index>,
  "reason": "<why>"
}}"""


@dataclass
class ImprovementResult:
    """Outcome of a self-improvement attempt."""

    action_taken: str = "none"
    new_version: int | None = None
    needs_recon: bool = False
    needs_human: bool = False
    detail: str = ""
    patches: list[dict[str, Any]] = field(default_factory=list)


class SelfImprover:
    """Dispatch remediation actions to patch KB artifacts.

    Routes each RemediationAction to a specific handler that loads
    the relevant artifact from KB, asks LLM for a fix, and saves
    the new version.
    """

    def __init__(self) -> None:
        pass

    async def improve(
        self,
        evidence: FailureEvidence,
        domain: str,
        url_pattern: str,
        kb: KBManager,
        llm: LLMRouter,
    ) -> ImprovementResult:
        """Apply remediation based on failure evidence.

        Args:
            evidence: Classified failure with remediation action.
            domain: Site domain (e.g. "shopping.naver.com").
            url_pattern: URL pattern in KB (e.g. "/search*").
            kb: Knowledge Base manager.
            llm: LLM router for generating patches.

        Returns:
            ImprovementResult describing what was done.
        """
        dispatch = {
            RemediationAction.FIX_SELECTOR: self._fix_selector,
            RemediationAction.FIX_OBSTACLE: self._fix_obstacle,
            RemediationAction.CHANGE_STRATEGY: self._change_strategy,
            RemediationAction.FULL_RECON: self._full_recon,
            RemediationAction.ADD_WAIT: self._add_wait,
            RemediationAction.HUMAN_HANDOFF: self._human_handoff,
        }
        handler = dispatch.get(evidence.remediation, self._human_handoff)
        return await handler(evidence, domain, url_pattern, kb, llm)

    async def _fix_selector(
        self,
        ev: FailureEvidence,
        domain: str,
        url_pattern: str,
        kb: KBManager,
        llm: LLMRouter,
    ) -> ImprovementResult:
        """Load workflow, ask LLM for selector patch, save new version."""
        workflow = kb.load_workflow(domain, url_pattern)
        if not workflow:
            return ImprovementResult(
                action_taken="fix_selector",
                detail="No workflow found in KB; cannot patch.",
            )

        # Find the failing step by selector match
        steps = workflow.get("steps", [])
        step_json = "{}"
        for step in steps:
            if step.get("selector") == ev.selector:
                step_json = json.dumps(step, ensure_ascii=False)
                break

        prompt = _SELECTOR_PATCH_PROMPT.format(
            selector=ev.selector or "unknown",
            error_message=ev.error_message,
            step_json=step_json,
            url=ev.url,
        )
        raw = await llm.complete(
            "fast",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.0,
        )
        patch = _parse_json_safe(raw)
        new_selector = patch.get("new_selector")
        if not new_selector:
            return ImprovementResult(
                action_taken="fix_selector",
                detail=f"LLM did not produce a valid selector: {raw[:200]}",
            )

        # Apply patch to workflow
        for step in steps:
            if step.get("selector") == ev.selector:
                step["selector"] = new_selector
                break

        new_ver = kb.save_workflow(domain, url_pattern, workflow)
        logger.info(
            "Patched selector %s -> %s (v%d)",
            ev.selector, new_selector, new_ver,
        )
        return ImprovementResult(
            action_taken="fix_selector",
            new_version=new_ver,
            detail=f"Selector patched: {ev.selector} -> {new_selector}",
            patches=[patch],
        )

    async def _fix_obstacle(
        self,
        ev: FailureEvidence,
        domain: str,
        url_pattern: str,
        kb: KBManager,
        llm: LLMRouter,
    ) -> ImprovementResult:
        """Generate obstacle dismissal code and store in workflow."""
        obstacle_type = ev.extra.get("obstacle_type", "unknown")
        prompt = _OBSTACLE_DISMISS_PROMPT.format(
            obstacle_type=obstacle_type,
            error_message=ev.error_message,
            url=ev.url,
        )
        raw = await llm.complete(
            "fast",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.0,
        )
        patch = _parse_json_safe(raw)
        dismiss_code = patch.get("dismiss_code", "")

        workflow = kb.load_workflow(domain, url_pattern) or {"steps": []}
        # Prepend obstacle dismissal as first step
        obstacle_step = {
            "action": "run_code",
            "code": dismiss_code,
            "description": f"Dismiss {obstacle_type} obstacle",
            "auto_generated": True,
        }
        workflow.setdefault("steps", []).insert(0, obstacle_step)
        new_ver = kb.save_workflow(domain, url_pattern, workflow)

        return ImprovementResult(
            action_taken="fix_obstacle",
            new_version=new_ver,
            detail=f"Added obstacle dismissal for {obstacle_type}",
            patches=[patch],
        )

    async def _change_strategy(
        self,
        ev: FailureEvidence,
        domain: str,
        url_pattern: str,
        kb: KBManager,
        llm: LLMRouter,
    ) -> ImprovementResult:
        """Ask LLM for a better strategy and update workflow metadata."""
        workflow = kb.load_workflow(domain, url_pattern) or {}
        current_strategy = workflow.get("strategy", "dom_only")

        prompt = _STRATEGY_PROMPT.format(
            strategy=current_strategy,
            error_message=ev.error_message,
            url=ev.url,
        )
        raw = await llm.complete(
            "fast",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,
        )
        patch = _parse_json_safe(raw)
        new_strategy = patch.get("new_strategy", current_strategy)

        workflow["strategy"] = new_strategy
        new_ver = kb.save_workflow(domain, url_pattern, workflow)

        return ImprovementResult(
            action_taken="change_strategy",
            new_version=new_ver,
            detail=f"Strategy changed: {current_strategy} -> {new_strategy}",
            patches=[patch],
        )

    async def _full_recon(
        self,
        ev: FailureEvidence,
        domain: str,
        url_pattern: str,
        kb: KBManager,
        llm: LLMRouter,
    ) -> ImprovementResult:
        """Signal that a full site reconnaissance is needed."""
        return ImprovementResult(
            action_taken="full_recon",
            needs_recon=True,
            detail=f"Site change detected: {ev.error_message[:120]}",
        )

    async def _add_wait(
        self,
        ev: FailureEvidence,
        domain: str,
        url_pattern: str,
        kb: KBManager,
        llm: LLMRouter,
    ) -> ImprovementResult:
        """Insert a wait step into the workflow DSL."""
        workflow = kb.load_workflow(domain, url_pattern) or {"steps": []}
        steps = workflow.get("steps", [])
        step_json = json.dumps(steps[:5], ensure_ascii=False)

        prompt = _WAIT_PROMPT.format(
            error_message=ev.error_message,
            url=ev.url,
            step_json=step_json,
        )
        raw = await llm.complete(
            "fast",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,
        )
        patch = _parse_json_safe(raw)
        wait_ms = patch.get("wait_ms", 3000)
        wait_for = patch.get("wait_for", "")
        idx = patch.get("insert_before_step", 0)
        idx = max(0, min(idx, len(steps)))

        wait_step = {
            "action": "wait",
            "wait_ms": wait_ms,
            "wait_for": wait_for,
            "auto_generated": True,
        }
        steps.insert(idx, wait_step)
        workflow["steps"] = steps
        new_ver = kb.save_workflow(domain, url_pattern, workflow)

        return ImprovementResult(
            action_taken="add_wait",
            new_version=new_ver,
            detail=f"Inserted wait {wait_ms}ms at step {idx}",
            patches=[patch],
        )

    async def _human_handoff(
        self,
        ev: FailureEvidence,
        domain: str,
        url_pattern: str,
        kb: KBManager,
        llm: LLMRouter,
    ) -> ImprovementResult:
        """Return a handoff signal for human intervention."""
        return ImprovementResult(
            action_taken="human_handoff",
            needs_human=True,
            detail=(
                f"Human intervention required: {ev.failure_type.value} "
                f"— {ev.error_message[:120]}"
            ),
        )


def _parse_json_safe(raw: str) -> dict[str, Any]:
    """Extract JSON from LLM response, tolerating markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # drop opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM JSON: %s", text[:200])
        return {}
