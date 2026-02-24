"""Image Batching — Screenshot preparation, grid creation, and candidate annotation.

Token cost: 0 (pure image processing, no API calls).

The image batcher handles all screenshot manipulation needed for VLM calls:
1. **prepare_screenshot** — Resize/compress a raw screenshot to a standard size.
2. **create_grid** — Stitch multiple screenshots into a grid for batch VLM analysis.
3. **annotate_candidates** — Draw numbered bounding boxes on a screenshot for VLM selection.
"""
from __future__ import annotations

import io
import logging
import math
from typing import Any

from src.core.types import ExtractedElement

logger = logging.getLogger(__name__)


def _import_pil() -> Any:
    """Import PIL with a helpful error message if not installed.

    Returns:
        The PIL.Image module.

    Raises:
        ImportError: If Pillow is not installed.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        return Image, ImageDraw, ImageFont
    except ImportError:
        raise ImportError(
            "Pillow is required for image processing. "
            "Install it with: pip install pillow>=10.0"
        )


class ImageBatcher:
    """Screenshot preparation and annotation for VLM analysis.

    Handles resizing, grid stitching, and candidate overlay annotation
    to prepare images for VLM API calls.

    Example::

        batcher = ImageBatcher()
        prepared = batcher.prepare_screenshot(raw_screenshot)
        grid = batcher.create_grid([img1, img2, img3, img4])
        annotated = batcher.annotate_candidates(screenshot, candidates)

    Args:
        max_batch_size: Maximum number of images in a grid.
        target_size: Target (width, height) for prepared screenshots.
    """

    def __init__(
        self,
        max_batch_size: int = 4,
        target_size: tuple[int, int] = (1024, 768),
    ) -> None:
        self._max_batch_size = max_batch_size
        self._target_size = target_size

    @property
    def max_batch_size(self) -> int:
        """Maximum number of images allowed in a grid."""
        return self._max_batch_size

    @property
    def target_size(self) -> tuple[int, int]:
        """Target size (width, height) for prepared screenshots."""
        return self._target_size

    def prepare_screenshot(self, raw_bytes: bytes) -> bytes:
        """Resize and compress a screenshot to the target size.

        Maintains aspect ratio by fitting within target dimensions and
        padding with a neutral background color.

        Args:
            raw_bytes: Raw screenshot image bytes (PNG or JPEG).

        Returns:
            Resized and compressed PNG image bytes.

        Raises:
            ValueError: If raw_bytes is empty or not a valid image.
        """
        if not raw_bytes:
            raise ValueError("Cannot prepare empty screenshot bytes")

        Image, _, _ = _import_pil()

        image = Image.open(io.BytesIO(raw_bytes))
        target_w, target_h = self._target_size

        # Resize maintaining aspect ratio.
        image.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)

        # Create canvas with neutral background and paste centered.
        canvas = Image.new("RGB", (target_w, target_h), (240, 240, 240))
        paste_x = (target_w - image.width) // 2
        paste_y = (target_h - image.height) // 2

        # Convert to RGB if needed (handle RGBA, palette, etc.).
        if image.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", image.size, (240, 240, 240))
            bg.paste(image, mask=image.split()[-1])
            image = bg
        elif image.mode != "RGB":
            image = image.convert("RGB")

        canvas.paste(image, (paste_x, paste_y))

        # Export as PNG.
        output = io.BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        return output.getvalue()

    def create_grid(self, images: list[bytes]) -> bytes:
        """Stitch multiple screenshots into a grid layout.

        Layout:
        - 1 image: single image (resized to target).
        - 2 images: 2x1 horizontal layout.
        - 3-4 images: 2x2 grid.
        - Excess images beyond max_batch_size are dropped.

        Args:
            images: List of screenshot image bytes.

        Returns:
            PNG bytes of the stitched grid image.

        Raises:
            ValueError: If no images are provided.
        """
        if not images:
            raise ValueError("Cannot create grid from empty image list")

        Image, ImageDraw, _ = _import_pil()

        # Limit to max batch size.
        batch = images[: self._max_batch_size]

        # Prepare each image.
        prepared: list[Any] = []
        for img_bytes in batch:
            img = Image.open(io.BytesIO(self.prepare_screenshot(img_bytes)))
            prepared.append(img)

        n = len(prepared)
        cell_w, cell_h = self._target_size

        if n == 1:
            # Single image — return as-is.
            return self.prepare_screenshot(images[0])

        if n == 2:
            # 2x1 horizontal layout.
            cols, rows = 2, 1
        else:
            # 2x2 grid.
            cols, rows = 2, 2

        grid_w = cols * cell_w
        grid_h = rows * cell_h
        grid = Image.new("RGB", (grid_w, grid_h), (200, 200, 200))

        for idx, img in enumerate(prepared):
            col = idx % cols
            row = idx // cols
            x = col * cell_w
            y = row * cell_h
            grid.paste(img, (x, y))

        # Draw grid lines and labels.
        draw = ImageDraw.Draw(grid)
        for idx in range(n):
            col = idx % cols
            row = idx // cols
            x = col * cell_w
            y = row * cell_h
            # Draw cell border.
            draw.rectangle([x, y, x + cell_w - 1, y + cell_h - 1], outline=(0, 0, 0), width=2)
            # Draw index label.
            draw.text((x + 5, y + 5), f"[{idx}]", fill=(255, 0, 0))

        output = io.BytesIO()
        grid.save(output, format="PNG")
        return output.getvalue()

    def annotate_candidates(
        self,
        screenshot: bytes,
        candidates: list[ExtractedElement],
    ) -> bytes:
        """Draw numbered bounding boxes on a screenshot for VLM selection.

        Each candidate's bounding box is drawn with a colored rectangle and
        a numbered label for the VLM to reference.

        Args:
            screenshot: Screenshot image bytes.
            candidates: List of candidate elements with bounding boxes.

        Returns:
            PNG bytes of the annotated screenshot.
        """
        Image, ImageDraw, _ = _import_pil()

        image = Image.open(io.BytesIO(screenshot))
        if image.mode != "RGB":
            image = image.convert("RGB")

        draw = ImageDraw.Draw(image)

        # Color palette for candidate boxes.
        colors = [
            (255, 0, 0),      # Red
            (0, 128, 0),      # Green
            (0, 0, 255),      # Blue
            (255, 165, 0),    # Orange
            (128, 0, 128),    # Purple
            (0, 128, 128),    # Teal
            (255, 0, 255),    # Magenta
            (128, 128, 0),    # Olive
        ]

        for idx, candidate in enumerate(candidates):
            x, y, w, h = candidate.bbox
            if w <= 0 or h <= 0:
                continue

            color = colors[idx % len(colors)]

            # Draw rectangle.
            draw.rectangle(
                [x, y, x + w, y + h],
                outline=color,
                width=2,
            )

            # Draw label background.
            label = f"[{idx}]"
            label_bbox = draw.textbbox((0, 0), label)
            label_w = label_bbox[2] - label_bbox[0] + 6
            label_h = label_bbox[3] - label_bbox[1] + 4
            draw.rectangle(
                [x, y - label_h, x + label_w, y],
                fill=color,
            )

            # Draw label text.
            draw.text(
                (x + 3, y - label_h + 2),
                label,
                fill=(255, 255, 255),
            )

        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


# ── Factory ─────────────────────────────────────────


def create_image_batcher(
    max_batch_size: int = 4,
    target_size: tuple[int, int] = (1024, 768),
) -> ImageBatcher:
    """Create and return a new ``ImageBatcher`` instance.

    Args:
        max_batch_size: Maximum batch size for grid creation.
        target_size: Target (width, height) for screenshot preparation.

    Returns:
        A configured ``ImageBatcher``.
    """
    return ImageBatcher(
        max_batch_size=max_batch_size,
        target_size=target_size,
    )
