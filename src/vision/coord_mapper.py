"""Coordinate Reverse Mapping — Map detection coordinates back to page coordinates.

Token cost: 0 (pure computation, no API calls).

Maps coordinates from screenshot/YOLO space back to actual page coordinates,
accounting for viewport size differences and scroll offset. Also provides
nearest-element lookup by Euclidean distance.
"""
from __future__ import annotations

import math

from src.core.types import ExtractedElement
from src.vision.image_batcher import CellInfo, GridMetadata
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

    def map_grid_detection_to_page(
        self,
        detection_bbox: tuple[int, int, int, int],
        grid_metadata: GridMetadata,
        screenshot_size: tuple[int, int],
    ) -> tuple[int, tuple[int, int, int, int]]:
        """Map a detection in grid-image space to a page-coordinate bbox.

        Steps:
        1. Determine which cell the detection centre falls into.
        2. Compute the detection's position relative to that cell.
        3. Scale the relative position into the cell's *source_bbox*.
        4. Apply viewport scaling and scroll offset.

        Args:
            detection_bbox: (x, y, w, h) of the detection in grid-image pixels.
            grid_metadata: Metadata from :meth:`ImageBatcher.create_grid_with_metadata`.
            screenshot_size: Size (w, h) of the original screenshot from which
                the grid items were cropped.

        Returns:
            A tuple of ``(cell_index, page_bbox)`` where *page_bbox* is
            ``(x, y, w, h)`` in page coordinates.

        Raises:
            ValueError: If the detection centre does not fall within any cell.
        """
        dx, dy, dw, dh = detection_bbox
        cx = dx + dw / 2
        cy = dy + dh / 2

        # Find the owning cell.
        cell = self._find_cell_for_point(cx, cy, grid_metadata)

        # Relative position inside the cell.
        gox, goy = cell.grid_offset
        cw, ch = cell.cell_size

        rel_x = (dx - gox) / cw if cw > 0 else 0.0
        rel_y = (dy - goy) / ch if ch > 0 else 0.0
        rel_w = dw / cw if cw > 0 else 0.0
        rel_h = dh / ch if ch > 0 else 0.0

        # Map to source bbox.
        sx, sy, sw, sh = cell.source_bbox
        src_x = sx + rel_x * sw
        src_y = sy + rel_y * sh
        src_w = rel_w * sw
        src_h = rel_h * sh

        # Scale from screenshot space to viewport/page space.
        page_bbox = self.map_bbox_to_page(
            (int(src_x), int(src_y), int(src_w), int(src_h)),
            screenshot_size,
        )
        return cell.index, page_bbox

    def map_grid_cell_to_page(
        self,
        cell_index: int,
        grid_metadata: GridMetadata,
        screenshot_size: tuple[int, int],
    ) -> tuple[int, int, int, int]:
        """Map an entire grid cell back to page coordinates.

        Useful when the VLM selects a cell by index rather than providing
        a sub-cell bounding box.

        Args:
            cell_index: 0-based cell index.
            grid_metadata: Grid composition metadata.
            screenshot_size: Size (w, h) of the original screenshot.

        Returns:
            ``(x, y, w, h)`` page-coordinate bbox for the cell's source region.

        Raises:
            ValueError: If *cell_index* is out of range.
        """
        if cell_index < 0 or cell_index >= len(grid_metadata.cells):
            raise ValueError(
                f"cell_index {cell_index} out of range "
                f"[0, {len(grid_metadata.cells)})"
            )
        cell = grid_metadata.cells[cell_index]
        return self.map_bbox_to_page(cell.source_bbox, screenshot_size)

    # ── Private Grid Helpers ───────────────────────

    @staticmethod
    def _find_cell_for_point(
        x: float, y: float, grid_metadata: GridMetadata
    ) -> CellInfo:
        """Return the cell containing point (x, y) in grid-image space.

        Raises:
            ValueError: If the point does not fall within any cell.
        """
        for cell in grid_metadata.cells:
            gx, gy = cell.grid_offset
            cw, ch = cell.cell_size
            if gx <= x < gx + cw and gy <= y < gy + ch:
                return cell

        raise ValueError(
            f"Point ({x}, {y}) does not fall within any grid cell"
        )

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
