"""CanvasExecutor — vision-only execution for Canvas pages.

No DOM selectors used. All interaction is coordinate-based:

1. UI-DETR-1 (LocalDetector) detects clickable regions (LLM 0 calls)
2. If single candidate → click directly
3. If multiple candidates → VLM chooses (selection problem, LLM 1 call)
4. If no candidates → VLM locates element from screenshot (LLM 1 call)
"""

from __future__ import annotations

import io
import json
import logging
import re
from typing import Protocol

from PIL import Image, ImageDraw, ImageFont

from src.vision.local_detector import Detection, LocalDetector

logger = logging.getLogger(__name__)


class ICanvasVLM(Protocol):
    """VLM interface for canvas element selection and location."""

    async def generate_with_image(
        self, prompt: str, image: bytes,
    ) -> str: ...


class ICanvasBrowser(Protocol):
    """Browser interface for canvas executor."""

    async def screenshot(self) -> bytes: ...
    async def mouse_click(self, x: int, y: int) -> None: ...
    async def get_viewport_size(self) -> dict[str, int]: ...


class CanvasExecutor:
    """Vision-only executor for Canvas pages.

    Usage:
        executor = CanvasExecutor(
            local_detector=detr_detector,
            vlm=gemini_flash,
        )
        success = await executor.find_and_click(browser, "검색 버튼")
    """

    def __init__(
        self,
        local_detector: LocalDetector,
        vlm: ICanvasVLM,
    ) -> None:
        self._detr = local_detector
        self._vlm = vlm

    async def find_and_click(
        self,
        browser: ICanvasBrowser,
        target_description: str,
    ) -> bool:
        """Find and click a target element on a Canvas page.

        Priority:
        1. UI-DETR-1 local detection (0 LLM calls)
        2. VLM screenshot analysis (1 LLM call)

        Args:
            browser: Browser instance.
            target_description: What to find and click.

        Returns:
            True if element was found and clicked.
        """
        screenshot_bytes = await browser.screenshot()
        screenshot = Image.open(io.BytesIO(screenshot_bytes))

        # --- Priority 1: Local detection ---
        detections = self._detr.detect(screenshot, threshold=0.3)

        if detections:
            if len(detections) == 1:
                # Single candidate → click directly (0 LLM calls)
                cx, cy = self._center(detections[0].box)
                await browser.mouse_click(cx, cy)
                return True

            # Multiple candidates → VLM selects (1 LLM call)
            annotated = self._annotate_candidates(
                screenshot, detections,
            )
            buf = io.BytesIO()
            annotated.save(buf, format="PNG")

            idx = await self._choose_element(
                buf.getvalue(),
                target_description,
                len(detections),
            )
            if idx is not None and 0 <= idx < len(detections):
                cx, cy = self._center(detections[idx].box)
                await browser.mouse_click(cx, cy)
                return True

        # --- Priority 2: VLM direct coordinate extraction ---
        xy = await self._locate_element(
            screenshot_bytes, target_description, screenshot.size,
        )
        if xy:
            await browser.mouse_click(xy[0], xy[1])
            return True

        logger.warning(
            "CanvasExecutor: failed to find '%s'", target_description,
        )
        return False

    async def _choose_element(
        self,
        annotated_image: bytes,
        target_description: str,
        num_candidates: int,
    ) -> int | None:
        """Ask VLM to choose among numbered candidates.

        Args:
            annotated_image: Screenshot with numbered bounding boxes.
            target_description: What to find.
            num_candidates: Total number of candidates.

        Returns:
            0-indexed chosen candidate, or None if parsing fails.
        """
        prompt = (
            f"이미지에서 빨간 박스로 {num_candidates}개의 UI 요소가"
            f" 표시되어 있습니다.\n"
            f"각 박스에 번호(0부터)가 붙어 있습니다.\n"
            f"'{target_description}'에 해당하는 요소의 번호를 선택하세요.\n"
            f"숫자만 답하세요."
        )
        response = await self._vlm.generate_with_image(
            prompt, annotated_image,
        )
        # Extract first integer from response
        match = re.search(r"\d+", response)
        if match:
            return int(match.group())
        return None

    async def _locate_element(
        self,
        screenshot_bytes: bytes,
        target_description: str,
        image_size: tuple[int, int],
    ) -> tuple[int, int] | None:
        """Ask VLM to directly locate element coordinates.

        Args:
            screenshot_bytes: Raw screenshot bytes.
            target_description: What to find.
            image_size: (width, height) of the screenshot.

        Returns:
            (x, y) pixel coordinates, or None if not found.
        """
        prompt = (
            f"이 스크린샷에서 '{target_description}'의 위치를 찾으세요.\n"
            f"이미지 크기: {image_size[0]}x{image_size[1]}\n"
            f"JSON으로 답하세요: {{\"x\": 픽셀X, \"y\": 픽셀Y}}"
        )
        response = await self._vlm.generate_with_image(
            prompt, screenshot_bytes,
        )

        # Try JSON parsing
        json_match = re.search(r"\{[^}]+\}", response)
        if json_match:
            try:
                data = json.loads(json_match.group())
                x = int(data.get("x", 0))
                y = int(data.get("y", 0))
                if 0 < x < image_size[0] and 0 < y < image_size[1]:
                    return (x, y)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        return None

    @staticmethod
    def _center(
        box: tuple[float, float, float, float],
    ) -> tuple[int, int]:
        """Calculate center point of a bounding box."""
        x1, y1, x2, y2 = box
        return int((x1 + x2) / 2), int((y1 + y2) / 2)

    @staticmethod
    def _annotate_candidates(
        screenshot: Image.Image,
        detections: list[Detection],
    ) -> Image.Image:
        """Draw numbered bounding boxes on screenshot for VLM selection."""
        img = screenshot.copy()
        draw = ImageDraw.Draw(img)

        try:
            font_path = (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            )
            font = ImageFont.truetype(font_path, 14)
        except OSError:
            font = ImageFont.load_default()

        for i, det in enumerate(detections):
            x1, y1, x2, y2 = det.box
            draw.rectangle(
                [x1, y1, x2, y2], outline="red", width=2,
            )
            draw.text((x1, max(0, y1 - 14)), str(i), fill="red", font=font)

        return img
