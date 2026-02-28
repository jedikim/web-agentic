"""Tests for CanvasDetector — Canvas page detection."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.vision.canvas_detector import CanvasDetector


@pytest.fixture
def detector() -> CanvasDetector:
    return CanvasDetector()


def _browser(
    has_canvas: bool = False, clickable_count: int = 50,
) -> AsyncMock:
    b = AsyncMock()

    async def evaluate(expr: str) -> object:
        if "canvas" in expr:
            return has_canvas
        return clickable_count

    b.evaluate = evaluate
    return b


class TestIsCanvasPage:
    async def test_canvas_tag_detected(
        self, detector: CanvasDetector,
    ) -> None:
        browser = _browser(has_canvas=True, clickable_count=100)
        assert await detector.is_canvas_page(browser) is True

    async def test_few_clickable_elements(
        self, detector: CanvasDetector,
    ) -> None:
        browser = _browser(has_canvas=False, clickable_count=3)
        assert await detector.is_canvas_page(browser) is True

    async def test_normal_page(
        self, detector: CanvasDetector,
    ) -> None:
        browser = _browser(has_canvas=False, clickable_count=50)
        assert await detector.is_canvas_page(browser) is False

    async def test_threshold_boundary_equal(
        self, detector: CanvasDetector,
    ) -> None:
        # Exactly at threshold (5) → Canvas
        browser = _browser(has_canvas=False, clickable_count=5)
        assert await detector.is_canvas_page(browser) is True

    async def test_threshold_boundary_above(
        self, detector: CanvasDetector,
    ) -> None:
        browser = _browser(has_canvas=False, clickable_count=6)
        assert await detector.is_canvas_page(browser) is False

    async def test_zero_clickable(
        self, detector: CanvasDetector,
    ) -> None:
        browser = _browser(has_canvas=False, clickable_count=0)
        assert await detector.is_canvas_page(browser) is True

    async def test_canvas_tag_takes_priority(
        self, detector: CanvasDetector,
    ) -> None:
        # Canvas tag present + many clickable → still Canvas
        browser = _browser(has_canvas=True, clickable_count=100)
        assert await detector.is_canvas_page(browser) is True


class TestCustomThreshold:
    async def test_custom_threshold(self) -> None:
        detector = CanvasDetector()
        detector.CANVAS_THRESHOLD = 10
        browser = _browser(has_canvas=False, clickable_count=8)
        assert await detector.is_canvas_page(browser) is True
