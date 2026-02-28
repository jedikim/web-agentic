"""GridComposer — combine multiple screenshots into a single grid image.

Used by BatchVerifier to send N item screenshots to VLM in 1 call
instead of N separate calls. Saves cost and latency.

Example:
    composer = GridComposer()
    grid = composer.compose(screenshots, cols=4)
    # grid is a single PIL Image with numbered cells
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class GridComposer:
    """Combine multiple screenshots into a numbered grid image."""

    def compose(
        self,
        screenshots: list[Image.Image],
        cols: int = 4,
        cell_size: tuple[int, int] = (300, 300),
        labels: list[str] | None = None,
    ) -> Image.Image:
        """Compose N screenshots into a grid image.

        Args:
            screenshots: List of PIL images to arrange.
            cols: Number of columns in the grid.
            cell_size: (width, height) of each cell.
            labels: Optional labels for each cell. Defaults to "1", "2", ...

        Returns:
            A single grid PIL Image with numbered cells.
        """
        if not screenshots:
            return Image.new("RGB", (1, 1), "white")

        cols = min(cols, len(screenshots))
        rows = (len(screenshots) + cols - 1) // cols
        grid = Image.new(
            "RGB",
            (cols * cell_size[0], rows * cell_size[1]),
            "white",
        )

        for i, shot in enumerate(screenshots):
            r, c = divmod(i, cols)
            resized = shot.resize(cell_size)
            grid.paste(resized, (c * cell_size[0], r * cell_size[1]))

            label = labels[i] if labels else str(i + 1)
            self._draw_label(
                grid, c * cell_size[0], r * cell_size[1], label,
            )

        return grid

    def _draw_label(
        self,
        grid: Image.Image,
        x: int,
        y: int,
        label: str,
    ) -> None:
        """Draw a numbered label in the top-left corner of a cell."""
        draw = ImageDraw.Draw(grid)
        padding = 4
        font_size = 16

        try:
            font_path = (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            )
            font = ImageFont.truetype(font_path, font_size)
        except OSError:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        # Semi-transparent background
        draw.rectangle(
            [x, y, x + text_w + padding * 2, y + text_h + padding * 2],
            fill=(0, 0, 0, 180),
        )
        draw.text(
            (x + padding, y + padding),
            label,
            fill="white",
            font=font,
        )
