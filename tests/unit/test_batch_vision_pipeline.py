"""Unit tests for BatchVisionPipeline — ``src.vision.batch_vision_pipeline``."""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from src.vision.batch_vision_pipeline import (
    YOLO_MIN_AVG_CONFIDENCE,
    YOLO_MIN_COVERAGE_RATIO,
    BatchItemResult,
    BatchVisionPipeline,
    BatchVisionResult,
)
from src.vision.coord_mapper import CoordMapper
from src.vision.image_batcher import CellInfo, GridMetadata, ImageBatcher
from src.vision.yolo_detector import Detection, YOLODetector
from src.vision.vlm_client import VLMClient


# ── Helpers ────────────────────────────────────────


def _make_png(w: int = 400, h: int = 320, color: tuple[int, int, int] = (128, 128, 128)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_2x2_metadata() -> GridMetadata:
    return GridMetadata(
        cells=[
            CellInfo(index=0, source_bbox=(0, 0, 200, 160), grid_offset=(0, 0), cell_size=(100, 80)),
            CellInfo(index=1, source_bbox=(200, 0, 200, 160), grid_offset=(100, 0), cell_size=(100, 80)),
            CellInfo(index=2, source_bbox=(0, 160, 200, 160), grid_offset=(0, 80), cell_size=(100, 80)),
            CellInfo(index=3, source_bbox=(200, 160, 200, 160), grid_offset=(100, 80), cell_size=(100, 80)),
        ],
        grid_size=(200, 160),
        cols=2,
        rows=2,
    )


def _good_yolo_detections() -> list[tuple[int, list[Detection]]]:
    """YOLO detections covering all 4 cells with high confidence."""
    return [
        (0, [Detection(label="card", confidence=0.9, bbox=(10, 10, 20, 20), class_id=0)]),
        (1, [Detection(label="card", confidence=0.85, bbox=(110, 10, 20, 20), class_id=0)]),
        (2, [Detection(label="card", confidence=0.88, bbox=(10, 90, 20, 20), class_id=0)]),
        (3, [Detection(label="card", confidence=0.92, bbox=(110, 90, 20, 20), class_id=0)]),
    ]


def _partial_yolo_detections() -> list[tuple[int, list[Detection]]]:
    """Only 1 of 4 cells covered — below YOLO_MIN_COVERAGE_RATIO."""
    return [
        (0, [Detection(label="card", confidence=0.9, bbox=(10, 10, 20, 20), class_id=0)]),
    ]


def _low_conf_yolo_detections() -> list[tuple[int, list[Detection]]]:
    """All 4 cells covered but avg confidence below threshold."""
    return [
        (0, [Detection(label="card", confidence=0.4, bbox=(10, 10, 20, 20), class_id=0)]),
        (1, [Detection(label="card", confidence=0.3, bbox=(110, 10, 20, 20), class_id=0)]),
        (2, [Detection(label="card", confidence=0.5, bbox=(10, 90, 20, 20), class_id=0)]),
        (3, [Detection(label="card", confidence=0.4, bbox=(110, 90, 20, 20), class_id=0)]),
    ]


def _vlm_results() -> list[dict]:
    return [
        {"index": 0, "label": "shoes", "confidence": 0.95, "relevant": True, "description": "Red sneakers", "reason": "matches"},
        {"index": 1, "label": "hat", "confidence": 0.6, "relevant": False, "description": "Blue hat", "reason": "wrong"},
        {"index": 2, "label": "shoes", "confidence": 0.88, "relevant": True, "description": "White shoes", "reason": "matches"},
        {"index": 3, "label": "bag", "confidence": 0.5, "relevant": False, "description": "Leather bag", "reason": "wrong"},
    ]


@pytest.fixture()
def batcher() -> ImageBatcher:
    return ImageBatcher(max_batch_size=4, target_size=(100, 80))


@pytest.fixture()
def screenshot() -> bytes:
    return _make_png(400, 320)


@pytest.fixture()
def item_bboxes() -> list[tuple[int, int, int, int]]:
    return [(0, 0, 200, 160), (200, 0, 200, 160), (0, 160, 200, 160), (200, 160, 200, 160)]


# ── Quality Judgment Tests ─────────────────────────


class TestQualityJudgment:
    def test_sufficient_quality(self) -> None:
        ok, reason = BatchVisionPipeline._judge_yolo_quality(
            _good_yolo_detections(), total_cells=4
        )
        assert ok is True
        assert reason == ""

    def test_low_coverage_insufficient(self) -> None:
        ok, reason = BatchVisionPipeline._judge_yolo_quality(
            _partial_yolo_detections(), total_cells=4
        )
        assert ok is False
        assert "covered" in reason.lower() or "%" in reason

    def test_low_confidence_insufficient(self) -> None:
        ok, reason = BatchVisionPipeline._judge_yolo_quality(
            _low_conf_yolo_detections(), total_cells=4
        )
        assert ok is False
        assert "confidence" in reason.lower()

    def test_boundary_coverage_exactly_half(self) -> None:
        """Exactly 50% coverage (2/4) should pass."""
        dets = _good_yolo_detections()[:2]  # 2 of 4 cells
        ok, _ = BatchVisionPipeline._judge_yolo_quality(dets, total_cells=4)
        assert ok is True

    def test_zero_cells(self) -> None:
        ok, reason = BatchVisionPipeline._judge_yolo_quality([], total_cells=0)
        assert ok is False


# ── Pipeline Tests ─────────────────────────────────


class TestProcessBatch:
    @pytest.mark.asyncio
    async def test_yolo_sufficient_no_vlm_call(
        self, batcher: ImageBatcher, screenshot: bytes, item_bboxes: list[tuple[int, int, int, int]]
    ) -> None:
        """When YOLO quality is sufficient, VLM is not called."""
        yolo = YOLODetector()
        vlm = VLMClient(api_key="fake")
        mapper = CoordMapper(viewport_size=(400, 320))

        pipeline = BatchVisionPipeline(batcher, yolo=yolo, vlm=vlm, coord_mapper=mapper)

        with patch.object(yolo, "detect_on_grid", new_callable=AsyncMock, return_value=_good_yolo_detections()):
            with patch.object(vlm, "analyze_grid", new_callable=AsyncMock) as mock_vlm:
                result = await pipeline.process_batch(
                    screenshot, item_bboxes, "find cheapest product", (400, 320)
                )

        assert result.yolo_used is True
        assert result.vlm_used is False
        mock_vlm.assert_not_called()
        assert len(result.items) == 4
        assert all(item.source == "yolo" for item in result.items)

    @pytest.mark.asyncio
    async def test_low_coverage_escalates_to_vlm(
        self, batcher: ImageBatcher, screenshot: bytes, item_bboxes: list[tuple[int, int, int, int]]
    ) -> None:
        """Low YOLO coverage triggers VLM escalation."""
        yolo = YOLODetector()
        vlm = VLMClient(api_key="fake")
        mapper = CoordMapper(viewport_size=(400, 320))

        pipeline = BatchVisionPipeline(batcher, yolo=yolo, vlm=vlm, coord_mapper=mapper)

        with patch.object(yolo, "detect_on_grid", new_callable=AsyncMock, return_value=_partial_yolo_detections()):
            with patch.object(vlm, "analyze_grid", new_callable=AsyncMock, return_value=_vlm_results()):
                result = await pipeline.process_batch(
                    screenshot, item_bboxes, "find shoes", (400, 320)
                )

        assert result.yolo_used is True
        assert result.vlm_used is True
        assert len(result.items) == 4
        assert all(item.source == "vlm" for item in result.items)

    @pytest.mark.asyncio
    async def test_low_confidence_escalates_to_vlm(
        self, batcher: ImageBatcher, screenshot: bytes, item_bboxes: list[tuple[int, int, int, int]]
    ) -> None:
        """Low YOLO confidence triggers VLM escalation."""
        yolo = YOLODetector()
        vlm = VLMClient(api_key="fake")
        mapper = CoordMapper(viewport_size=(400, 320))

        pipeline = BatchVisionPipeline(batcher, yolo=yolo, vlm=vlm, coord_mapper=mapper)

        with patch.object(yolo, "detect_on_grid", new_callable=AsyncMock, return_value=_low_conf_yolo_detections()):
            with patch.object(vlm, "analyze_grid", new_callable=AsyncMock, return_value=_vlm_results()):
                result = await pipeline.process_batch(
                    screenshot, item_bboxes, "find shoes", (400, 320)
                )

        assert result.yolo_used is True
        assert result.vlm_used is True
        assert result.escalation_reason != ""

    @pytest.mark.asyncio
    async def test_force_vlm_skips_yolo(
        self, batcher: ImageBatcher, screenshot: bytes, item_bboxes: list[tuple[int, int, int, int]]
    ) -> None:
        """force_vlm=True skips YOLO entirely."""
        yolo = YOLODetector()
        vlm = VLMClient(api_key="fake")
        mapper = CoordMapper(viewport_size=(400, 320))

        pipeline = BatchVisionPipeline(batcher, yolo=yolo, vlm=vlm, coord_mapper=mapper)

        with patch.object(yolo, "detect_on_grid", new_callable=AsyncMock) as mock_yolo:
            with patch.object(vlm, "analyze_grid", new_callable=AsyncMock, return_value=_vlm_results()):
                result = await pipeline.process_batch(
                    screenshot, item_bboxes, "find shoes", (400, 320), force_vlm=True
                )

        mock_yolo.assert_not_called()
        assert result.yolo_used is False
        assert result.vlm_used is True

    @pytest.mark.asyncio
    async def test_no_yolo_uses_vlm_directly(
        self, batcher: ImageBatcher, screenshot: bytes, item_bboxes: list[tuple[int, int, int, int]]
    ) -> None:
        """When yolo=None, pipeline goes directly to VLM."""
        vlm = VLMClient(api_key="fake")
        mapper = CoordMapper(viewport_size=(400, 320))

        pipeline = BatchVisionPipeline(batcher, yolo=None, vlm=vlm, coord_mapper=mapper)

        with patch.object(vlm, "analyze_grid", new_callable=AsyncMock, return_value=_vlm_results()):
            result = await pipeline.process_batch(
                screenshot, item_bboxes, "find shoes", (400, 320)
            )

        assert result.yolo_used is False
        assert result.vlm_used is True

    @pytest.mark.asyncio
    async def test_results_have_page_coordinates(
        self, batcher: ImageBatcher, screenshot: bytes, item_bboxes: list[tuple[int, int, int, int]]
    ) -> None:
        """Result items contain valid page_bbox coordinates."""
        yolo = YOLODetector()
        mapper = CoordMapper(viewport_size=(400, 320))

        pipeline = BatchVisionPipeline(batcher, yolo=yolo, coord_mapper=mapper)

        with patch.object(yolo, "detect_on_grid", new_callable=AsyncMock, return_value=_good_yolo_detections()):
            result = await pipeline.process_batch(
                screenshot, item_bboxes, "find product", (400, 320)
            )

        for item in result.items:
            x, y, w, h = item.page_bbox
            assert x >= 0
            assert y >= 0
            # page_bbox should be within the screenshot dimensions (no scaling here)
            assert x + w <= 400
            assert y + h <= 320

    @pytest.mark.asyncio
    async def test_batch_exceeding_max_size(
        self, screenshot: bytes
    ) -> None:
        """6 items → split into 2 grids (4 + 2)."""
        batcher = ImageBatcher(max_batch_size=4, target_size=(100, 80))
        yolo = YOLODetector()
        mapper = CoordMapper(viewport_size=(400, 320))

        pipeline = BatchVisionPipeline(batcher, yolo=yolo, coord_mapper=mapper)

        # 6 bboxes (we'll mock the crops/grid steps)
        bboxes = [(i * 60, 0, 60, 60) for i in range(6)]

        # We need the YOLO to return good detections for each sub-grid.
        call_count = 0

        async def fake_detect_on_grid(grid_image, grid_meta):
            nonlocal call_count
            call_count += 1
            # Return one detection per cell
            return [
                (i, [Detection(label="card", confidence=0.9, bbox=(cell.grid_offset[0] + 10, cell.grid_offset[1] + 10, 20, 20), class_id=0)])
                for i, cell in enumerate(grid_meta.cells)
            ]

        with patch.object(yolo, "detect_on_grid", side_effect=fake_detect_on_grid):
            result = await pipeline.process_batch(
                screenshot, bboxes, "find products", (400, 320)
            )

        # Should have been called twice (4 + 2).
        assert call_count == 2
        # Total items: 6
        assert len(result.items) == 6
        # Cell indices should be globally adjusted.
        indices = sorted(item.cell_index for item in result.items)
        assert indices == [0, 1, 2, 3, 4, 5]
