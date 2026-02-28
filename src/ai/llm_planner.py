"""LLM Planner — L module for the adaptive web automation engine.

Implements the ``ILLMPlanner`` protocol using the Google Gemini API.
Automation runtime uses Flash only — Pro is reserved for coding tasks
(evolution/code_generator). All outputs are structured patches (P3 principle).
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

from src.ai.llm_provider import ILLMProvider
from src.ai.prompt_manager import PromptManager
from src.core.types import ExtractedElement, PatchData, StepDefinition
from src.observability.tracing import trace, update_current_observation


@dataclass(frozen=True)
class CaptchaAction:
    """A single action in a CAPTCHA solving plan."""

    action: str  # click, type, press_key
    target: str = ""  # element description for matching
    value: str = ""  # text to type or key to press
    description: str = ""


@dataclass(frozen=True)
class CaptchaActionPlan:
    """LLM-planned sequence of actions to solve a CAPTCHA."""

    actions: list[CaptchaAction]
    needs_iframe: bool = False
    reasoning: str = ""

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

    Automation runtime uses Flash only. Pro model reference is kept for
    non-runtime use cases (e.g. evolution code generation) but is never
    used in plan/select/fix_selector calls.

    Args:
        prompt_manager: Prompt template manager.
        api_key: Gemini API key. Falls back to ``GEMINI_API_KEY`` env var.
        tier1_model: Primary (cheaper/faster) model name.
        tier2_model: Pro model name (retained for non-runtime use).
        provider: Optional LLM provider instance. When set, all API
            calls go through this provider instead of the built-in
            Gemini client.
    """

    def __init__(
        self,
        prompt_manager: PromptManager,
        api_key: str | None = None,
        tier1_model: str | None = None,
        tier2_model: str | None = None,
        max_cost_usd: float = 0.20,
        provider: ILLMProvider | None = None,
    ) -> None:
        self.prompt_manager = prompt_manager
        self.tier1_model = tier1_model or DEFAULT_FLASH_MODEL
        self.tier2_model = tier2_model or DEFAULT_PRO_MODEL
        self.usage = UsageStats()
        self._max_cost_usd = max_cost_usd
        self._provider = provider

        if provider is None:
            resolved_key = (
                api_key
                or os.environ.get("GEMINI_API_KEY", "")
                or os.environ.get("GOOGLE_API_KEY", "")
            )
            self._client = (
                genai.Client(api_key=resolved_key) if resolved_key else genai.Client()
            )
        else:
            self._client = None  # type: ignore[assignment]

    # ── Public API (ILLMPlanner Protocol) ────────────

    @trace(name="llm-plan")
    async def plan(self, instruction: str) -> list[StepDefinition]:
        """Decompose a natural language instruction into automation steps.

        Uses Flash model only — Pro is reserved for coding tasks
        (evolution/code_generator).

        Args:
            instruction: Natural language task description.

        Returns:
            Ordered list of ``StepDefinition`` objects.
        """
        prompt = self.prompt_manager.get_prompt(
            "plan_steps", instruction=instruction
        )

        response_text, tokens = await self._call_gemini(prompt, self.tier1_model)
        self.usage.record(self.tier1_model, tokens)

        steps, _confidence = self._parse_plan_response(response_text)
        return steps

    @trace(name="llm-select")
    async def select(
        self, candidates: list[ExtractedElement], intent: str,
        page_context: str = "",
    ) -> PatchData:
        """Select the best element from candidates for a given intent.

        Args:
            candidates: List of extracted DOM elements.
            intent: User intent or action description.
            page_context: Optional page context string (URL, title,
                visible text, previous action) to help disambiguate.

        Returns:
            ``PatchData`` with ``patch_type="selector_fix"`` containing
            the selected element ID and confidence.
        """
        candidates_json = json.dumps(
            [
                {
                    "eid": c.eid,
                    "type": c.type,
                    "text": (c.text or "")[:80],
                    **({"role": c.role} if c.role else {}),
                }
                for c in candidates
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )

        prompt = self.prompt_manager.get_prompt(
            "select_element",
            candidates=candidates_json,
            intent=intent,
            page_context=page_context,
        )

        # Element selection: Flash only (no Pro escalation).
        # Escalating to Pro for selection is wasteful — if Flash can't find
        # the right element in the candidate list, Pro won't do better.
        # The candidate list quality matters more than the model tier.
        response_text, tokens = await self._call_gemini(prompt, self.tier1_model)
        self.usage.record(self.tier1_model, tokens)

        try:
            result = self._parse_select_response(response_text)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Select parse failed (%s), returning empty", exc)
            return PatchData(
                patch_type="selector_fix",
                target="",
                data={"selected_eid": "", "reasoning": f"parse error: {exc}"},
                confidence=0.0,
            )

        # Validate that the returned eid matches an actual candidate.
        # LLMs sometimes hallucinate CSS selectors instead of picking
        # from the provided candidate list.
        valid_eids = {c.eid for c in candidates}
        if result.target in valid_eids:
            return result

        # Try fuzzy matching: the LLM may have returned a close variant
        selected = result.target.strip()
        for c in candidates:
            if c.eid.strip() == selected:
                return result

        # LLM returned an invalid eid — find the best candidate by
        # matching the LLM's reasoning/eid text against candidate text.
        logger.warning(
            "LLM select returned invalid eid '%s', "
            "falling back to text matching from %d candidates",
            selected, len(candidates),
        )
        best_candidate = None
        best_score = -1
        import re as _re
        search_words = _re.findall(r"[\w가-힣]{2,}", selected.lower())
        if not search_words:
            search_words = _re.findall(
                r"[\w가-힣]{2,}",
                result.data.get("reasoning", "").lower(),
            )
        for c in candidates:
            txt = ((c.text or "") + " " + (c.role or "")).lower()
            score = sum(1 for w in search_words if w in txt)
            if score > best_score:
                best_score = score
                best_candidate = c
        if best_candidate and best_score > 0:
            logger.info(
                "Recovered: mapped to eid=%s (score=%d)",
                best_candidate.eid, best_score,
            )
            return PatchData(
                patch_type="selector_fix",
                target=best_candidate.eid,
                data={
                    "selected_eid": best_candidate.eid,
                    "reasoning": f"recovered from invalid '{selected}'",
                },
                confidence=max(0.3, result.confidence * 0.5),
            )

        return result  # Return as-is, let executor handle the failure

    @trace(name="llm-plan-with-context")
    async def plan_with_context(
        self,
        instruction: str,
        page_url: str = "",
        page_title: str = "",
        visible_text_snippet: str = "",
        attachments: list[dict[str, Any]] | None = None,
    ) -> list[StepDefinition]:
        """Plan with current page context for better LLM decisions.

        Uses Flash model only — Pro is reserved for coding tasks
        (evolution/code_generator).

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

        response_text, tokens = await self._call_gemini(
            prompt, self.tier1_model, images=images,
        )
        self.usage.record(self.tier1_model, tokens)

        steps, _confidence = self._parse_plan_response(response_text)
        return steps

    async def plan_captcha_action(
        self, captcha_info: dict[str, str], elements: list[ExtractedElement]
    ) -> CaptchaActionPlan:
        """Plan CAPTCHA solving actions using LLM.

        Given VLM analysis results and the current page elements, the LLM
        decides what sequence of actions (click, type, press_key) to perform.

        Args:
            captcha_info: Dict with keys from VLM analysis (captcha_type,
                image_description, question, input_type) and optionally
                an ``answer`` key from solve_captcha().
            elements: Extracted DOM elements from the current page.

        Returns:
            CaptchaActionPlan with ordered actions.
        """
        elements_json = json.dumps(
            [
                {
                    "eid": e.eid,
                    "type": e.type,
                    "text": (e.text or "")[:80],
                    **({"role": e.role} if e.role else {}),
                }
                for e in elements
                if e.visible
            ][:50],
            ensure_ascii=False,
            separators=(",", ":"),
        )

        prompt = self.prompt_manager.get_prompt(
            "captcha_action",
            captcha_type=captcha_info.get("captcha_type", "unknown"),
            image_description=captcha_info.get("image_description", ""),
            question=captcha_info.get("question", ""),
            answer=captcha_info.get("answer", ""),
            input_type=captcha_info.get("input_type", ""),
            elements=elements_json,
        )

        response_text, tokens = await self._call_gemini(prompt, self.tier1_model)
        self.usage.record(self.tier1_model, tokens)

        try:
            cleaned = _extract_json(response_text)
            data = json.loads(cleaned)
            actions: list[CaptchaAction] = []
            for a in data.get("actions", []):
                actions.append(CaptchaAction(
                    action=a.get("action", "click"),
                    target=a.get("target", a.get("target_eid", "")),
                    value=a.get("value", ""),
                    description=a.get("description", ""),
                ))
            return CaptchaActionPlan(
                actions=actions,
                needs_iframe=data.get("needs_iframe", False),
                reasoning=data.get("reasoning", ""),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Failed to parse captcha action plan: %s", exc)
            return CaptchaActionPlan(actions=[], reasoning=f"parse error: {exc}")

    async def extract_structured_data(
        self, elements: list[ExtractedElement], data_type: str
    ) -> list[dict[str, Any]]:
        """Extract structured data from DOM elements using LLM.

        Used as fallback when Schema.org markup is not available.
        The LLM inspects element text/structure and returns structured items.

        Args:
            elements: List of extracted DOM elements from the page.
            data_type: Type of data to extract (e.g. "product", "article").

        Returns:
            List of dicts with extracted fields (varies by data_type).
        """
        elements_json = json.dumps(
            [
                {
                    "eid": e.eid,
                    "type": e.type,
                    "text": (e.text or "")[:120],
                    **({"parent_context": e.parent_context} if e.parent_context else {}),
                }
                for e in elements
                if e.visible and e.text
            ][:80],
            ensure_ascii=False,
            separators=(",", ":"),
        )

        prompt = self.prompt_manager.get_prompt(
            "extract_products",
            elements=elements_json,
            data_type=data_type,
        )

        response_text, tokens = await self._call_gemini(prompt, self.tier1_model)
        self.usage.record(self.tier1_model, tokens)

        try:
            cleaned = _extract_json(response_text)
            data = json.loads(cleaned)
            if isinstance(data, dict):
                data = data.get("items", data.get("products", []))
            if not isinstance(data, list):
                return []
            return [item for item in data if isinstance(item, dict)]
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.warning("Failed to parse extract_structured_data response")
            return []

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

    @trace(name="gemini-api-call", as_type="generation")
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
        # Use provider if available (non-multimodal path)
        if self._provider is not None and not images:
            text = await self._provider.generate(prompt)
            tokens_used = (len(prompt) + len(text)) // 4
            return text, tokens_used

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
        update_current_observation(
            model=model,
            usage_details={"input": tokens_used // 2, "output": tokens_used // 2},
            metadata={"multimodal": bool(images)},
        )
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

            # For click/type actions, always clear the selector.
            # The prompt says "selector: null" but LLMs often ignore this
            # and guess CSS selectors that fail on real pages.
            # The orchestrator finds elements from live DOM via LLM select.
            raw_selector = s.get("selector")
            if node_type in ("click", "type") and raw_selector:
                raw_selector = None

            step = StepDefinition(
                step_id=step_id,
                intent=intent,
                node_type=node_type,
                selector=raw_selector,
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
    provider: ILLMProvider | None = None,
) -> LLMPlanner:
    """Create an ``LLMPlanner`` with default configuration.

    Args:
        api_key: Gemini API key. Falls back to ``GEMINI_API_KEY`` env var.
        max_cost_usd: Maximum total cost before skipping Tier2 escalation.
        provider: Optional LLM provider instance for multi-provider support.

    Returns:
        Configured ``LLMPlanner`` instance.
    """
    prompt_manager = PromptManager()
    return LLMPlanner(
        prompt_manager=prompt_manager,
        api_key=api_key,
        max_cost_usd=max_cost_usd,
        provider=provider,
    )
