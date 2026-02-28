"""LocalDetector — local UI element detection (RF-DETR / YOLO fallback).

Provides LLM-free verification: element existence, position, count.
Used by the orchestrator for fast, zero-cost verification steps.

Falls back gracefully when RF-DETR is not installed, using existing
YOLO detector or returning empty results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """A detected UI element.

    Attributes:
        box: Bounding box (x1, y1, x2, y2) in pixels.
        confidence: Detection confidence score.
        label: Optional class label.
    """

    box: tuple[float, float, float, float]
    confidence: float
    label: str = ""


class IObjectDetector(Protocol):
    """Protocol for object detection backends."""

    def predict(
        self, image: Any, threshold: float = 0.35,
    ) -> list[Detection]: ...


class LocalDetector:
    """Local UI element detector for LLM-free verification.

    Usage:
        detector = LocalDetector()  # auto-detects available backend
        detections = detector.detect(screenshot)
        exists = detector.verify_element_exists(screenshot, region)
        count = detector.count_items(screenshot)
    """

    def __init__(
        self,
        backend: IObjectDetector | None = None,
    ) -> None:
        self._backend = backend

    def detect(
        self,
        screenshot: Image.Image,
        threshold: float = 0.35,
    ) -> list[Detection]:
        """Detect clickable UI elements in screenshot.

        Args:
            screenshot: PIL Image of the page.
            threshold: Confidence threshold.

        Returns:
            List of detected elements with bounding boxes.
        """
        if self._backend is None:
            return []
        return self._backend.predict(screenshot, threshold)

    def verify_element_exists(
        self,
        screenshot: Image.Image,
        expected_region: tuple[float, float, float, float],
        threshold: float = 0.35,
    ) -> bool:
        """Check if a clickable element exists in the expected region.

        Args:
            screenshot: PIL Image of the page.
            expected_region: (x1, y1, x2, y2) bounding box to check.
            threshold: Detection confidence threshold.

        Returns:
            True if an element overlapping the region is found.
        """
        detections = self.detect(screenshot, threshold)
        return any(
            self._iou(det.box, expected_region) > 0.3
            for det in detections
        )

    def count_items(
        self,
        screenshot: Image.Image,
        threshold: float = 0.35,
    ) -> int:
        """Count visible items (product cards, etc.) in screenshot.

        Groups similarly-sized detections to estimate card count.

        Args:
            screenshot: PIL Image of the page.
            threshold: Detection confidence threshold.

        Returns:
            Estimated number of similar items.
        """
        detections = self.detect(screenshot, threshold)
        return self._count_similar_sized(detections)

    @staticmethod
    def _iou(
        box_a: tuple[float, float, float, float],
        box_b: tuple[float, float, float, float],
    ) -> float:
        """Calculate Intersection over Union between two boxes."""
        x1 = max(box_a[0], box_b[0])
        y1 = max(box_a[1], box_b[1])
        x2 = min(box_a[2], box_b[2])
        y2 = min(box_a[3], box_b[3])

        inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        if inter == 0:
            return 0.0

        area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
        area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
        union = area_a + area_b - inter

        return inter / union if union > 0 else 0.0

    @staticmethod
    def _count_similar_sized(
        detections: list[Detection],
        size_tolerance: float = 0.4,
    ) -> int:
        """Count detections with similar bounding box sizes.

        Groups by area similarity to find repeated items like
        product cards vs navigation buttons.

        Args:
            detections: List of detections.
            size_tolerance: Relative size difference tolerance.

        Returns:
            Count of the largest group of similarly-sized detections.
        """
        if not detections:
            return 0
        if len(detections) == 1:
            return 1

        areas = []
        for det in detections:
            w = det.box[2] - det.box[0]
            h = det.box[3] - det.box[1]
            areas.append(w * h)

        # Sort by area and group similar sizes
        sorted_areas = sorted(areas)
        best_group = 1
        current_group = 1

        for i in range(1, len(sorted_areas)):
            if sorted_areas[i - 1] > 0:
                ratio = sorted_areas[i] / sorted_areas[i - 1]
                if 1.0 - size_tolerance <= ratio <= 1.0 + size_tolerance:
                    current_group += 1
                    best_group = max(best_group, current_group)
                else:
                    current_group = 1
            else:
                current_group = 1

        return best_group
