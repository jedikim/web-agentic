"""Unit tests for Coordinate Mapper — ``src.vision.coord_mapper``."""
from __future__ import annotations

import math

import pytest

from src.core.types import ExtractedElement
from src.vision.coord_mapper import (
    CoordMapper,
    create_coord_mapper,
)
from src.vision.yolo_detector import Detection


# ── Fixtures ────────────────────────────────────────


@pytest.fixture()
def mapper() -> CoordMapper:
    """Create a CoordMapper with standard 1920x1080 viewport."""
    return CoordMapper(viewport_size=(1920, 1080))


@pytest.fixture()
def small_mapper() -> CoordMapper:
    """Create a CoordMapper with a smaller 1280x720 viewport."""
    return CoordMapper(viewport_size=(1280, 720))


@pytest.fixture()
def candidates() -> list[ExtractedElement]:
    """Sample candidate elements at known positions."""
    return [
        ExtractedElement(eid="btn-1", type="button", text="A", bbox=(100, 100, 50, 30)),
        ExtractedElement(eid="btn-2", type="button", text="B", bbox=(500, 300, 80, 40)),
        ExtractedElement(eid="btn-3", type="button", text="C", bbox=(900, 600, 60, 25)),
    ]


# ── map_detection_to_page() Tests ───────────────────


class TestMapDetectionToPage:
    """Tests for CoordMapper.map_detection_to_page()."""

    def test_same_size_no_scaling(self) -> None:
        """When screenshot == viewport, coordinates are unchanged."""
        mapper = CoordMapper(viewport_size=(1024, 768))
        det = Detection(label="button", confidence=0.9, bbox=(100, 200, 50, 30), class_id=0)
        # Center = (125, 215)
        result = mapper.map_detection_to_page(det, screenshot_size=(1024, 768))
        assert result == (125, 215)

    def test_2x_upscale(self, mapper: CoordMapper) -> None:
        """Screenshot at half viewport size scales coordinates 2x."""
        det = Detection(label="button", confidence=0.9, bbox=(100, 100, 50, 30), class_id=0)
        # Center in screenshot: (125, 115)
        # Scale: 1920/960=2, 1080/540=2
        result = mapper.map_detection_to_page(det, screenshot_size=(960, 540))
        assert result == (250, 230)

    def test_downscale(self) -> None:
        """Viewport smaller than screenshot — coordinates are downscaled."""
        mapper = CoordMapper(viewport_size=(640, 480))
        det = Detection(label="button", confidence=0.9, bbox=(200, 200, 100, 50), class_id=0)
        # Center in screenshot: (250, 225)
        # Scale: 640/1280=0.5, 480/960=0.5
        result = mapper.map_detection_to_page(det, screenshot_size=(1280, 960))
        assert result == (125, 112)

    def test_with_scroll_offset(self, mapper: CoordMapper) -> None:
        """Scroll offset is added to mapped coordinates."""
        mapper.scroll_offset = (0, 500)
        det = Detection(label="button", confidence=0.9, bbox=(0, 0, 100, 100), class_id=0)
        # Center in screenshot: (50, 50)
        # No scaling if same size.
        result = mapper.map_detection_to_page(det, screenshot_size=(1920, 1080))
        assert result == (50, 550)  # y + scroll_offset_y

    def test_with_horizontal_scroll(self, mapper: CoordMapper) -> None:
        """Horizontal scroll offset is also applied."""
        mapper.scroll_offset = (200, 0)
        det = Detection(label="button", confidence=0.9, bbox=(100, 100, 50, 50), class_id=0)
        result = mapper.map_detection_to_page(det, screenshot_size=(1920, 1080))
        assert result[0] == 125 + 200  # x + scroll_offset_x


# ── map_bbox_to_page() Tests ────────────────────────


class TestMapBboxToPage:
    """Tests for CoordMapper.map_bbox_to_page()."""

    def test_same_size_no_scaling(self) -> None:
        """When screenshot == viewport, bbox is unchanged."""
        mapper = CoordMapper(viewport_size=(1024, 768))
        result = mapper.map_bbox_to_page((100, 200, 50, 30), screenshot_size=(1024, 768))
        assert result == (100, 200, 50, 30)

    def test_2x_upscale(self, mapper: CoordMapper) -> None:
        """Bbox is scaled when screenshot differs from viewport."""
        # Scale: 1920/960=2, 1080/540=2
        result = mapper.map_bbox_to_page((100, 100, 50, 30), screenshot_size=(960, 540))
        assert result == (200, 200, 100, 60)

    def test_with_scroll_offset(self, mapper: CoordMapper) -> None:
        """Scroll offset shifts bbox position but not size."""
        mapper.scroll_offset = (0, 300)
        result = mapper.map_bbox_to_page((100, 100, 50, 30), screenshot_size=(1920, 1080))
        assert result == (100, 400, 50, 30)

    def test_different_viewport_sizes(self) -> None:
        """Different viewport sizes produce different results."""
        mapper_small = CoordMapper(viewport_size=(640, 480))
        mapper_large = CoordMapper(viewport_size=(2560, 1440))
        bbox = (100, 100, 50, 30)
        ss = (1280, 960)
        r_small = mapper_small.map_bbox_to_page(bbox, ss)
        r_large = mapper_large.map_bbox_to_page(bbox, ss)
        assert r_small != r_large
        assert r_large[2] > r_small[2]  # larger viewport → larger mapped width


