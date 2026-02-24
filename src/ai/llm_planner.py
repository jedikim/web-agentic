"""LLM Planner — L module for the adaptive web automation engine.

Implements the ``ILLMPlanner`` protocol using the Google Gemini API
with a tiered model strategy (Flash for speed, Pro for accuracy).
All outputs are structured patches — never free-form code (P3 principle).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types

from src.ai.prompt_manager import PromptManager
from src.core.types import ExtractedElement, PatchData, StepDefinition

logger = logging.getLogger(__name__)

# ── Model defaults (overridable via env vars) ────────

DEFAULT_FLASH_MODEL = os.environ.get("GEMINI_FLASH_MODEL", "gemini-3-flash-preview")
DEFAULT_PRO_MODEL = os.environ.get("GEMINI_PRO_MODEL", "gemini-3.1-pro-preview")

# ── Cost constants (USD per 1M tokens) ────────────────

_COST_PER_MILLION: dict[str, dict[str, float]] = {
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.0},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.0},
    "gemini-3-pro-preview": {"input": 2.00, "output": 12.0},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}
_DEFAULT_COST_PER_MILLION = {"input": 1.0, "output": 5.0}


@dataclass
class UsageStats:
    """Tracks cumulative token usage and cost."""

    total_tokens: int = 0
    total_cost_usd: float = 0.0
    calls: int = 0
    escalations: int = 0
    call_log: list[dict[str, Any]] = field(default_factory=list)

    def record(self, model: str, tokens: int) -> None:
        """Record a single API call.

        Uses a blended average of input/output cost for simplicity,
        since we only track total tokens, not input vs output separately.
        """
        pricing = _COST_PER_MILLION.get(model, _DEFAULT_COST_PER_MILLION)
        avg_per_million = (pricing["input"] + pricing["output"]) / 2
        cost = (tokens / 1_000_000) * avg_per_million
        self.total_tokens += tokens
        self.total_cost_usd += cost
        self.calls += 1
        self.call_log.append(
            {"model": model, "tokens": tokens, "cost_usd": cost}
        )


class LLMPlanner:
    """LLM-based planner using Google Gemini API.

    Implements the ``ILLMPlanner`` protocol with tiered model escalation:
    tier1 (Flash) is tried first; if confidence is low or parsing fails,
    tier2 (Pro) is used as a fallback.

    Args:
        prompt_manager: Prompt template manager.
        api_key: Gemini API key. Falls back to ``GEMINI_API_KEY`` env var.
        tier1_model: Primary (cheaper/faster) model name.
        tier2_model: Escalation (more capable) model name.
    """

    def __init__(
        self,
        prompt_manager: PromptManager,
        api_key: str | None = None,
        tier1_model: str | None = None,
        tier2_model: str | None = None,
        max_cost_usd: float = 0.20,
    ) -> None:
        self.prompt_manager = prompt_manager
        self.tier1_model = tier1_model or DEFAULT_FLASH_MODEL
        self.tier2_model = tier2_model or DEFAULT_PRO_MODEL
        self.usage = UsageStats()
        self._max_cost_usd = max_cost_usd

        resolved_key = api_key or os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
        self._client = genai.Client(api_key=resolved_key) if resolved_key else genai.Client()

    # ── Public API (ILLMPlanner Protocol) ────────────

    async def plan(self, instruction: str) -> list[StepDefinition]:
        """Decompose a natural language instruction into automation steps.

        Args:
            instruction: Natural language task description.

        Returns:
            Ordered list of ``StepDefinition`` objects.
        """
        prompt = self.prompt_manager.get_prompt(
            "plan_steps", instruction=instruction
        )

        # Tier 1 attempt
        response_text, tokens = await self._call_gemini(prompt, self.tier1_model)
        self.usage.record(self.tier1_model, tokens)

        try:
            steps, confidence = self._parse_plan_response(response_text)
            if confidence >= 0.7:
                return steps
            logger.info(
                "Tier1 plan confidence %.2f < 0.7, escalating to tier2",
                confidence,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Tier1 plan parse failed (%s), escalating to tier2", exc)
            steps = None

        # Cost guard: skip Tier2 if budget exceeded
        if self.usage.total_cost_usd >= self._max_cost_usd:
            logger.warning(
                "Cost limit $%.4f reached, skipping Tier2 plan escalation",
                self._max_cost_usd,
            )
            if steps is not None:
                return steps
            raise ValueError("Tier1 plan parse failed and cost limit reached")

        # Tier 2 escalation
        self.usage.escalations += 1
        response_text, tokens = await self._call_gemini(prompt, self.tier2_model)
        self.usage.record(self.tier2_model, tokens)
        steps, _ = self._parse_plan_response(response_text)
        return steps

    async def select(
        self, candidates: list[ExtractedElement], intent: str
    ) -> PatchData:
        """Select the best element from candidates for a given intent.

        Args:
            candidates: List of extracted DOM elements.
            intent: User intent or action description.

        Returns:
            ``PatchData`` with ``patch_type="selector_fix"`` containing
            the selected element ID and confidence.
        """
        candidates_json = json.dumps(
            [
                {
                    "eid": c.eid,
                    "type": c.type,
                    "text": c.text,
                    "role": c.role,
                    "visible": c.visible,
                }
                for c in candidates
            ],
            ensure_ascii=False,
            indent=2,
        )

        prompt = self.prompt_manager.get_prompt(
            "select_element", candidates=candidates_json, intent=intent
        )

        # Tier 1 attempt
        response_text, tokens = await self._call_gemini(prompt, self.tier1_model)
        self.usage.record(self.tier1_model, tokens)

        try:
            patch = self._parse_select_response(response_text)
            if patch.confidence >= 0.7:
                return patch
            logger.info(
                "Tier1 select confidence %.2f < 0.7, escalating to tier2",
                patch.confidence,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "Tier1 select parse failed (%s), escalating to tier2", exc
            )
            patch = None

        # Cost guard: skip Tier2 if budget exceeded
        if self.usage.total_cost_usd >= self._max_cost_usd:
            logger.warning(
                "Cost limit $%.4f reached, skipping Tier2 escalation",
                self._max_cost_usd,
            )
            if patch is not None:
                return patch
            # Tier1 parse failed and no budget — return low-confidence fallback
            return PatchData(
                patch_type="selector_fix",
                target="",
                data={"selected_eid": "", "reasoning": "cost limit reached"},
                confidence=0.0,
            )

        # Tier 2 escalation
        self.usage.escalations += 1
        response_text, tokens = await self._call_gemini(prompt, self.tier2_model)
        self.usage.record(self.tier2_model, tokens)
        return self._parse_select_response(response_text)

    async def plan_with_context(
        self,
        instruction: str,
        page_url: str = "",
        page_title: str = "",
        visible_text_snippet: str = "",
        attachments: list[dict[str, Any]] | None = None,
    ) -> list[StepDefinition]:
        """Plan with current page context for better LLM decisions.

        Args:
            instruction: Natural language task description.
            page_url: Current page URL.
            page_title: Current page title.
            visible_text_snippet: Truncated visible text from page.
            attachments: Optional list of attachment dicts with
                filename, mime_type, and base64_data keys (for multimodal).

        Returns:
            Ordered list of StepDefinition objects.
        """
        prompt = self.prompt_manager.get_prompt(
            "plan_steps_with_context",
            instruction=instruction,
            page_url=page_url,
            page_title=page_title,
            visible_text=visible_text_snippet[:500],
        )

        # Build image parts from attachments for multimodal
        images: list[dict[str, Any]] | None = None
        if attachments:
            images = [
                {"mime_type": a["mime_type"], "base64_data": a["base64_data"]}
                for a in attachments
                if a.get("mime_type", "").startswith("image/")
            ]
            if not images:
                images = None

        # Tier 1 attempt
        response_text, tokens = await self._call_gemini(
            prompt, self.tier1_model, images=images,
        )
        self.usage.record(self.tier1_model, tokens)

        try:
            steps, confidence = self._parse_plan_response(response_text)
            if confidence >= 0.7:
                return steps
            logger.info(
                "Tier1 plan_with_context confidence %.2f < 0.7, escalating",
                confidence,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Tier1 plan_with_context parse failed (%s), escalating", exc)
            steps = None

        # Cost guard: skip Tier2 if budget exceeded
        if self.usage.total_cost_usd >= self._max_cost_usd:
            logger.warning(
                "Cost limit $%.4f reached, skipping Tier2 plan escalation",
                self._max_cost_usd,
            )
            if steps is not None:
                return steps
            raise ValueError("Tier1 plan parse failed and cost limit reached")

        # Tier 2 escalation
        self.usage.escalations += 1
        response_text, tokens = await self._call_gemini(
            prompt, self.tier2_model, images=images,
        )
        self.usage.record(self.tier2_model, tokens)
        steps, _ = self._parse_plan_response(response_text)
        return steps

    async def solve_captcha(self, captcha_info: dict[str, str]) -> str:
        """Solve a CAPTCHA given its visual analysis.

        The CAPTCHA has already been analyzed by YOLO/VLM.
        This method uses pure text reasoning to compute the answer.

        Args:
            captcha_info: Dict with keys: captcha_type, image_description,
                          question, and optionally raw_text.

        Returns:
            The answer string to type into the CAPTCHA input.
        """
        prompt = (
            "You are solving a CAPTCHA challenge. The image has already been analyzed.\n\n"
            f"CAPTCHA type: {captcha_info.get('captcha_type', 'unknown')}\n"
            f"Image description: {captcha_info.get('image_description', '')}\n"
            f"Question: {captcha_info.get('question', '')}\n\n"
            "Based on the description above, what is the correct answer?\n"
            "Think step by step, then provide ONLY the answer.\n\n"
            'Respond with JSON: {"reasoning": "step by step thinking", "answer": "the answer"}\n'
            "The answer should be exactly what needs to be typed into the input field."
        )

        response_text, tokens = await self._call_gemini(prompt, self.tier1_model)
        self.usage.record(self.tier1_model, tokens)

        # Parse answer from response
        try:
            cleaned = _extract_json(response_text)
            data = json.loads(cleaned)
            answer = str(data.get("answer", ""))
            reasoning = data.get("reasoning", "")
            logger.info("CAPTCHA solve reasoning: %s", reasoning)
            logger.info("CAPTCHA solve answer: %s", answer)
            return answer
        except (json.JSONDecodeError, KeyError, ValueError):
            # Fallback: try to extract any short answer from text
            logger.warning("Failed to parse CAPTCHA solve response, using raw text")
            # Look for a short answer (numbers, short text)
            lines = response_text.strip().split("\n")
            for line in reversed(lines):
                line = line.strip().strip('"').strip("'")
                if line and len(line) <= 20:
                    return line
            return response_text.strip()[:20]

    # ── Internal: Gemini API call ────────────────────

    async def _call_gemini(
        self,
        prompt: str,
        model: str,
        images: list[dict[str, Any]] | None = None,
    ) -> tuple[str, int]:
        """Call the Gemini API and return (response_text, tokens_used).

        This method wraps the actual API call and is designed to be
        easily mocked in unit tests. When *images* are provided the
        call becomes multimodal (text + inline image parts).

        Args:
            prompt: The full prompt string.
            model: Gemini model name.
            images: Optional list of dicts with ``mime_type`` and
                ``base64_data`` keys for inline image content.

        Returns:
            Tuple of (response text, token count).
        """
        # Build content: text-only or multimodal (text + images)
        if images:
            content_parts: list[Any] = [prompt]
            for img in images:
                content_parts.append(
                    types.Part.from_bytes(
                        data=base64.b64decode(img["base64_data"]),
                        mime_type=img["mime_type"],
                    )
                )
            response = await self._client.aio.models.generate_content(
                model=model, contents=content_parts,
            )
        else:
            response = await self._client.aio.models.generate_content(
                model=model, contents=prompt,
            )

        text = response.text or ""
        # Estimate token count from usage metadata if available,
        # otherwise approximate from text length
        tokens_used = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            tokens_used = getattr(response.usage_metadata, "total_token_count", 0)
        if tokens_used == 0:
            # Rough approximation: 1 token ≈ 4 characters
            tokens_used = (len(prompt) + len(text)) // 4
        return text, tokens_used

    # ── Internal: Response parsing ───────────────────

    @staticmethod
    def _parse_plan_response(text: str) -> tuple[list[StepDefinition], float]:
        """Parse a plan response into StepDefinitions and confidence.

        Handles aliases:
        - step_id: also accepts id
        - intent: also accepts description
        - node_type: also accepts action, type
        - max_attempts, timeout_ms: validated as positive integers

        Args:
            text: Raw LLM response text.

        Returns:
            Tuple of (list of StepDefinition, confidence score).

        Raises:
            json.JSONDecodeError: If the text is not valid JSON.
            KeyError: If required fields are missing.
            ValueError: If step data is invalid.
        """
        cleaned = _extract_json(text)
        data = json.loads(cleaned)

        confidence = 1.0
        if isinstance(data, dict):
            confidence = float(data.get("confidence", 1.0))
            steps_data = data.get("steps", [])
        elif isinstance(data, list):
            steps_data = data
        else:
            raise ValueError(f"Unexpected response type: {type(data).__name__}")

        steps: list[StepDefinition] = []
        for i, s in enumerate(steps_data):
            if not isinstance(s, dict):
                raise ValueError(f"Step {i} is not a dict: {type(s).__name__}")

            # Handle field aliases
            step_id = str(s.get("step_id") or s.get("id") or f"step_{i + 1}")
            intent = str(s.get("intent") or s.get("description") or "")
            node_type = str(
                s.get("node_type") or s.get("action") or s.get("type") or "action"
            )

            # Validate positive integers
            raw_max_attempts = s.get("max_attempts", 3)
            max_attempts = max(1, int(raw_max_attempts))

            raw_timeout_ms = s.get("timeout_ms", 10000)
            timeout_ms = max(1, int(raw_timeout_ms))

            step = StepDefinition(
                step_id=step_id,
                intent=intent,
                node_type=node_type,
                selector=s.get("selector"),
                arguments=list(s.get("arguments", [])),
                max_attempts=max_attempts,
                timeout_ms=timeout_ms,
            )
            steps.append(step)

        if not steps:
            raise ValueError("Plan response contains no steps")

        return steps, confidence

    @staticmethod
    def _parse_select_response(text: str) -> PatchData:
        """Parse a select response into PatchData.

        Accepts alternative field names for robustness:
        - eid: also accepts element_id, selected_eid, selector, id
        - confidence: clamped to [0.0, 1.0]
        - reasoning: also accepts reason, explanation

        Args:
            text: Raw LLM response text.

        Returns:
            PatchData with patch_type="selector_fix".

        Raises:
            json.JSONDecodeError: If the text is not valid JSON.
            KeyError: If no element ID field is found.
        """
        cleaned = _extract_json(text)
        data = json.loads(cleaned)

        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")

        # Accept alternative field names for element ID
        eid = None
        for key in ("eid", "element_id", "selected_eid", "selector", "id"):
            if key in data:
                eid = data[key]
                break
        if eid is None:
            raise KeyError(
                "No element ID field found (tried: eid, element_id, selected_eid, selector, id)"
            )

        # Confidence with clamping
        raw_confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, raw_confidence))

        # Accept alternative reasoning fields
        reasoning = ""
        for key in ("reasoning", "reason", "explanation"):
            if key in data:
                reasoning = data[key]
                break

        return PatchData(
            patch_type="selector_fix",
            target=str(eid),
            data={"selected_eid": str(eid), "reasoning": str(reasoning)},
            confidence=confidence,
        )


# ── Helpers ──────────────────────────────────────────


def _extract_json(text: str) -> str:
    """Extract JSON from a response that may contain markdown fences or preamble.

    Handles:
    1. Markdown code fences (```json ... ```)
    2. Raw JSON structure detection ({...} or [...])
    3. Fallback: return stripped text

    Args:
        text: Raw response text.

    Returns:
        Cleaned JSON string.
    """
    # 1. Try markdown code fences first
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 2. Try to find raw JSON structure (outermost { } or [ ])
    #    Pick whichever delimiter appears first in the text.
    stripped = text.strip()
    candidates: list[tuple[int, str, str]] = []
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        idx = stripped.find(start_char)
        if idx != -1:
            candidates.append((idx, start_char, end_char))

    # Sort by position so we try the earliest delimiter first
    candidates.sort(key=lambda x: x[0])

    for start_idx, start_char, end_char in candidates:
        # Find matching closing bracket
        depth = 0
        in_string = False
        escape = False
        for i in range(start_idx, len(stripped)):
            c = stripped[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == start_char:
                depth += 1
            elif c == end_char:
                depth -= 1
                if depth == 0:
                    return stripped[start_idx : i + 1]

    # 3. Fallback
    return stripped


# ── Factory ──────────────────────────────────────────


def create_llm_planner(
    api_key: str | None = None,
    max_cost_usd: float = 0.20,
) -> LLMPlanner:
    """Create an ``LLMPlanner`` with default configuration.

    Args:
        api_key: Gemini API key. Falls back to ``GEMINI_API_KEY`` env var.
        max_cost_usd: Maximum total cost before skipping Tier2 escalation.

    Returns:
        Configured ``LLMPlanner`` instance.
    """
    prompt_manager = PromptManager()
    return LLMPlanner(
        prompt_manager=prompt_manager,
        api_key=api_key,
        max_cost_usd=max_cost_usd,
    )
