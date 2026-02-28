"""Tests for LocalDetector — local UI element detection."""

from __future__ import annotations

from PIL import Image

from src.vision.local_detector import Detection, LocalDetector


def _make_img(w: int = 800, h: int = 600) -> Image.Image:
    return Image.new("RGB", (w, h), "white")


class TestDetect:
    def test_no_backend_returns_empty(self) -> None:
        detector = LocalDetector(backend=None)
        result = detector.detect(_make_img())
        assert result == []

    def test_with_mock_backend(self) -> None:
        class MockBackend:
            def predict(
                self, image: Image.Image, threshold: float = 0.35,
            ) -> list[Detection]:
                return [
                    Detection(box=(10, 20, 100, 80), confidence=0.9),
                    Detection(box=(200, 300, 350, 450), confidence=0.7),
                ]

        detector = LocalDetector(backend=MockBackend())
        result = detector.detect(_make_img())
        assert len(result) == 2
        assert result[0].confidence == 0.9

    def test_threshold_passed_to_backend(self) -> None:
        thresholds: list[float] = []

        class TrackingBackend:
            def predict(
                self, image: Image.Image, threshold: float = 0.35,
            ) -> list[Detection]:
                thresholds.append(threshold)
                return []

        detector = LocalDetector(backend=TrackingBackend())
        detector.detect(_make_img(), threshold=0.8)
        assert thresholds == [0.8]


class TestVerifyElementExists:
    def test_element_in_region(self) -> None:
        class MockBackend:
            def predict(
                self, image: Image.Image, threshold: float = 0.35,
            ) -> list[Detection]:
                return [Detection(box=(10, 10, 100, 100), confidence=0.9)]

        detector = LocalDetector(backend=MockBackend())
        assert detector.verify_element_exists(
            _make_img(), (10, 10, 100, 100),
        )

    def test_element_not_in_region(self) -> None:
        class MockBackend:
            def predict(
                self, image: Image.Image, threshold: float = 0.35,
            ) -> list[Detection]:
                return [Detection(box=(10, 10, 50, 50), confidence=0.9)]

        detector = LocalDetector(backend=MockBackend())
        # Far away region
        assert not detector.verify_element_exists(
            _make_img(), (500, 500, 600, 600),
        )

    def test_no_detections(self) -> None:
        detector = LocalDetector(backend=None)
        assert not detector.verify_element_exists(
            _make_img(), (10, 10, 100, 100),
        )


class TestCountItems:
    def test_no_backend(self) -> None:
        detector = LocalDetector(backend=None)
        assert detector.count_items(_make_img()) == 0

    def test_similar_sized_items(self) -> None:
        class MockBackend:
            def predict(
                self, image: Image.Image, threshold: float = 0.35,
            ) -> list[Detection]:
                # 5 product cards with similar size
                return [
                    Detection(box=(0, 0, 200, 300), confidence=0.9),
                    Detection(box=(200, 0, 400, 300), confidence=0.8),
                    Detection(box=(400, 0, 600, 300), confidence=0.85),
                    Detection(box=(0, 300, 200, 600), confidence=0.9),
                    Detection(box=(200, 300, 400, 600), confidence=0.7),
                ]

        detector = LocalDetector(backend=MockBackend())
        count = detector.count_items(_make_img())
        assert count == 5

    def test_mixed_sizes(self) -> None:
        class MockBackend:
            def predict(
                self, image: Image.Image, threshold: float = 0.35,
            ) -> list[Detection]:
                return [
                    # 3 small buttons
                    Detection(box=(0, 0, 50, 30), confidence=0.9),
                    Detection(box=(60, 0, 110, 30), confidence=0.8),
                    Detection(box=(120, 0, 170, 30), confidence=0.85),
                    # 1 large banner (very different size)
                    Detection(box=(0, 100, 800, 400), confidence=0.9),
                ]

        detector = LocalDetector(backend=MockBackend())
        count = detector.count_items(_make_img())
        # Largest group of similar size = 3 buttons
        assert count == 3

    def test_single_detection(self) -> None:
        class MockBackend:
            def predict(
                self, image: Image.Image, threshold: float = 0.35,
            ) -> list[Detection]:
                return [Detection(box=(10, 10, 100, 100), confidence=0.9)]

        detector = LocalDetector(backend=MockBackend())
        assert detector.count_items(_make_img()) == 1


class TestIoU:
    def test_perfect_overlap(self) -> None:
        iou = LocalDetector._iou((0, 0, 100, 100), (0, 0, 100, 100))
        assert iou == 1.0

    def test_no_overlap(self) -> None:
        iou = LocalDetector._iou((0, 0, 50, 50), (100, 100, 200, 200))
        assert iou == 0.0

    def test_partial_overlap(self) -> None:
        iou = LocalDetector._iou((0, 0, 100, 100), (50, 50, 150, 150))
        # Intersection: 50*50=2500, Union: 10000+10000-2500=17500
        assert abs(iou - 2500 / 17500) < 0.01

    def test_contained(self) -> None:
        iou = LocalDetector._iou((0, 0, 100, 100), (25, 25, 75, 75))
        # Intersection = 50*50 = 2500, Union = 10000+2500-2500 = 10000
        assert abs(iou - 0.25) < 0.01

    def test_zero_area_box(self) -> None:
        iou = LocalDetector._iou((0, 0, 0, 0), (0, 0, 100, 100))
        assert iou == 0.0


class TestCountSimilarSized:
    def test_empty(self) -> None:
        assert LocalDetector._count_similar_sized([]) == 0

    def test_single(self) -> None:
        dets = [Detection(box=(0, 0, 100, 100), confidence=0.9)]
        assert LocalDetector._count_similar_sized(dets) == 1

    def test_all_same_size(self) -> None:
        dets = [
            Detection(box=(i * 100, 0, i * 100 + 90, 90), confidence=0.9)
            for i in range(10)
        ]
        assert LocalDetector._count_similar_sized(dets) == 10
