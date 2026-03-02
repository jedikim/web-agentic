"""Visual Scanner — Stage 2 of site reconnaissance.

Uses local object detection (YOLO26/RT-DETR) + optional VLM
to supplement DOM-based analysis with visual structure info.
"""

from __future__ import annotations

import io
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class DetectorLike(Protocol):
    """Local object detector interface."""

    def detect(self, image: Any, threshold: float = 0.3) -> list[dict[str, Any]]: ...


class VLMLike(Protocol):
    """VLM interface for visual analysis."""

    async def generate(self, *, image: Any, prompt: str) -> str: ...


class BrowserLike(Protocol):
    """Minimal browser interface for screenshots."""

    async def screenshot(self) -> bytes: ...


class VisualScanner:
    """Supplement DOM recon with visual analysis.

    Stage 2 of 3-stage recon. Cost: $0 (detector only) or ~$0.003 (+ VLM).
    VLM is only called when Canvas or high image density is detected.
    """

    async def scan(
        self,
        browser: BrowserLike,
        dom_result: dict[str, Any],
        detector: DetectorLike | None = None,
        vlm: VLMLike | None = None,
    ) -> dict[str, Any]:
        """Run visual scan.

        Args:
            browser: Browser for screenshots.
            dom_result: Results from DOM scanner.
            detector: Local object detector (YOLO26/RT-DETR).
            vlm: Vision LLM client.

        Returns:
            Dict with visual analysis results.
        """
        screenshot_bytes = await browser.screenshot()

        # Object detection (local, $0)
        visual_elements: list[dict[str, Any]] = []
        if detector is not None:
            try:
                from PIL import Image

                image = Image.open(io.BytesIO(screenshot_bytes))
                detections = detector.detect(image, threshold=0.3)
                visual_elements = self._classify_detections(detections)
            except Exception as e:
                logger.warning("Object detection failed: %s", e)

        # VLM call decision
        needs_vlm = (
            dom_result.get("canvas_count", 0) > 0
            or dom_result.get("image_density") == "high"
            or dom_result.get("total_elements", 0) < 50
        )

        vlm_analysis: str | None = None
        if needs_vlm and vlm is not None:
            try:
                from PIL import Image

                image = Image.open(io.BytesIO(screenshot_bytes))
                vlm_analysis = await vlm.generate(
                    image=image,
                    prompt=(
                        "Analyze the visual structure of this web page:\n"
                        "1. Overall layout (header, sidebar, main, footer)\n"
                        "2. Menu structure (position, depth)\n"
                        "3. Canvas or image-only content areas\n"
                        "4. Thumbnail/card grid structures\n"
                        "5. Popup or overlay positions\n"
                        "Respond in JSON."
                    ),
                )
            except Exception as e:
                logger.warning("VLM analysis failed: %s", e)

        return {
            "obj_detections": visual_elements,
            "vlm_analysis": vlm_analysis,
            "needs_vlm": needs_vlm,
            "screenshot_bytes": screenshot_bytes,
        }

    @staticmethod
    def _classify_detections(
        detections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Classify raw detections into UI element categories."""
        classified: list[dict[str, Any]] = []
        for det in detections:
            label = str(det.get("label", "")).lower()
            category = "unknown"
            if "button" in label or "btn" in label:
                category = "button"
            elif "menu" in label or "nav" in label:
                category = "menu"
            elif "input" in label or "text" in label or "field" in label:
                category = "input"
            elif "card" in label or "product" in label or "item" in label:
                category = "card"
            elif "image" in label or "img" in label:
                category = "image"
            classified.append({
                "category": category,
                "label": det.get("label", ""),
                "confidence": det.get("confidence", 0.0),
                "bbox": det.get("bbox", []),
            })
        return classified
