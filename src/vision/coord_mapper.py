"""Coordinate Reverse Mapping — Map detection coordinates back to page coordinates.

Token cost: 0 (pure computation, no API calls).

Maps coordinates from screenshot/YOLO space back to actual page coordinates,
accounting for viewport size differences and scroll offset. Also provides
nearest-element lookup by Euclidean distance.
"""
from __future__ import annotations

import math
from typing import Any

from src.core.types import ExtractedElement
from src.vision.yolo_detector import Detection


class CoordMapper:
    """Maps coordinates between screenshot space and page coordinate space.

    Screenshots may be at a different resolution than the actual page viewport.
    This mapper handles the scaling and offset translation between these spaces.

    Example::

        mapper = CoordMapper(viewport_size=(1920, 1080))
        page_center = mapper.map_detection_to_page(detection, screenshot_size=(1024, 768))
        page_bbox = mapper.map_bbox_to_page(bbox, screenshot_size=(1024, 768))
        nearest = mapper.find_closest_element(point, candidates)

    Args:
        viewport_size: Page viewport size as (width, height).
    """

    def __init__(self, viewport_size: tuple[int, int] = (1920, 1080)) -> None:
        self._viewport_size = viewport_size
        self._scroll_offset: tuple[int, int] = (0, 0)

    @property
    def viewport_size(self) -> tuple[int, int]:
        """Current viewport size (width, height)."""
        return self._viewport_size

    @viewport_size.setter
    def viewport_size(self, value: tuple[int, int]) -> None:
        """Set the viewport size.

        Args:
            value: New viewport size as (width, height).
        """
        self._viewport_size = value

    @property
    def scroll_offset(self) -> tuple[int, int]:
        """Current scroll offset (x, y)."""
        return self._scroll_offset

    @scroll_offset.setter
    def scroll_offset(self, value: tuple[int, int]) -> None:
        """Set the scroll offset.

        Args:
            value: Scroll offset as (x, y) in page coordinates.
        """
        self._scroll_offset = value

    def _scale_factors(
        self, screenshot_size: tuple[int, int]
    ) -> tuple[float, float]:
        """Calculate scaling factors from screenshot to viewport.

        Args:
            screenshot_size: Screenshot dimensions (width, height).

        Returns:
            Tuple of (scale_x, scale_y) factors.
        """
        vp_w, vp_h = self._viewport_size
        ss_w, ss_h = screenshot_size

        scale_x = vp_w / ss_w if ss_w > 0 else 1.0
        scale_y = vp_h / ss_h if ss_h > 0 else 1.0

        return scale_x, scale_y

    def map_detection_to_page(
        self,
        detection: Detection,
        screenshot_size: tuple[int, int],
    ) -> tuple[int, int]:
        """Map a detection's center point to page coordinates.

        Calculates the center of the detection's bounding box, scales it
        to viewport coordinates, and applies the scroll offset.

        Args:
            detection: The YOLO detection to map.
            screenshot_size: Size of the screenshot (width, height) in which
                the detection was found.

        Returns:
            Center point (x, y) in page coordinates.
        """
        x, y, w, h = detection.bbox
        center_ss_x = x + w / 2
        center_ss_y = y + h / 2

        scale_x, scale_y = self._scale_factors(screenshot_size)

        page_x = int(center_ss_x * scale_x) + self._scroll_offset[0]
        page_y = int(center_ss_y * scale_y) + self._scroll_offset[1]

        return page_x, page_y

    def map_bbox_to_page(
        self,
        bbox: tuple[int, int, int, int],
        screenshot_size: tuple[int, int],
    ) -> tuple[int, int, int, int]:
        """Map a bounding box from screenshot space to page coordinates.

        Scales the bounding box dimensions and applies scroll offset
        to the position.

        Args:
            bbox: Bounding box as (x, y, width, height) in screenshot space.
            screenshot_size: Size of the screenshot (width, height).

        Returns:
            Scaled bounding box (x, y, width, height) in page coordinates.
        """
        x, y, w, h = bbox
        scale_x, scale_y = self._scale_factors(screenshot_size)

        page_x = int(x * scale_x) + self._scroll_offset[0]
        page_y = int(y * scale_y) + self._scroll_offset[1]
        page_w = int(w * scale_x)
        page_h = int(h * scale_y)

        return page_x, page_y, page_w, page_h

    def find_closest_element(
        self,
        point: tuple[int, int],
        candidates: list[ExtractedElement],
    ) -> ExtractedElement | None:
        """Find the closest candidate element to a point by Euclidean distance.

        Computes the distance from the given point to the center of each
        candidate's bounding box and returns the nearest one.

        Args:
            point: Target point (x, y) in page coordinates.
            candidates: List of candidate elements with bounding boxes.

        Returns:
            The nearest ``ExtractedElement``, or None if candidates is empty.
        """
        if not candidates:
            return None

        px, py = point
        best: ExtractedElement | None = None
        best_dist = float("inf")

        for candidate in candidates:
            cx, cy, cw, ch = candidate.bbox
            center_x = cx + cw / 2
            center_y = cy + ch / 2

            dist = math.sqrt((px - center_x) ** 2 + (py - center_y) ** 2)
            if dist < best_dist:
                best_dist = dist
                best = candidate

        return best


# ── Factory ─────────────────────────────────────────


def create_coord_mapper(
    viewport_size: tuple[int, int] = (1920, 1080),
) -> CoordMapper:
    """Create and return a new ``CoordMapper`` instance.

    Args:
        viewport_size: Page viewport size as (width, height).

    Returns:
        A configured ``CoordMapper``.
    """
    return CoordMapper(viewport_size=viewport_size)
