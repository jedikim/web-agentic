"""BatchVerifier — verify multiple items with a single VLM call.

Instead of calling VLM N times for N items, combines screenshots
into a grid image and asks VLM once. Saves cost ~95% for 20 items.

Usage:
    verifier = BatchVerifier(vlm=gemini_flash, composer=GridComposer())
    results = await verifier.verify_items(
        screenshots, "이 상품들이 등산복인가?"
    )
    # results = [True, True, False, True, ...]
"""

from __future__ import annotations

import io
import json
import logging
import re
from typing import Protocol

from PIL import Image

from src.vision.grid_composer import GridComposer

logger = logging.getLogger(__name__)

_BATCH_VERIFY_PROMPT = """\
이미지는 {count}개 아이템의 그리드입니다.
각 셀에 번호가 있습니다.
질문: {question}
각 번호에 대해 Y(예) 또는 N(아니오)로 답하세요.
형식: 1:Y, 2:N, 3:Y, ..."""


class IBatchVLM(Protocol):
    """VLM interface for batch verification."""

    async def generate_with_image(
        self, prompt: str, image: bytes,
    ) -> str: ...


class BatchVerifier:
    """Verify multiple items using grid image + single VLM call.

    Two verification modes:
    - verify_items: Takes pre-captured screenshots
    - verify_with_question: Takes screenshots + semantic question
    """

    def __init__(
        self,
        vlm: IBatchVLM,
        composer: GridComposer | None = None,
    ) -> None:
        self._vlm = vlm
        self._composer = composer or GridComposer()

    async def verify_items(
        self,
        screenshots: list[Image.Image],
        question: str,
        cols: int = 4,
    ) -> list[bool]:
        """Verify multiple items with a single VLM call.

        Args:
            screenshots: List of item screenshots.
            question: Verification question for VLM.
            cols: Grid columns.

        Returns:
            List of bool results, one per item.
        """
        if not screenshots:
            return []

        grid = self._composer.compose(screenshots, cols=cols)

        # Convert grid to bytes
        buf = io.BytesIO()
        grid.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        prompt = _BATCH_VERIFY_PROMPT.format(
            count=len(screenshots),
            question=question,
        )

        response = await self._vlm.generate_with_image(
            prompt, image_bytes,
        )

        return self._parse_yn(response, len(screenshots))

    def _parse_yn(
        self, response: str, expected_count: int,
    ) -> list[bool]:
        """Parse VLM Y/N response into list of bools.

        Handles formats like:
        - "1:Y, 2:N, 3:Y"
        - "1: Y\\n2: N\\n3: Y"
        - JSON array: [true, false, true]

        Args:
            response: VLM response text.
            expected_count: Expected number of results.

        Returns:
            List of booleans. Defaults to False for unparsed items.
        """
        results = [False] * expected_count

        # Try JSON array first
        try:
            data = json.loads(response)
            if isinstance(data, list):
                for i, v in enumerate(data[:expected_count]):
                    results[i] = bool(v)
                return results
        except (json.JSONDecodeError, ValueError):
            pass

        # Try "N:Y/N" pattern
        pattern = re.findall(r"(\d+)\s*:\s*([YyNn])", response)
        if pattern:
            for num_str, yn in pattern:
                idx = int(num_str) - 1  # 1-indexed to 0-indexed
                if 0 <= idx < expected_count:
                    results[idx] = yn.upper() == "Y"
            return results

        # Fallback: count Y/N tokens
        tokens = re.findall(r"[YyNn]", response)
        for i, token in enumerate(tokens[:expected_count]):
            results[i] = token.upper() == "Y"

        return results
