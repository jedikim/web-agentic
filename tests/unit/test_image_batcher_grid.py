"""Unit tests for ImageBatcher grid metadata — crop_regions / create_grid_with_metadata."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from src.vision.image_batcher import (
    CellInfo,
    GridMetadata,
    ImageBatcher,
)


# ── Helpers ────────────────────────────────────────


def _make_png(
    width: int = 100, height: int = 80, color: tuple[int, int, int] = (255, 0, 0)
) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def batcher() -> ImageBatcher:
    return ImageBatcher(max_batch_size=4, target_size=(100, 80))


@pytest.fixture()
def screenshot() -> bytes:
    """400×320 screenshot with space for 4 quadrants."""
    return _make_png(400, 320)


@pytest.fixture()
def four_bboxes() -> list[tuple[int, int, int, int]]:
    """Four non-overlapping quadrant bboxes inside a 400×320 image."""
    return [
        (0, 0, 200, 160),
        (200, 0, 200, 160),
        (0, 160, 200, 160),
        (200, 160, 200, 160),
    ]


# ── crop_regions() Tests ──────────────────────────


class TestCropRegions:
    def test_crop_regions_count(
        self, batcher: ImageBatcher, screenshot: bytes, four_bboxes: list[tuple[int, int, int, int]]
    ) -> None:
        crops = batcher.crop_regions(screenshot, four_bboxes)
        assert len(crops) == 4

    def test_crop_returns_valid_png(
        self, batcher: ImageBatcher, screenshot: bytes, four_bboxes: list[tuple[int, int, int, int]]
    ) -> None:
        crops = batcher.crop_regions(screenshot, four_bboxes)
        for c in crops:
            assert c[:8] == b"\x89PNG\r\n\x1a\n"

    def test_crop_out_of_bounds_clamped(self, batcher: ImageBatcher) -> None:
        screenshot = _make_png(100, 80)
        regions = [(80, 60, 50, 50)]  # extends beyond 100×80
        crops = batcher.crop_regions(screenshot, regions)
        assert len(crops) == 1
        img = Image.open(io.BytesIO(crops[0]))
        # Clamped: x2=min(130,100)=100, y2=min(110,80)=80 → size 20×20
        assert img.width == 20
        assert img.height == 20

    def test_crop_empty_screenshot_raises(self, batcher: ImageBatcher) -> None:
        with pytest.raises(ValueError, match="empty"):
            batcher.crop_regions(b"", [(0, 0, 10, 10)])


# ── create_grid_with_metadata() Tests ─────────────


class TestCreateGridWithMetadata:
    def test_grid_metadata_cell_count(self, batcher: ImageBatcher) -> None:
        imgs = [_make_png(50, 40, (i * 60, 0, 0)) for i in range(4)]
        bboxes = [(i * 100, 0, 100, 80) for i in range(4)]
        _, meta = batcher.create_grid_with_metadata(imgs, bboxes)
        assert len(meta.cells) == 4

    def test_grid_metadata_offsets(self, batcher: ImageBatcher) -> None:
        """2×2 layout offsets should be (0,0), (100,0), (0,80), (100,80)."""
        imgs = [_make_png(50, 40)] * 4
        bboxes = [(0, 0, 50, 40)] * 4
        _, meta = batcher.create_grid_with_metadata(imgs, bboxes)
        expected_offsets = [(0, 0), (100, 0), (0, 80), (100, 80)]
        actual_offsets = [c.grid_offset for c in meta.cells]
        assert actual_offsets == expected_offsets

    def test_source_bboxes_preserved(self, batcher: ImageBatcher) -> None:
        imgs = [_make_png(50, 40)] * 3
        bboxes = [(10, 20, 100, 80), (200, 20, 100, 80), (10, 200, 100, 80)]
        _, meta = batcher.create_grid_with_metadata(imgs, bboxes)
        for i, cell in enumerate(meta.cells):
            assert cell.source_bbox == bboxes[i]

    def test_grid_size_2x2(self, batcher: ImageBatcher) -> None:
        imgs = [_make_png(50, 40)] * 4
        bboxes = [(0, 0, 50, 40)] * 4
        grid_bytes, meta = batcher.create_grid_with_metadata(imgs, bboxes)
        assert meta.grid_size == (200, 160)
        assert meta.cols == 2
        assert meta.rows == 2
        img = Image.open(io.BytesIO(grid_bytes))
        assert img.size == (200, 160)

    def test_single_image_grid(self, batcher: ImageBatcher) -> None:
        imgs = [_make_png(50, 40)]
        bboxes = [(10, 20, 50, 40)]
        _, meta = batcher.create_grid_with_metadata(imgs, bboxes)
        assert len(meta.cells) == 1
        assert meta.cols == 1
        assert meta.rows == 1

    def test_mismatch_raises(self, batcher: ImageBatcher) -> None:
        imgs = [_make_png(50, 40)] * 3
        bboxes = [(0, 0, 50, 40)] * 2  # mismatch
        with pytest.raises(ValueError, match="mismatch"):
            batcher.create_grid_with_metadata(imgs, bboxes)

    def test_empty_images_raises(self, batcher: ImageBatcher) -> None:
        with pytest.raises(ValueError, match="empty"):
            batcher.create_grid_with_metadata([], [])

    def test_returns_valid_png(self, batcher: ImageBatcher) -> None:
        imgs = [_make_png(50, 40)] * 2
        bboxes = [(0, 0, 50, 40)] * 2
        grid_bytes, _ = batcher.create_grid_with_metadata(imgs, bboxes)
        assert grid_bytes[:8] == b"\x89PNG\r\n\x1a\n"
