"""Tests for GridComposer — grid image creation."""

from __future__ import annotations

import pytest
from PIL import Image

from src.vision.grid_composer import GridComposer


@pytest.fixture
def composer() -> GridComposer:
    return GridComposer()


def _make_img(
    width: int = 100, height: int = 100, color: str = "red",
) -> Image.Image:
    return Image.new("RGB", (width, height), color)


class TestCompose:
    def test_single_image(self, composer: GridComposer) -> None:
        imgs = [_make_img()]
        grid = composer.compose(imgs, cols=4, cell_size=(50, 50))
        assert grid.size == (50, 50)

    def test_4_images_2x2(self, composer: GridComposer) -> None:
        imgs = [_make_img() for _ in range(4)]
        grid = composer.compose(imgs, cols=2, cell_size=(100, 100))
        assert grid.size == (200, 200)

    def test_5_images_3_cols(self, composer: GridComposer) -> None:
        imgs = [_make_img() for _ in range(5)]
        grid = composer.compose(imgs, cols=3, cell_size=(100, 100))
        # 5 items in 3 cols = 2 rows
        assert grid.size == (300, 200)

    def test_20_images_4x5(self, composer: GridComposer) -> None:
        imgs = [_make_img() for _ in range(20)]
        grid = composer.compose(imgs, cols=4, cell_size=(300, 300))
        assert grid.size == (1200, 1500)

    def test_empty_list(self, composer: GridComposer) -> None:
        grid = composer.compose([], cols=4)
        assert grid.size == (1, 1)

    def test_custom_labels(self, composer: GridComposer) -> None:
        imgs = [_make_img(), _make_img()]
        labels = ["A", "B"]
        grid = composer.compose(
            imgs, cols=2, cell_size=(100, 100), labels=labels,
        )
        assert grid.size == (200, 100)

    def test_cols_clamped_to_image_count(
        self, composer: GridComposer,
    ) -> None:
        imgs = [_make_img(), _make_img()]
        # cols=10 but only 2 images → cols clamped to 2
        grid = composer.compose(imgs, cols=10, cell_size=(100, 100))
        assert grid.size == (200, 100)

    def test_resizes_images(self, composer: GridComposer) -> None:
        imgs = [_make_img(width=500, height=500)]
        grid = composer.compose(imgs, cols=1, cell_size=(100, 100))
        assert grid.size == (100, 100)

    def test_different_sized_inputs(
        self, composer: GridComposer,
    ) -> None:
        imgs = [
            _make_img(100, 100),
            _make_img(200, 50),
            _make_img(50, 300),
        ]
        grid = composer.compose(imgs, cols=3, cell_size=(100, 100))
        assert grid.size == (300, 100)


class TestDrawLabel:
    def test_label_draws_without_error(
        self, composer: GridComposer,
    ) -> None:
        grid = Image.new("RGB", (200, 200), "white")
        # Should not raise
        composer._draw_label(grid, 0, 0, "1")
        composer._draw_label(grid, 100, 100, "Test")

    def test_label_modifies_pixels(
        self, composer: GridComposer,
    ) -> None:
        grid = Image.new("RGB", (100, 100), "white")
        before = grid.copy()
        composer._draw_label(grid, 0, 0, "X")
        # At least some pixels should differ
        assert grid.tobytes() != before.tobytes()
