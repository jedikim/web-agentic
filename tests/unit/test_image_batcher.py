"""Unit tests for Image Batcher — ``src.vision.image_batcher``."""
from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image

from src.core.types import ExtractedElement
from src.vision.image_batcher import (
    ImageBatcher,
    create_image_batcher,
)


# ── Fixtures ────────────────────────────────────────


def _make_png(width: int = 10, height: int = 10, color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """Create a minimal valid PNG image of given size and color using PIL."""
    image = Image.new("RGB", (width, height), color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _make_rgba_png(width: int = 10, height: int = 10) -> bytes:
    """Create a minimal valid RGBA PNG image."""
    image = Image.new("RGBA", (width, height), (255, 0, 0, 128))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture()
def small_png() -> bytes:
    """10x10 pixel red PNG image."""
    return _make_png(10, 10)


@pytest.fixture()
def medium_png() -> bytes:
    """200x150 pixel blue PNG image."""
    return _make_png(200, 150, (0, 0, 255))


@pytest.fixture()
def large_png() -> bytes:
    """2000x1500 pixel green PNG image (larger than target)."""
    return _make_png(2000, 1500, (0, 255, 0))


@pytest.fixture()
def batcher() -> ImageBatcher:
    """Create an ImageBatcher with default settings."""
    return ImageBatcher(max_batch_size=4, target_size=(1024, 768))


@pytest.fixture()
def small_batcher() -> ImageBatcher:
    """Create a small ImageBatcher for quicker tests."""
    return ImageBatcher(max_batch_size=4, target_size=(100, 80))


@pytest.fixture()
def candidates() -> list[ExtractedElement]:
    """Sample candidate elements with bounding boxes for annotation tests."""
    return [
        ExtractedElement(eid="btn-1", type="button", text="OK", bbox=(10, 20, 40, 20)),
        ExtractedElement(eid="btn-2", type="button", text="Cancel", bbox=(60, 20, 60, 20)),
        ExtractedElement(eid="inp-1", type="input", text="Name", bbox=(10, 60, 120, 25)),
    ]


# ── prepare_screenshot() Tests ──────────────────────


class TestPrepareScreenshot:
    """Tests for ImageBatcher.prepare_screenshot()."""

    def test_prepare_returns_png_bytes(self, batcher: ImageBatcher, small_png: bytes) -> None:
        """Prepared screenshot is valid PNG bytes."""
        result = batcher.prepare_screenshot(small_png)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_prepare_resizes_to_target(self, small_batcher: ImageBatcher, small_png: bytes) -> None:
        """Prepared screenshot has the target dimensions."""
        result = small_batcher.prepare_screenshot(small_png)
        img = Image.open(io.BytesIO(result))
        assert img.size == (100, 80)

    def test_prepare_large_image_fits_target(self, small_batcher: ImageBatcher, large_png: bytes) -> None:
        """Large images are downscaled to fit the target size."""
        result = small_batcher.prepare_screenshot(large_png)
        img = Image.open(io.BytesIO(result))
        assert img.size == (100, 80)

    def test_prepare_empty_bytes_raises(self, batcher: ImageBatcher) -> None:
        """Empty bytes raise ValueError."""
        with pytest.raises(ValueError, match="empty"):
            batcher.prepare_screenshot(b"")

    def test_prepare_rgba_image(self, small_batcher: ImageBatcher) -> None:
        """RGBA images are handled correctly (converted to RGB)."""
        rgba_png = _make_rgba_png(50, 40)
        result = small_batcher.prepare_screenshot(rgba_png)
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGB"
        assert img.size == (100, 80)

    def test_prepare_preserves_rgb_mode(self, small_batcher: ImageBatcher, small_png: bytes) -> None:
        """RGB images remain in RGB mode."""
        result = small_batcher.prepare_screenshot(small_png)
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGB"


# ── create_grid() Tests ─────────────────────────────


class TestCreateGrid:
    """Tests for ImageBatcher.create_grid()."""

    def test_grid_single_image(self, small_batcher: ImageBatcher, small_png: bytes) -> None:
        """Single image grid returns a single prepared image."""
        result = small_batcher.create_grid([small_png])
        img = Image.open(io.BytesIO(result))
        # Single image — same as target size.
        assert img.size == (100, 80)

    def test_grid_two_images(self, small_batcher: ImageBatcher, small_png: bytes) -> None:
        """Two images create a 2x1 horizontal grid."""
        result = small_batcher.create_grid([small_png, small_png])
        img = Image.open(io.BytesIO(result))
        # 2x1 grid: width = 2*100, height = 1*80.
        assert img.size == (200, 80)

    def test_grid_four_images(self, small_batcher: ImageBatcher, small_png: bytes) -> None:
        """Four images create a 2x2 grid."""
        result = small_batcher.create_grid([small_png] * 4)
        img = Image.open(io.BytesIO(result))
        # 2x2 grid: width = 2*100, height = 2*80.
        assert img.size == (200, 160)

    def test_grid_three_images(self, small_batcher: ImageBatcher, small_png: bytes) -> None:
        """Three images create a 2x2 grid (one cell empty)."""
        result = small_batcher.create_grid([small_png] * 3)
        img = Image.open(io.BytesIO(result))
        assert img.size == (200, 160)

    def test_grid_empty_list_raises(self, batcher: ImageBatcher) -> None:
        """Empty image list raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            batcher.create_grid([])

    def test_grid_exceeds_max_batch_size(self, small_batcher: ImageBatcher, small_png: bytes) -> None:
        """Excess images beyond max_batch_size are dropped."""
        # max_batch_size=4, pass 6 images.
        result = small_batcher.create_grid([small_png] * 6)
        img = Image.open(io.BytesIO(result))
        # Should be 2x2 grid (only 4 images used).
        assert img.size == (200, 160)

    def test_grid_returns_valid_png(self, small_batcher: ImageBatcher, small_png: bytes) -> None:
        """Grid output is valid PNG."""
        result = small_batcher.create_grid([small_png, small_png])
        assert result[:8] == b"\x89PNG\r\n\x1a\n"


# ── annotate_candidates() Tests ─────────────────────


class TestAnnotateCandidates:
    """Tests for ImageBatcher.annotate_candidates()."""

    def test_annotate_returns_png(
        self, small_batcher: ImageBatcher, candidates: list[ExtractedElement]
    ) -> None:
        """Annotated screenshot is valid PNG."""
        # Use a larger image so bbox fits.
        screenshot = _make_png(200, 100)
        result = small_batcher.annotate_candidates(screenshot, candidates)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_annotate_preserves_dimensions(
        self, small_batcher: ImageBatcher, candidates: list[ExtractedElement]
    ) -> None:
        """Annotated image has same dimensions as input."""
        screenshot = _make_png(200, 100)
        result = small_batcher.annotate_candidates(screenshot, candidates)
        original = Image.open(io.BytesIO(screenshot))
        annotated = Image.open(io.BytesIO(result))
        assert annotated.size == original.size

    def test_annotate_empty_candidates(self, small_batcher: ImageBatcher) -> None:
        """Empty candidates list returns the image unchanged in size."""
        screenshot = _make_png(200, 100)
        result = small_batcher.annotate_candidates(screenshot, [])
        original = Image.open(io.BytesIO(screenshot))
        annotated = Image.open(io.BytesIO(result))
        assert annotated.size == original.size

    def test_annotate_modifies_pixels(
        self, small_batcher: ImageBatcher, candidates: list[ExtractedElement]
    ) -> None:
        """Annotation modifies pixel data (boxes are drawn)."""
        screenshot = _make_png(200, 100)
        result = small_batcher.annotate_candidates(screenshot, candidates)
        # The annotated image should differ from the original.
        assert result != screenshot

    def test_annotate_skips_zero_size_bbox(self, small_batcher: ImageBatcher) -> None:
        """Candidates with zero-size bboxes are skipped."""
        screenshot = _make_png(200, 100)
        candidates = [
            ExtractedElement(eid="zero", type="button", text="Zero", bbox=(10, 10, 0, 0)),
        ]
        # Should not crash.
        result = small_batcher.annotate_candidates(screenshot, candidates)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"


# ── Factory Tests ───────────────────────────────────


class TestFactory:
    """Tests for the create_image_batcher factory."""

    def test_create_with_defaults(self) -> None:
        """Factory creates batcher with default settings."""
        b = create_image_batcher()
        assert isinstance(b, ImageBatcher)
        assert b.max_batch_size == 4
        assert b.target_size == (1024, 768)

    def test_create_with_custom_params(self) -> None:
        """Factory accepts custom parameters."""
        b = create_image_batcher(max_batch_size=8, target_size=(512, 384))
        assert b.max_batch_size == 8
        assert b.target_size == (512, 384)