# ── find_closest_element() Tests ────────────────────


class TestFindClosestElement:
    """Tests for CoordMapper.find_closest_element()."""

    def test_finds_nearest(self, mapper: CoordMapper, candidates: list[ExtractedElement]) -> None:
        """Returns the element closest to the given point."""
        # btn-1 center: (125, 115), btn-2 center: (540, 320), btn-3 center: (930, 612.5)
        result = mapper.find_closest_element((130, 120), candidates)
        assert result is not None
        assert result.eid == "btn-1"

    def test_finds_second_candidate(self, mapper: CoordMapper, candidates: list[ExtractedElement]) -> None:
        """Point near second candidate returns second candidate."""
        result = mapper.find_closest_element((550, 330), candidates)
        assert result is not None
        assert result.eid == "btn-2"

    def test_finds_third_candidate(self, mapper: CoordMapper, candidates: list[ExtractedElement]) -> None:
        """Point near third candidate returns third candidate."""
        result = mapper.find_closest_element((920, 610), candidates)
        assert result is not None
        assert result.eid == "btn-3"

    def test_empty_candidates_returns_none(self, mapper: CoordMapper) -> None:
        """Empty candidates list returns None."""
        result = mapper.find_closest_element((100, 100), [])
        assert result is None

    def test_single_candidate_always_returned(self, mapper: CoordMapper) -> None:
        """With one candidate, it's always returned regardless of distance."""
        elem = ExtractedElement(eid="sole", type="button", text="Only", bbox=(0, 0, 10, 10))
        result = mapper.find_closest_element((9999, 9999), [elem])
        assert result is not None
        assert result.eid == "sole"

    def test_equidistant_returns_first(self, mapper: CoordMapper) -> None:
        """When two candidates are equidistant, the first in list is returned."""
        e1 = ExtractedElement(eid="a", type="button", text="A", bbox=(0, 0, 100, 100))
        e2 = ExtractedElement(eid="b", type="button", text="B", bbox=(200, 0, 100, 100))
        # Point equidistant from both centers (50,50) and (250,50) → (150, 50).
        result = mapper.find_closest_element((150, 50), [e1, e2])
        assert result is not None
        # Both are 100px away; first in list wins.
        assert result.eid == "a"


# ── Scroll Offset Tests ────────────────────────────


class TestScrollOffset:
    """Tests for scroll offset handling."""

    def test_default_scroll_offset_is_zero(self, mapper: CoordMapper) -> None:
        """Default scroll offset is (0, 0)."""
        assert mapper.scroll_offset == (0, 0)

    def test_set_scroll_offset(self, mapper: CoordMapper) -> None:
        """Scroll offset can be set and retrieved."""
        mapper.scroll_offset = (100, 500)
        assert mapper.scroll_offset == (100, 500)

    def test_scroll_offset_applied_to_detection(self, mapper: CoordMapper) -> None:
        """Scroll offset is correctly applied when mapping detection."""
        mapper.scroll_offset = (50, 200)
        det = Detection(label="button", confidence=0.9, bbox=(0, 0, 100, 100), class_id=0)
        result = mapper.map_detection_to_page(det, screenshot_size=(1920, 1080))
        # Center = (50, 50) + scroll = (100, 250)
        assert result == (100, 250)


# ── Factory Tests ───────────────────────────────────


class TestFactory:
    """Tests for the create_coord_mapper factory."""

    def test_create_with_defaults(self) -> None:
        """Factory creates mapper with default viewport."""
        m = create_coord_mapper()
        assert isinstance(m, CoordMapper)
        assert m.viewport_size == (1920, 1080)

    def test_create_with_custom_viewport(self) -> None:
        """Factory accepts custom viewport size."""
        m = create_coord_mapper(viewport_size=(2560, 1440))
        assert m.viewport_size == (2560, 1440)
