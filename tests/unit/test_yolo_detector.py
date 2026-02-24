"""Unit tests for YOLO detector — ``src.vision.yolo_detector``."""
from __future__ import annotations

import io
import struct
import zlib
from unittest.mock import MagicMock, patch

import pytest

from src.core.types import ExtractedElement
from src.vision.yolo_detector import (
    Detection,
    YOLODetector,
    create_yolo_detector,
    _LABEL_TO_TYPE,
)


# ── Fixtures ────────────────────────────────────────


def _make_png(width: int = 10, height: int = 10) -> bytes:
    """Create a minimal valid PNG image of given size."""
    # Minimal PNG: IHDR + single IDAT + IEND
    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # Raw image data: filter byte 0 + RGB pixels per row
    raw_rows = b""
    for _ in range(height):
        raw_rows += b"\x00" + b"\xff\x00\x00" * width  # filter=0 + red pixels
    idat_data = zlib.compress(raw_rows)

    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", ihdr_data)
    png += _chunk(b"IDAT", idat_data)
    png += _chunk(b"IEND", b"")
    return png


@pytest.fixture()
def small_png() -> bytes:
    """10x10 pixel red PNG image."""
    return _make_png(10, 10)


@pytest.fixture()
def detector() -> YOLODetector:
    """Create a YOLODetector with default settings."""
    return YOLODetector(model_path="yolo11n.pt", confidence_threshold=0.5)


def _fake_detections() -> list[dict]:
    """Return a list of fake YOLO detection dicts."""
    return [
        {
            "label": "button",
            "confidence": 0.95,
            "bbox": (100, 200, 50, 30),
            "class_id": 0,
        },
        {
            "label": "input",
            "confidence": 0.85,
            "bbox": (300, 100, 200, 40),
            "class_id": 1,
        },
        {
            "label": "link",
            "confidence": 0.72,
            "bbox": (50, 400, 120, 20),
            "class_id": 2,
        },
        {
            "label": "icon",
            "confidence": 0.40,
            "bbox": (500, 300, 16, 16),
            "class_id": 3,
        },
    ]


# ── Detection Dataclass Tests ───────────────────────


class TestDetection:
    """Tests for the Detection dataclass."""

    def test_detection_creation(self) -> None:
        """Detection holds label, confidence, bbox, and class_id."""
        det = Detection(label="button", confidence=0.95, bbox=(10, 20, 30, 40), class_id=0)
        assert det.label == "button"
        assert det.confidence == 0.95
        assert det.bbox == (10, 20, 30, 40)
        assert det.class_id == 0

    def test_detection_is_frozen(self) -> None:
        """Detection is immutable (frozen dataclass)."""
        det = Detection(label="button", confidence=0.95, bbox=(10, 20, 30, 40), class_id=0)
        with pytest.raises(AttributeError):
            det.label = "input"  # type: ignore[misc]


# ── YOLODetector.detect() Tests ─────────────────────


class TestDetect:
    """Tests for YOLODetector.detect()."""

    @pytest.mark.asyncio
    async def test_detect_returns_list_of_detections(
        self, detector: YOLODetector, small_png: bytes
    ) -> None:
        """detect() returns a list of Detection objects."""
        with patch.object(detector, "_run_inference", return_value=_fake_detections()):
            results = await detector.detect(small_png)
        assert isinstance(results, list)
        assert all(isinstance(d, Detection) for d in results)

    @pytest.mark.asyncio
    async def test_detect_filters_by_confidence(
        self, detector: YOLODetector, small_png: bytes
    ) -> None:
        """Detections below confidence_threshold are excluded."""
        with patch.object(detector, "_run_inference", return_value=_fake_detections()):
            results = await detector.detect(small_png)
        # The icon detection (0.40) should be filtered out (threshold=0.5).
        confidences = [d.confidence for d in results]
        assert all(c >= 0.5 for c in confidences)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_detect_sorted_by_confidence_descending(
        self, detector: YOLODetector, small_png: bytes
    ) -> None:
        """Results are sorted by confidence, highest first."""
        with patch.object(detector, "_run_inference", return_value=_fake_detections()):
            results = await detector.detect(small_png)
        confidences = [d.confidence for d in results]
        assert confidences == sorted(confidences, reverse=True)

    @pytest.mark.asyncio
    async def test_detect_empty_screenshot_returns_empty(
        self, detector: YOLODetector
    ) -> None:
        """Empty screenshot bytes return an empty list."""
        results = await detector.detect(b"")
        assert results == []

    @pytest.mark.asyncio
    async def test_detect_no_results(
        self, detector: YOLODetector, small_png: bytes
    ) -> None:
        """When YOLO finds nothing, detect() returns empty list."""
        with patch.object(detector, "_run_inference", return_value=[]):
            results = await detector.detect(small_png)
        assert results == []

    @pytest.mark.asyncio
    async def test_detect_preserves_bbox(
        self, detector: YOLODetector, small_png: bytes
    ) -> None:
        """Bounding box coordinates are preserved from raw detections."""
        fake = [{"label": "button", "confidence": 0.9, "bbox": (10, 20, 30, 40), "class_id": 0}]
        with patch.object(detector, "_run_inference", return_value=fake):
            results = await detector.detect(small_png)
        assert results[0].bbox == (10, 20, 30, 40)

    @pytest.mark.asyncio
    async def test_detect_high_threshold_filters_all(
        self, small_png: bytes
    ) -> None:
        """Very high threshold filters all detections."""
        det = YOLODetector(confidence_threshold=0.99)
        with patch.object(det, "_run_inference", return_value=_fake_detections()):
            results = await det.detect(small_png)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_detect_low_threshold_includes_all(
        self, small_png: bytes
    ) -> None:
        """Very low threshold includes all detections."""
        det = YOLODetector(confidence_threshold=0.1)
        with patch.object(det, "_run_inference", return_value=_fake_detections()):
            results = await det.detect(small_png)
        assert len(results) == 4


