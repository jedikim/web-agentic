"""VLM API Client — Gemini multimodal vision for element selection and page analysis.

Token cost: Variable (tier-1 Gemini Flash is cheap, tier-2 Gemini Pro is expensive).

The VLM client provides three capabilities:
1. **select_element** — Given a screenshot and candidate elements, select the best match.
2. **describe_page** — Describe what's visible on a screenshot.
3. **find_element** — Locate a described element on a screenshot, returning coordinates.

Tier escalation: If tier-1 confidence < 0.7, automatically retry with tier-2 model.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from src.core.types import ExtractedElement, PatchData
from src.vision.yolo_detector import Detection

logger = logging.getLogger(__name__)


# ── Cost Tracking ───────────────────────────────────


@dataclass
class UsageStats:
    """Tracks VLM API token usage and cost.

    Attributes:
        total_input_tokens: Total input tokens consumed.
        total_output_tokens: Total output tokens consumed.
        total_calls: Total API calls made.
        tier1_calls: Calls made with tier-1 model.
        tier2_calls: Calls made with tier-2 model.
        estimated_cost_usd: Estimated total cost in USD.
    """

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_calls: int = 0
    tier1_calls: int = 0
    tier2_calls: int = 0
    estimated_cost_usd: float = 0.0


# Approximate pricing per million tokens (input/output) for cost estimation.
_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro-preview-06-05": {"input": 1.25, "output": 10.0},
}

# Default pricing for unknown models.
_DEFAULT_PRICING = {"input": 1.0, "output": 5.0}


# ── VLMClient ───────────────────────────────────────


class VLMClient:
    """Gemini multimodal VLM client for vision-based element interaction.

    Provides element selection, page description, and element location using
    Gemini's image+text capabilities. Implements tier escalation: if the
    tier-1 model returns low confidence, the tier-2 model is consulted.

    Example::

        client = VLMClient(api_key="your-key")
        patch = await client.select_element(screenshot, candidates, "click login button")
        description = await client.describe_page(screenshot)
        detection = await client.find_element(screenshot, "the blue Submit button")

    Args:
        api_key: Gemini API key. Reads from GOOGLE_API_KEY env var if None.
        tier1_model: Model name for tier-1 (fast/cheap) calls.
        tier2_model: Model name for tier-2 (accurate/expensive) calls.
    """

    # Confidence threshold below which we escalate to tier-2.
    TIER_ESCALATION_THRESHOLD = 0.7

    def __init__(
        self,
        api_key: str | None = None,
        tier1_model: str = "gemini-2.0-flash",
        tier2_model: str = "gemini-2.5-pro-preview-06-05",
    ) -> None:
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        self._tier1_model = tier1_model
        self._tier2_model = tier2_model
        self._stats = UsageStats()

    @property
    def stats(self) -> UsageStats:
        """Return current usage statistics."""
        return self._stats

    def _call_gemini_vision(
        self,
        model_name: str,
        image_bytes: bytes,
        prompt: str,
    ) -> dict[str, Any]:
        """Make a Gemini multimodal API call with image + text.

        This method is separated for testability — tests can patch it to
        return fake responses without making real API calls.

        Args:
            model_name: Gemini model name to use.
            image_bytes: Screenshot image bytes.
            prompt: Text prompt to send alongside the image.

        Returns:
            Dictionary with keys: text (response text), input_tokens, output_tokens.

        Raises:
            RuntimeError: If the API call fails.
        """
        import google.generativeai as genai
        from PIL import Image
        import io

        if not self._api_key:
            raise RuntimeError(
                "Gemini API key not configured. Set GOOGLE_API_KEY environment variable "
                "or pass api_key to VLMClient constructor."
            )

        genai.configure(api_key=self._api_key)
        model = genai.GenerativeModel(model_name)

        image = Image.open(io.BytesIO(image_bytes))
        response = model.generate_content([prompt, image])

        # Extract token usage.
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0)
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0)

        return {
            "text": response.text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    def _update_stats(self, model_name: str, response: dict[str, Any]) -> None:
        """Update usage statistics from an API response.

        Args:
            model_name: The model used for the call.
            response: The API response dict with token counts.
        """
        input_tokens = response.get("input_tokens", 0)
        output_tokens = response.get("output_tokens", 0)

        self._stats.total_input_tokens += input_tokens
        self._stats.total_output_tokens += output_tokens
        self._stats.total_calls += 1

        if model_name == self._tier1_model:
            self._stats.tier1_calls += 1
        else:
            self._stats.tier2_calls += 1

        # Estimate cost.
        pricing = _PRICING.get(model_name, _DEFAULT_PRICING)
        cost = (
            (input_tokens / 1_000_000) * pricing["input"]
            + (output_tokens / 1_000_000) * pricing["output"]
        )
        self._stats.estimated_cost_usd += cost

    async def select_element(
        self,
        screenshot: bytes,
        candidates: list[ExtractedElement],
        intent: str,
    ) -> PatchData:
        """Select the best matching element from candidates using VLM.

        Sends the screenshot with numbered candidate overlays to Gemini and
        asks it to select the best match for the given intent.

        Args:
            screenshot: Screenshot image bytes (ideally with annotated candidates).
            candidates: List of candidate elements to choose from.
            intent: The user's intent description (e.g., "click the login button").

        Returns:
            A ``PatchData`` with the selected element's selector and confidence.
        """
        # Build candidate list for the prompt.
        candidate_text = "\n".join(
            f"  [{i}] type={c.type}, text='{c.text or ''}', eid='{c.eid}', bbox={c.bbox}"
            for i, c in enumerate(candidates)
        )

        prompt = (
            f"You are an element selector for web automation.\n"
            f"Intent: {intent}\n\n"
            f"Candidates:\n{candidate_text}\n\n"
            f"Which numbered candidate best matches the intent?\n"
            f"Respond with JSON: {{\"index\": <number>, \"confidence\": <0.0-1.0>, "
            f"\"reason\": \"<brief reason>\"}}"
        )

        # Tier-1 call.
        response = self._call_gemini_vision(self._tier1_model, screenshot, prompt)
        self._update_stats(self._tier1_model, response)

        parsed = self._parse_selection_response(response["text"], candidates)

        # Tier escalation if confidence is low.
        if parsed["confidence"] < self.TIER_ESCALATION_THRESHOLD:
            logger.info(
                "Tier-1 confidence %.2f < %.2f, escalating to tier-2",
                parsed["confidence"],
                self.TIER_ESCALATION_THRESHOLD,
            )
            response2 = self._call_gemini_vision(self._tier2_model, screenshot, prompt)
            self._update_stats(self._tier2_model, response2)
            parsed = self._parse_selection_response(response2["text"], candidates)

        selected_idx = parsed["index"]
        selected = candidates[selected_idx] if 0 <= selected_idx < len(candidates) else candidates[0]

        return PatchData(
            patch_type="selector_fix",
            target=selected.eid,
            data={
                "selector": selected.eid,
                "element_type": selected.type,
                "text": selected.text,
                "bbox": selected.bbox,
                "reason": parsed.get("reason", ""),
            },
            confidence=parsed["confidence"],
        )

    async def analyze_captcha(self, screenshot: bytes) -> dict[str, Any]:
        """Analyze a CAPTCHA screenshot using VLM.

        Describes the CAPTCHA type, content, and question so that
        a text-only LLM can solve it.

        Args:
            screenshot: Screenshot image bytes showing the CAPTCHA.

        Returns:
            Dict with captcha_type, question, image_description, and raw_text.
        """
        prompt = (
            "You are analyzing a CAPTCHA security challenge on a web page.\n\n"
            "Describe in detail:\n"
            "1. What type of CAPTCHA is this? (text recognition, image selection, "
            "math problem, question about image, slider, etc.)\n"
            "2. What does the CAPTCHA image show? Describe ALL text, numbers, "
            "and visual details you can see in the image.\n"
            "3. What is the exact question or instruction being asked?\n"
            "4. What input is expected? (text field, checkbox, drag, etc.)\n\n"
            "Respond with JSON:\n"
            '{"captcha_type": "question_about_image", '
            '"image_description": "detailed description of what the image shows", '
            '"question": "the exact question text", '
            '"input_type": "text"}\n\n'
            "Be VERY precise about numbers, text, and details in the image — "
            "the answer depends on accurate reading."
        )

        response = self._call_gemini_vision(self._tier1_model, screenshot, prompt)
        self._update_stats(self._tier1_model, response)

        try:
            json_match = re.search(r"\{[^}]+\}", response["text"], re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "captcha_type": str(data.get("captcha_type", "unknown")),
                    "image_description": str(data.get("image_description", "")),
                    "question": str(data.get("question", "")),
                    "input_type": str(data.get("input_type", "text")),
                    "raw_text": response["text"],
                }
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "captcha_type": "unknown",
            "image_description": "",
            "question": "",
            "input_type": "text",
            "raw_text": response["text"],
        }

    async def describe_page(self, screenshot: bytes) -> str:
        """Describe what's visible on a screenshot.

        Args:
            screenshot: Screenshot image bytes.

        Returns:
            A text description of the page contents.
        """
        prompt = (
            "Describe the web page shown in this screenshot. Include:\n"
            "1. Page type (login, search results, product page, etc.)\n"
            "2. Key interactive elements visible (buttons, inputs, links)\n"
            "3. Any modals, popups, or overlays\n"
            "4. Overall layout description\n"
            "Keep the description concise (2-4 sentences)."
        )

        response = self._call_gemini_vision(self._tier1_model, screenshot, prompt)
        self._update_stats(self._tier1_model, response)

        return response["text"]

    async def find_element(
        self,
        screenshot: bytes,
        description: str,
    ) -> Detection | None:
        """Find an element on a screenshot by description.

        Asks the VLM to locate a described element and return its bounding box.

        Args:
            screenshot: Screenshot image bytes.
            description: Natural language description of the element to find.

        Returns:
            A ``Detection`` object with the element's location, or None if not found.
        """
        prompt = (
            f"Find the element matching this description on the screenshot: '{description}'\n\n"
            f"If found, respond with JSON: {{\"found\": true, \"label\": \"<element type>\", "
            f"\"confidence\": <0.0-1.0>, \"bbox\": [x, y, width, height]}}\n"
            f"If not found, respond with: {{\"found\": false}}\n"
            f"Coordinates should be in pixels relative to the screenshot."
        )

        # Tier-1 call.
        response = self._call_gemini_vision(self._tier1_model, screenshot, prompt)
        self._update_stats(self._tier1_model, response)

        parsed = self._parse_find_response(response["text"])

        # Tier escalation if found but low confidence.
        if (
            parsed is not None
            and parsed["confidence"] < self.TIER_ESCALATION_THRESHOLD
        ):
            logger.info(
                "Tier-1 find confidence %.2f < %.2f, escalating to tier-2",
                parsed["confidence"],
                self.TIER_ESCALATION_THRESHOLD,
            )
            response2 = self._call_gemini_vision(self._tier2_model, screenshot, prompt)
            self._update_stats(self._tier2_model, response2)
            parsed = self._parse_find_response(response2["text"])

        if parsed is None:
            return None

        bbox = parsed["bbox"]
        return Detection(
            label=parsed["label"],
            confidence=parsed["confidence"],
            bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
            class_id=0,
        )

    # ── Private Helpers ─────────────────────────────

    def _parse_selection_response(
        self,
        text: str,
        candidates: list[ExtractedElement],
    ) -> dict[str, Any]:
        """Parse the VLM selection response into structured data.

        Args:
            text: Raw response text from VLM.
            candidates: Candidate list (for bounds checking).

        Returns:
            Dict with index, confidence, and reason.
        """
        try:
            # Try to extract JSON from the response.
            json_match = re.search(r"\{[^}]+\}", text)
            if json_match:
                data = json.loads(json_match.group())
                index = int(data.get("index", 0))
                confidence = float(data.get("confidence", 0.5))
                reason = str(data.get("reason", ""))
                # Bounds check.
                if index < 0 or index >= len(candidates):
                    index = 0
                return {"index": index, "confidence": confidence, "reason": reason}
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # Fallback: try to find a number in the response.
        numbers = re.findall(r"\d+", text)
        if numbers:
            index = int(numbers[0])
            if 0 <= index < len(candidates):
                return {"index": index, "confidence": 0.5, "reason": "parsed from text"}

        return {"index": 0, "confidence": 0.3, "reason": "fallback"}

    def _parse_find_response(self, text: str) -> dict[str, Any] | None:
        """Parse the VLM find_element response.

        Args:
            text: Raw response text from VLM.

        Returns:
            Dict with label, confidence, and bbox, or None if not found.
        """
        try:
            json_match = re.search(r"\{[^}]+\}", text)
            if json_match:
                data = json.loads(json_match.group())
                if not data.get("found", False):
                    return None
                return {
                    "label": str(data.get("label", "unknown")),
                    "confidence": float(data.get("confidence", 0.5)),
                    "bbox": list(data.get("bbox", [0, 0, 0, 0])),
                }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        return None


# ── Factory ─────────────────────────────────────────


def create_vlm_client(
    api_key: str | None = None,
    tier1_model: str = "gemini-2.0-flash",
    tier2_model: str = "gemini-2.5-pro-preview-06-05",
) -> VLMClient:
    """Create and return a new ``VLMClient`` instance.

    Args:
        api_key: Gemini API key. Reads from GOOGLE_API_KEY env var if None.
        tier1_model: Model name for tier-1 calls.
        tier2_model: Model name for tier-2 calls.

    Returns:
        A configured ``VLMClient``.
    """
    return VLMClient(
        api_key=api_key,
        tier1_model=tier1_model,
        tier2_model=tier2_model,
    )
