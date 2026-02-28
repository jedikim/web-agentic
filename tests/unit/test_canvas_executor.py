"""Tests for CanvasExecutor — vision-only Canvas page execution."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from src.vision.canvas_executor import CanvasExecutor
from src.vision.local_detector import Detection, LocalDetector


def _make_screenshot() -> bytes:
    img = Image.new("RGB", (800, 600), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def mock_vlm() -> AsyncMock:
    vlm = AsyncMock()
    vlm.generate_with_image = AsyncMock(return_value="0")
    return vlm


@pytest.fixture
def mock_browser() -> AsyncMock:
    b = AsyncMock()
    b.screenshot = AsyncMock(return_value=_make_screenshot())
    b.mouse_click = AsyncMock()
    b.get_viewport_size = AsyncMock(
        return_value={"width": 800, "height": 600},
    )
    return b


class MockBackend:
    """Configurable mock detection backend."""

    def __init__(self, detections: list[Detection] | None = None) -> None:
        self._detections = detections or []

    def predict(
        self, image: Image.Image, threshold: float = 0.35,
    ) -> list[Detection]:
        return self._detections


class TestFindAndClick:
    async def test_single_detection_clicks_directly(
        self, mock_vlm: AsyncMock, mock_browser: AsyncMock,
    ) -> None:
        backend = MockBackend([
            Detection(box=(100, 200, 200, 300), confidence=0.9),
        ])
        detector = LocalDetector(backend=backend)
        executor = CanvasExecutor(
            local_detector=detector, vlm=mock_vlm,
        )

        result = await executor.find_and_click(
            mock_browser, "검색 버튼",
        )

        assert result is True
        mock_browser.mouse_click.assert_called_once_with(150, 250)
        # VLM should NOT be called (single candidate)
        mock_vlm.generate_with_image.assert_not_called()

    async def test_multiple_detections_vlm_chooses(
        self, mock_vlm: AsyncMock, mock_browser: AsyncMock,
    ) -> None:
        backend = MockBackend([
            Detection(box=(100, 100, 200, 200), confidence=0.9),
            Detection(box=(300, 100, 400, 200), confidence=0.8),
            Detection(box=(500, 100, 600, 200), confidence=0.7),
        ])
        detector = LocalDetector(backend=backend)
        executor = CanvasExecutor(
            local_detector=detector, vlm=mock_vlm,
        )

        # VLM returns "1" → choose second candidate
        mock_vlm.generate_with_image = AsyncMock(return_value="1")

        result = await executor.find_and_click(
            mock_browser, "검색 버튼",
        )

        assert result is True
        mock_browser.mouse_click.assert_called_once_with(350, 150)

    async def test_no_detections_vlm_locates(
        self, mock_vlm: AsyncMock, mock_browser: AsyncMock,
    ) -> None:
        detector = LocalDetector(backend=MockBackend([]))
        executor = CanvasExecutor(
            local_detector=detector, vlm=mock_vlm,
        )

        mock_vlm.generate_with_image = AsyncMock(
            return_value='{"x": 400, "y": 300}',
        )

        result = await executor.find_and_click(
            mock_browser, "검색 버튼",
        )

        assert result is True
        mock_browser.mouse_click.assert_called_once_with(400, 300)

    async def test_all_methods_fail(
        self, mock_vlm: AsyncMock, mock_browser: AsyncMock,
    ) -> None:
        detector = LocalDetector(backend=MockBackend([]))
        executor = CanvasExecutor(
            local_detector=detector, vlm=mock_vlm,
        )

        # VLM returns garbage
        mock_vlm.generate_with_image = AsyncMock(
            return_value="I don't know",
        )

        result = await executor.find_and_click(
            mock_browser, "impossible target",
        )

        assert result is False

    async def test_vlm_returns_invalid_index(
        self, mock_vlm: AsyncMock, mock_browser: AsyncMock,
    ) -> None:
        backend = MockBackend([
            Detection(box=(100, 100, 200, 200), confidence=0.9),
            Detection(box=(300, 100, 400, 200), confidence=0.8),
        ])
        detector = LocalDetector(backend=backend)
        executor = CanvasExecutor(
            local_detector=detector, vlm=mock_vlm,
        )

        # VLM returns index out of range
        mock_vlm.generate_with_image = AsyncMock(
            side_effect=[
                "99",  # choose_element → invalid index
                '{"x": 400, "y": 300}',  # locate_element fallback
            ],
        )

        result = await executor.find_and_click(
            mock_browser, "대상 요소",
        )

        assert result is True
        # Should have fallen through to VLM locate
        mock_browser.mouse_click.assert_called_once_with(400, 300)

    async def test_vlm_coordinates_out_of_bounds(
        self, mock_vlm: AsyncMock, mock_browser: AsyncMock,
    ) -> None:
        detector = LocalDetector(backend=MockBackend([]))
        executor = CanvasExecutor(
            local_detector=detector, vlm=mock_vlm,
        )

        mock_vlm.generate_with_image = AsyncMock(
            return_value='{"x": 9999, "y": 9999}',
        )

        result = await executor.find_and_click(
            mock_browser, "요소",
        )
        assert result is False


class TestCenter:
    def test_basic_center(self) -> None:
        assert CanvasExecutor._center((0, 0, 100, 100)) == (50, 50)

    def test_offset_box(self) -> None:
        assert CanvasExecutor._center((200, 300, 400, 500)) == (300, 400)


class TestAnnotateCandidates:
    def test_draws_boxes(self) -> None:
        img = Image.new("RGB", (400, 400), "white")
        detections = [
            Detection(box=(10, 10, 100, 100), confidence=0.9),
            Detection(box=(200, 200, 300, 300), confidence=0.8),
        ]
        result = CanvasExecutor._annotate_candidates(img, detections)
        assert result.size == (400, 400)
        # Original should not be modified
        assert img.tobytes() != result.tobytes()


class TestChooseElement:
    async def test_parses_number(self, mock_vlm: AsyncMock) -> None:
        executor = CanvasExecutor(
            local_detector=LocalDetector(), vlm=mock_vlm,
        )
        mock_vlm.generate_with_image = AsyncMock(return_value="2")
        result = await executor._choose_element(b"img", "target", 5)
        assert result == 2

    async def test_extracts_from_text(
        self, mock_vlm: AsyncMock,
    ) -> None:
        executor = CanvasExecutor(
            local_detector=LocalDetector(), vlm=mock_vlm,
        )
        mock_vlm.generate_with_image = AsyncMock(
            return_value="번호 3이 맞습니다",
        )
        result = await executor._choose_element(b"img", "target", 5)
        assert result == 3

    async def test_no_number_returns_none(
        self, mock_vlm: AsyncMock,
    ) -> None:
        executor = CanvasExecutor(
            local_detector=LocalDetector(), vlm=mock_vlm,
        )
        mock_vlm.generate_with_image = AsyncMock(
            return_value="잘 모르겠습니다",
        )
        result = await executor._choose_element(b"img", "target", 5)
        assert result is None


class TestLocateElement:
    async def test_parses_json_coords(
        self, mock_vlm: AsyncMock,
    ) -> None:
        executor = CanvasExecutor(
            local_detector=LocalDetector(), vlm=mock_vlm,
        )
        mock_vlm.generate_with_image = AsyncMock(
            return_value='{"x": 150, "y": 250}',
        )
        result = await executor._locate_element(
            b"img", "버튼", (800, 600),
        )
        assert result == (150, 250)

    async def test_invalid_json_returns_none(
        self, mock_vlm: AsyncMock,
    ) -> None:
        executor = CanvasExecutor(
            local_detector=LocalDetector(), vlm=mock_vlm,
        )
        mock_vlm.generate_with_image = AsyncMock(
            return_value="no json here",
        )
        result = await executor._locate_element(
            b"img", "버튼", (800, 600),
        )
        assert result is None

    async def test_out_of_bounds_returns_none(
        self, mock_vlm: AsyncMock,
    ) -> None:
        executor = CanvasExecutor(
            local_detector=LocalDetector(), vlm=mock_vlm,
        )
        mock_vlm.generate_with_image = AsyncMock(
            return_value='{"x": 0, "y": 0}',
        )
        result = await executor._locate_element(
            b"img", "버튼", (800, 600),
        )
        # x=0 → not > 0
        assert result is None