# ── YOLODetector.detect_elements() Tests ────────────


class TestDetectElements:
    """Tests for YOLODetector.detect_elements()."""

    @pytest.mark.asyncio
    async def test_detect_elements_returns_extracted_elements(
        self, detector: YOLODetector, small_png: bytes
    ) -> None:
        """detect_elements() returns ExtractedElement objects."""
        with patch.object(detector, "_run_inference", return_value=_fake_detections()):
            elements = await detector.detect_elements(small_png)
        assert isinstance(elements, list)
        assert all(isinstance(e, ExtractedElement) for e in elements)

    @pytest.mark.asyncio
    async def test_detect_elements_maps_types(
        self, detector: YOLODetector, small_png: bytes
    ) -> None:
        """Element types are correctly mapped from YOLO labels."""
        with patch.object(detector, "_run_inference", return_value=_fake_detections()):
            elements = await detector.detect_elements(small_png)
        types = {e.type for e in elements}
        # button, input, link should all be present (icon filtered by confidence).
        assert "button" in types
        assert "input" in types
        assert "link" in types

    @pytest.mark.asyncio
    async def test_detect_elements_type_filter(
        self, detector: YOLODetector, small_png: bytes
    ) -> None:
        """element_types filter restricts output to matching types."""
        with patch.object(detector, "_run_inference", return_value=_fake_detections()):
            elements = await detector.detect_elements(small_png, element_types=["button"])
        assert all(e.type == "button" for e in elements)
        assert len(elements) == 1

    @pytest.mark.asyncio
    async def test_detect_elements_eid_format(
        self, detector: YOLODetector, small_png: bytes
    ) -> None:
        """Element IDs follow the yolo-{index}-{label} format."""
        fake = [{"label": "button", "confidence": 0.9, "bbox": (10, 20, 30, 40), "class_id": 0}]
        with patch.object(detector, "_run_inference", return_value=fake):
            elements = await detector.detect_elements(small_png)
        assert elements[0].eid == "yolo-0-button"

    @pytest.mark.asyncio
    async def test_detect_elements_parent_context(
        self, detector: YOLODetector, small_png: bytes
    ) -> None:
        """Elements have parent_context set to 'yolo_detection'."""
        fake = [{"label": "button", "confidence": 0.9, "bbox": (10, 20, 30, 40), "class_id": 0}]
        with patch.object(detector, "_run_inference", return_value=fake):
            elements = await detector.detect_elements(small_png)
        assert elements[0].parent_context == "yolo_detection"

    @pytest.mark.asyncio
    async def test_detect_elements_unknown_label_gets_default_type(
        self, detector: YOLODetector, small_png: bytes
    ) -> None:
        """Unknown YOLO labels default to 'button' element type."""
        fake = [{"label": "unknown_thing", "confidence": 0.9, "bbox": (10, 20, 30, 40), "class_id": 99}]
        with patch.object(detector, "_run_inference", return_value=fake):
            elements = await detector.detect_elements(small_png)
        assert elements[0].type == "button"

    @pytest.mark.asyncio
    async def test_detect_elements_empty_returns_empty(
        self, detector: YOLODetector
    ) -> None:
        """Empty screenshot returns empty element list."""
        elements = await detector.detect_elements(b"")
        assert elements == []


# ── Lazy Loading Tests ──────────────────────────────


class TestLazyLoading:
    """Tests for lazy model loading behavior."""

    def test_model_not_loaded_initially(self, detector: YOLODetector) -> None:
        """Model is not loaded at construction time."""
        assert detector.is_loaded is False
        assert detector._model is None

    def test_load_model_sets_loaded_flag(self) -> None:
        """_load_model sets the is_loaded flag."""
        det = YOLODetector()
        with patch("src.vision.yolo_detector.YOLO", create=True) as mock_yolo:
            # Simulate ultralytics import.
            import sys
            mock_module = MagicMock()
            mock_module.YOLO = mock_yolo
            with patch.dict(sys.modules, {"ultralytics": mock_module}):
                det._load_model()
        assert det.is_loaded is True


# ── Factory Tests ───────────────────────────────────


class TestFactory:
    """Tests for the create_yolo_detector factory."""

    def test_create_with_defaults(self) -> None:
        """Factory creates a detector with default settings."""
        det = create_yolo_detector()
        assert isinstance(det, YOLODetector)
        assert det._model_path == "yolo11n.pt"
        assert det._confidence_threshold == 0.5

    def test_create_with_custom_params(self) -> None:
        """Factory accepts custom model_path and confidence_threshold."""
        det = create_yolo_detector(model_path="custom.pt", confidence_threshold=0.8)
        assert det._model_path == "custom.pt"
        assert det._confidence_threshold == 0.8
