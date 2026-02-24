"""Batch Vision Pipeline — Grid-based multi-item visual processing.

Combines image batching, YOLO detection, VLM classification, and coordinate
reverse-mapping into a single pipeline that processes multiple page items
with minimal API calls.

Cost model:
- crop + grid: $0 (local PIL)
- YOLO:        $0 (local GPU)
- VLM:         ~$0.003-0.005 per grid (only when YOLO quality is insufficient)
- Per-batch:   $0 ~ $0.005
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.vision.coord_mapper import CoordMapper
from src.vision.image_batcher import GridMetadata, ImageBatcher
from src.vision.vlm_client import VLMClient
from src.vision.yolo_detector import Detection, YOLODetector

logger = logging.getLogger(__name__)

# ── Quality Thresholds ──────────────────────────────

YOLO_MIN_COVERAGE_RATIO = 0.5
"""Minimum fraction of cells that must have at least one detection."""

YOLO_MIN_AVG_CONFIDENCE = 0.6
"""Minimum average confidence across all detections."""


# ── Result Dataclasses ──────────────────────────────


@dataclass(frozen=True)
class BatchItemResult:
    """Result for a single item within a batch.

    Attributes:
        cell_index: 0-based index within the grid.
        label: Detected / classified label.
        confidence: Confidence score (0.0–1.0).
        grid_bbox: Bounding box in grid-image space.
        page_bbox: Reverse-mapped bounding box in page coordinates.
        source: ``"yolo"`` or ``"vlm"``.
        extra: Additional metadata from the source.
    """

    cell_index: int
    label: str
    confidence: float
    grid_bbox: tuple[int, int, int, int]
    page_bbox: tuple[int, int, int, int]
    source: str  # "yolo" | "vlm"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BatchVisionResult:
    """Aggregated result of the batch vision pipeline.

    Attributes:
        items: Per-item results.
        grid_image: The composed grid image bytes (reusable).
        grid_metadata: Grid composition metadata.
        yolo_used: Whether YOLO detection was invoked.
        vlm_used: Whether VLM was invoked (escalation).
        total_yolo_detections: Count of YOLO detections.
        avg_yolo_confidence: Mean YOLO detection confidence.
        escalation_reason: Reason for VLM escalation (empty if none).
    """

    items: list[BatchItemResult]
    grid_image: bytes
    grid_metadata: GridMetadata
    yolo_used: bool
    vlm_used: bool
    total_yolo_detections: int = 0
    avg_yolo_confidence: float = 0.0
    escalation_reason: str = ""


# ── Pipeline ────────────────────────────────────────


class BatchVisionPipeline:
    """Grid-based batch vision pipeline.

    Orchestrates:
    1. Image cropping and grid stitching.
    2. YOLO detection on the grid (local, free).
    3. Quality judgment — escalate to VLM if YOLO is insufficient.
    4. VLM grid analysis (single API call).
    5. Coordinate reverse-mapping to page space.

    Args:
        batcher: Image batcher for cropping / grid creation.
        yolo: Optional YOLO detector (skipped if None).
        vlm: Optional VLM client (skipped if None).
        coord_mapper: Optional coordinate mapper (identity if None).
    """

    def __init__(
        self,
        batcher: ImageBatcher,
        yolo: YOLODetector | None = None,
        vlm: VLMClient | None = None,
        coord_mapper: CoordMapper | None = None,
    ) -> None:
        self._batcher = batcher
        self._yolo = yolo
        self._vlm = vlm
        self._coord_mapper = coord_mapper or CoordMapper()

    async def process_batch(
        self,
        screenshot: bytes,
        item_bboxes: list[tuple[int, int, int, int]],
        intent: str,
        screenshot_size: tuple[int, int],
        force_vlm: bool = False,
    ) -> BatchVisionResult:
        """Run the full batch vision pipeline.

        When there are more items than ``batcher.max_batch_size``, the
        items are split into groups and processed separately; results are
        then merged into a single :class:`BatchVisionResult`.

        Args:
            screenshot: Full-page screenshot bytes.
            item_bboxes: Bounding boxes for each item on the screenshot.
            intent: User intent for VLM classification.
            screenshot_size: (w, h) of the screenshot.
            force_vlm: Skip YOLO and go directly to VLM.

        Returns:
            Aggregated :class:`BatchVisionResult`.
        """
        max_bs = self._batcher.max_batch_size

        if len(item_bboxes) <= max_bs:
            return await self._process_single_grid(
                screenshot, item_bboxes, intent, screenshot_size, force_vlm,
            )

        # Split into chunks and process each.
        all_items: list[BatchItemResult] = []
        last_grid_image = b""
        last_meta = None
        yolo_used = False
        vlm_used = False
        total_yolo = 0
        sum_conf = 0.0
        count_conf = 0

        for start in range(0, len(item_bboxes), max_bs):
            chunk_bboxes = item_bboxes[start : start + max_bs]
            result = await self._process_single_grid(
                screenshot, chunk_bboxes, intent, screenshot_size, force_vlm,
            )
            # Adjust cell indices to be globally unique.
            for item in result.items:
                adjusted = BatchItemResult(
                    cell_index=item.cell_index + start,
                    label=item.label,
                    confidence=item.confidence,
                    grid_bbox=item.grid_bbox,
                    page_bbox=item.page_bbox,
                    source=item.source,
                    extra=item.extra,
                )
                all_items.append(adjusted)

            last_grid_image = result.grid_image
            last_meta = result.grid_metadata
            yolo_used = yolo_used or result.yolo_used
            vlm_used = vlm_used or result.vlm_used
            total_yolo += result.total_yolo_detections
            if result.avg_yolo_confidence > 0:
                sum_conf += result.avg_yolo_confidence * result.total_yolo_detections
                count_conf += result.total_yolo_detections

        assert last_meta is not None
        avg_conf = (sum_conf / count_conf) if count_conf > 0 else 0.0

        return BatchVisionResult(
            items=all_items,
            grid_image=last_grid_image,
            grid_metadata=last_meta,
            yolo_used=yolo_used,
            vlm_used=vlm_used,
            total_yolo_detections=total_yolo,
            avg_yolo_confidence=avg_conf,
        )

    async def _process_single_grid(
        self,
        screenshot: bytes,
        item_bboxes: list[tuple[int, int, int, int]],
        intent: str,
        screenshot_size: tuple[int, int],
        force_vlm: bool,
    ) -> BatchVisionResult:
        """Process a single grid batch (≤ max_batch_size items)."""
        # 1. Crop items from the screenshot.
        crops = self._batcher.crop_regions(screenshot, item_bboxes)

        # 2. Stitch into a grid with metadata.
        grid_image, grid_meta = self._batcher.create_grid_with_metadata(
            crops, item_bboxes,
        )

        items: list[BatchItemResult] = []
        yolo_used = False
        vlm_used = False
        total_yolo = 0
        avg_conf = 0.0
        escalation_reason = ""

        # 3. YOLO detection (unless force_vlm or no YOLO).
        cell_detections: list[tuple[int, list[Detection]]] = []
        if not force_vlm and self._yolo is not None:
            yolo_used = True
            cell_detections = await self._yolo.detect_on_grid(grid_image, grid_meta)
            total_yolo = sum(len(dets) for _, dets in cell_detections)
            if total_yolo > 0:
                avg_conf = (
                    sum(d.confidence for _, dets in cell_detections for d in dets)
                    / total_yolo
                )

            # 4. Quality judgment.
            sufficient, reason = self._judge_yolo_quality(
                cell_detections, len(grid_meta.cells),
            )
            if sufficient:
                # Build results from YOLO detections.
                for cell_idx, dets in cell_detections:
                    best = max(dets, key=lambda d: d.confidence)
                    _, page_bbox = self._coord_mapper.map_grid_detection_to_page(
                        best.bbox, grid_meta, screenshot_size,
                    )
                    items.append(
                        BatchItemResult(
                            cell_index=cell_idx,
                            label=best.label,
                            confidence=best.confidence,
                            grid_bbox=best.bbox,
                            page_bbox=page_bbox,
                            source="yolo",
                        )
                    )
                return BatchVisionResult(
                    items=items,
                    grid_image=grid_image,
                    grid_metadata=grid_meta,
                    yolo_used=True,
                    vlm_used=False,
                    total_yolo_detections=total_yolo,
                    avg_yolo_confidence=avg_conf,
                )
            else:
                escalation_reason = reason

        # 5. VLM escalation (same grid image, single API call).
        if self._vlm is not None:
            vlm_used = True
            vlm_results = await self._vlm.analyze_grid(
                grid_image, intent, len(grid_meta.cells),
            )
            for vr in vlm_results:
                cell_idx = vr["index"]
                if 0 <= cell_idx < len(grid_meta.cells):
                    page_bbox = self._coord_mapper.map_grid_cell_to_page(
                        cell_idx, grid_meta, screenshot_size,
                    )
                    items.append(
                        BatchItemResult(
                            cell_index=cell_idx,
                            label=vr.get("label", ""),
                            confidence=vr.get("confidence", 0.0),
                            grid_bbox=(0, 0, 0, 0),
                            page_bbox=page_bbox,
                            source="vlm",
                            extra={
                                "relevant": vr.get("relevant", False),
                                "description": vr.get("description", ""),
                                "reason": vr.get("reason", ""),
                            },
                        )
                    )

        return BatchVisionResult(
            items=items,
            grid_image=grid_image,
            grid_metadata=grid_meta,
            yolo_used=yolo_used,
            vlm_used=vlm_used,
            total_yolo_detections=total_yolo,
            avg_yolo_confidence=avg_conf,
            escalation_reason=escalation_reason,
        )

    @staticmethod
    def _judge_yolo_quality(
        cell_detections: list[tuple[int, list[Detection]]],
        total_cells: int,
    ) -> tuple[bool, str]:
        """Evaluate whether YOLO results are sufficient.

        Args:
            cell_detections: Per-cell detection lists from YOLO.
            total_cells: Total number of cells in the grid.

        Returns:
            ``(sufficient, reason)`` — *reason* is empty if sufficient.
        """
        if total_cells == 0:
            return False, "no cells"

        covered = len(cell_detections)
        coverage = covered / total_cells

        if coverage < YOLO_MIN_COVERAGE_RATIO:
            return False, (
                f"YOLO covered {coverage * 100:.0f}% of cells "
                f"(need {YOLO_MIN_COVERAGE_RATIO * 100:.0f}%)"
            )

        all_confs = [
            d.confidence for _, dets in cell_detections for d in dets
        ]
        avg_conf = sum(all_confs) / len(all_confs) if all_confs else 0.0

        if avg_conf < YOLO_MIN_AVG_CONFIDENCE:
            return False, (
                f"avg confidence {avg_conf:.2f} below threshold "
                f"{YOLO_MIN_AVG_CONFIDENCE}"
            )

        return True, ""
