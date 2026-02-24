"""YOLO Local Inference — Vision-based element detection using YOLO models.

Token cost: 0 (local inference, no API calls).

The YOLO detector provides a fast, local fallback for element detection when
text-based approaches fail (VisualAmbiguity). It wraps the ultralytics YOLO
model and maps raw detections to ``ExtractedElement`` objects.

Key features:
- Lazy model loading (loaded on first detect call).
- Confidence-based filtering.
- Element type filtering (button, input, link, etc.).
- Mockable ``_run_inference()`` for testing without a real model.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any

from src.core.types import ExtractedElement

logger = logging.getLogger(__name__)


# ── Detection Dataclass ─────────────────────────────


@dataclass(frozen=True)
class Detection:
    """A single YOLO detection result.

    Attributes:
        label: Class label name (e.g., "button", "text", "image").
        confidence: Detection confidence score (0.0-1.0).
        bbox: Bounding box as (x, y, width, height) in pixels.
        class_id: YOLO class ID.
    """

    label: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x, y, width, height
    class_id: int


# ── Label-to-ElementType Mapping ────────────────────

_LABEL_TO_TYPE: dict[str, str] = {
    "person": "image",
    "car": "image",
    "dog": "image",
    "cat": "image",
    "cell phone": "button",
    "laptop": "image",
    "tv": "image",
    "mouse": "button",
    "keyboard": "input",
    "remote": "button",
    "book": "link",
    "clock": "icon",
    "button": "button",
    "input": "input",
    "link": "link",
    "text": "button",
    "image": "image",
    "icon": "icon",
    "checkbox": "input",
    "radio": "input",
    "dropdown": "input",
    "tab": "tab",
    "card": "card",
}

# Default element type for unmapped labels.
_DEFAULT_ELEMENT_TYPE = "button"


# ── YOLODetector ────────────────────────────────────


class YOLODetector:
    """YOLO-based element detector for screenshot analysis.

    Uses ultralytics YOLO model for local inference. The model is lazily loaded
    on the first ``detect()`` call to minimize startup time and memory usage.

    Example::

        detector = create_yolo_detector()
        detections = await detector.detect(screenshot_bytes)
        elements = await detector.detect_elements(screenshot_bytes, element_types=["button"])

    Args:
        model_path: Path to the YOLO model weights file.
        confidence_threshold: Minimum confidence score to include a detection.
    """

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        confidence_threshold: float = 0.5,
    ) -> None:
        self._model_path = model_path
        self._confidence_threshold = confidence_threshold
        self._model: Any = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        """Whether the YOLO model has been loaded."""
        return self._loaded

    def _load_model(self) -> None:
        """Load the YOLO model from disk.

        Raises:
            ImportError: If ultralytics is not installed.
        """
        try:
            from ultralytics import YOLO
        except ImportError:
            raise ImportError(
                "ultralytics is required for YOLO detection. "
                "Install it with: pip install 'web-agentic[vision]' "
                "or: pip install ultralytics>=8.2"
            )
        self._model = YOLO(self._model_path)
        self._loaded = True
        logger.info("YOLO model loaded from %s", self._model_path)

    def _run_inference(self, image_bytes: bytes) -> list[dict[str, Any]]:
        """Run YOLO inference on image bytes.

        This method is separated for testability — tests can patch it to
        return fake detection results without loading a real YOLO model.

        Args:
            image_bytes: Raw PNG/JPEG image bytes.

        Returns:
            List of detection dicts with keys: label, confidence, bbox, class_id.
        """
        if not self._loaded:
            self._load_model()

        # Convert bytes to PIL Image for YOLO.
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes))

        results = self._model(image, verbose=False)
        detections: list[dict[str, Any]] = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for i in range(len(boxes)):
                xyxy = boxes.xyxy[i].tolist()
                x1, y1, x2, y2 = xyxy
                w = int(x2 - x1)
                h = int(y2 - y1)
                conf = float(boxes.conf[i])
                cls_id = int(boxes.cls[i])
                label = result.names.get(cls_id, f"class_{cls_id}")
                detections.append(
                    {
                        "label": label,
                        "confidence": conf,
                        "bbox": (int(x1), int(y1), w, h),
                        "class_id": cls_id,
                    }
                )

        return detections

    async def detect(self, screenshot: bytes) -> list[Detection]:
        """Run YOLO detection on a screenshot.

        Args:
            screenshot: Raw screenshot image bytes (PNG or JPEG).

        Returns:
            List of ``Detection`` objects above the confidence threshold,
            sorted by confidence (highest first).
        """
        if not screenshot:
            return []

        raw_detections = self._run_inference(screenshot)

        detections: list[Detection] = []
        for d in raw_detections:
            if d["confidence"] >= self._confidence_threshold:
                detections.append(
                    Detection(
                        label=d["label"],
                        confidence=d["confidence"],
                        bbox=d["bbox"],
                        class_id=d["class_id"],
                    )
                )

        # Sort by confidence descending.
        detections.sort(key=lambda det: det.confidence, reverse=True)
        return detections

    async def detect_elements(
        self,
        screenshot: bytes,
        element_types: list[str] | None = None,
    ) -> list[ExtractedElement]:
        """Detect elements and convert to ``ExtractedElement`` objects.

        Maps YOLO detection labels to element types using the label-to-type
        mapping table. Optionally filters by element type.

        Args:
            screenshot: Raw screenshot image bytes.
            element_types: Optional list of element types to include
                (e.g., ["button", "input"]). If None, all types are included.

        Returns:
            List of ``ExtractedElement`` objects.
        """
        detections = await self.detect(screenshot)

        elements: list[ExtractedElement] = []
        for i, det in enumerate(detections):
            elem_type = _LABEL_TO_TYPE.get(det.label, _DEFAULT_ELEMENT_TYPE)

            # Filter by requested element types.
            if element_types is not None and elem_type not in element_types:
                continue

            elements.append(
                ExtractedElement(
                    eid=f"yolo-{i}-{det.label}",
                    type=elem_type,
                    text=det.label,
                    role=None,
                    bbox=det.bbox,
                    visible=True,
                    parent_context="yolo_detection",
                )
            )

        return elements


# ── Factory ─────────────────────────────────────────


def create_yolo_detector(
    model_path: str | None = None,
    confidence_threshold: float = 0.5,
) -> YOLODetector:
    """Create and return a new ``YOLODetector`` instance.

    Args:
        model_path: Path to YOLO model weights. Defaults to "yolo11n.pt".
        confidence_threshold: Minimum confidence threshold.

    Returns:
        A configured ``YOLODetector``.
    """
    return YOLODetector(
        model_path=model_path or "yolo11n.pt",
        confidence_threshold=confidence_threshold,
    )
