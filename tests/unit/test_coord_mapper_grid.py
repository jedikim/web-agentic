"""Unit tests for CoordMapper grid reverse-mapping methods."""
from __future__ import annotations

import pytest

from src.vision.coord_mapper import CoordMapper
from src.vision.image_batcher import CellInfo, GridMetadata


# ── Helpers ────────────────────────────────────────


def _make_2x2_metadata() -> GridMetadata:
    """Create a 2×2 grid metadata (200×160, cells 100×80 each)."""
    cells = [
        CellInfo(index=0, source_bbox=(0, 0, 200, 160), grid_offset=(0, 0), cell_size=(100, 80)),
        CellInfo(index=1, source_bbox=(200, 0, 200, 160), grid_offset=(100, 0), cell_size=(100, 80)),
        CellInfo(index=2, source_bbox=(0, 160, 200, 160), grid_offset=(0, 80), cell_size=(100, 80)),
        CellInfo(index=3, source_bbox=(200, 160, 200, 160), grid_offset=(100, 80), cell_size=(100, 80)),
    ]
    return GridMetadata(cells=cells, grid_size=(200, 160), cols=2, rows=2)


@pytest.fixture()
def mapper() -> CoordMapper:
    """1:1 viewport = screenshot (no scaling)."""
    return CoordMapper(viewport_size=(400, 320))


@pytest.fixture()
def meta() -> GridMetadata:
    return _make_2x2_metadata()


# ── map_grid_detection_to_page() Tests ────────────


class TestMapGridDetectionToPage:
    def test_detection_in_first_cell(
        self, mapper: CoordMapper, meta: GridMetadata
    ) -> None:
        """Detection at (10, 10, 20, 20) in cell 0 → page (20, 20, 40, 40)."""
        # Grid cell 0: offset (0,0), cell_size (100,80), source_bbox (0,0,200,160)
        # rel_x = 10/100 = 0.1, rel_y = 10/80 = 0.125
        # rel_w = 20/100 = 0.2, rel_h = 20/80 = 0.25
        # src: x=0+0.1*200=20, y=0+0.125*160=20, w=0.2*200=40, h=0.25*160=40
        # viewport == screenshot → no scaling
        idx, bbox = mapper.map_grid_detection_to_page(
            (10, 10, 20, 20), meta, screenshot_size=(400, 320)
        )
        assert idx == 0
        assert bbox == (20, 20, 40, 40)

    def test_detection_in_last_cell(
        self, mapper: CoordMapper, meta: GridMetadata
    ) -> None:
        """Detection in cell 3 (bottom-right)."""
        # Cell 3: offset (100,80), source_bbox (200,160,200,160)
        # Detection at grid (110, 85, 10, 10) → center (115, 90) → cell 3
        # rel_x = (110-100)/100 = 0.1, rel_y = (85-80)/80 = 0.0625
        # src: x=200+0.1*200=220, y=160+0.0625*160=170, w=0.1*200=20, h=0.125*160=20
        idx, bbox = mapper.map_grid_detection_to_page(
            (110, 85, 10, 10), meta, screenshot_size=(400, 320)
        )
        assert idx == 3
        assert bbox == (220, 170, 20, 20)

    def test_with_scroll_offset(self, meta: GridMetadata) -> None:
        mapper = CoordMapper(viewport_size=(400, 320))
        mapper.scroll_offset = (0, 500)
        idx, bbox = mapper.map_grid_detection_to_page(
            (10, 10, 20, 20), meta, screenshot_size=(400, 320)
        )
        assert idx == 0
        # Same as first cell but y += 500
        assert bbox == (20, 520, 40, 40)

    def test_with_viewport_scaling(self, meta: GridMetadata) -> None:
        """Viewport 800×640 but screenshot 400×320 → 2x scale."""
        mapper = CoordMapper(viewport_size=(800, 640))
        idx, bbox = mapper.map_grid_detection_to_page(
            (10, 10, 20, 20), meta, screenshot_size=(400, 320)
        )
        assert idx == 0
        # Unscaled: (20, 20, 40, 40), scaled 2x → (40, 40, 80, 80)
        assert bbox == (40, 40, 80, 80)

    def test_detection_outside_cells_raises(
        self, mapper: CoordMapper, meta: GridMetadata
    ) -> None:
        with pytest.raises(ValueError, match="does not fall within"):
            mapper.map_grid_detection_to_page(
                (300, 300, 10, 10), meta, screenshot_size=(400, 320)
            )


# ── map_grid_cell_to_page() Tests ─────────────────


class TestMapGridCellToPage:
    def test_cell_to_page_mapping(
        self, mapper: CoordMapper, meta: GridMetadata
    ) -> None:
        """Cell 0 source_bbox (0,0,200,160) → same (no scaling)."""
        bbox = mapper.map_grid_cell_to_page(0, meta, screenshot_size=(400, 320))
        assert bbox == (0, 0, 200, 160)

    def test_cell_3_to_page(
        self, mapper: CoordMapper, meta: GridMetadata
    ) -> None:
        bbox = mapper.map_grid_cell_to_page(3, meta, screenshot_size=(400, 320))
        assert bbox == (200, 160, 200, 160)

    def test_cell_with_scaling(self, meta: GridMetadata) -> None:
        mapper = CoordMapper(viewport_size=(800, 640))
        bbox = mapper.map_grid_cell_to_page(1, meta, screenshot_size=(400, 320))
        # source_bbox (200,0,200,160) → scale 2x → (400, 0, 400, 320)
        assert bbox == (400, 0, 400, 320)

    def test_invalid_index_raises(
        self, mapper: CoordMapper, meta: GridMetadata
    ) -> None:
        with pytest.raises(ValueError, match="out of range"):
            mapper.map_grid_cell_to_page(4, meta, screenshot_size=(400, 320))

    def test_negative_index_raises(
        self, mapper: CoordMapper, meta: GridMetadata
    ) -> None:
        with pytest.raises(ValueError, match="out of range"):
            mapper.map_grid_cell_to_page(-1, meta, screenshot_size=(400, 320))
