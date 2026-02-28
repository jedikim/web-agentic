"""Tests for BatchVerifier — multi-item VLM verification."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from PIL import Image

from src.vision.batch_verifier import BatchVerifier
from src.vision.grid_composer import GridComposer


@pytest.fixture
def mock_vlm() -> AsyncMock:
    vlm = AsyncMock()
    vlm.generate_with_image = AsyncMock(
        return_value="1:Y, 2:Y, 3:N, 4:Y"
    )
    return vlm


@pytest.fixture
def verifier(mock_vlm: AsyncMock) -> BatchVerifier:
    return BatchVerifier(vlm=mock_vlm, composer=GridComposer())


def _make_imgs(n: int = 4) -> list[Image.Image]:
    colors = ["red", "blue", "green", "yellow", "purple", "orange"]
    return [
        Image.new("RGB", (100, 100), colors[i % len(colors)])
        for i in range(n)
    ]


class TestVerifyItems:
    async def test_basic_verification(
        self, verifier: BatchVerifier,
    ) -> None:
        results = await verifier.verify_items(
            _make_imgs(4), "이 상품들이 등산복인가?",
        )
        assert results == [True, True, False, True]

    async def test_empty_list(
        self, verifier: BatchVerifier,
    ) -> None:
        results = await verifier.verify_items([], "question")
        assert results == []

    async def test_single_item(
        self, mock_vlm: AsyncMock,
    ) -> None:
        mock_vlm.generate_with_image = AsyncMock(return_value="1:Y")
        verifier = BatchVerifier(vlm=mock_vlm)
        results = await verifier.verify_items(
            _make_imgs(1), "맞나요?",
        )
        assert results == [True]

    async def test_20_items(
        self, mock_vlm: AsyncMock,
    ) -> None:
        # Simulate 20-item response
        yn_str = ", ".join(
            f"{i+1}:{'Y' if i % 3 != 0 else 'N'}"
            for i in range(20)
        )
        mock_vlm.generate_with_image = AsyncMock(return_value=yn_str)
        verifier = BatchVerifier(vlm=mock_vlm)
        results = await verifier.verify_items(
            _make_imgs(20), "등산복인가?", cols=4,
        )
        assert len(results) == 20
        assert results[0] is False  # 1 → N (0%3==0)
        assert results[1] is True   # 2 → Y
        assert results[3] is False  # 4 → N (3%3==0)

    async def test_vlm_called_once(
        self, verifier: BatchVerifier, mock_vlm: AsyncMock,
    ) -> None:
        await verifier.verify_items(_make_imgs(10), "question")
        assert mock_vlm.generate_with_image.call_count == 1

    async def test_prompt_includes_count(
        self, verifier: BatchVerifier, mock_vlm: AsyncMock,
    ) -> None:
        await verifier.verify_items(_make_imgs(5), "등산복인가?")
        prompt = mock_vlm.generate_with_image.call_args[0][0]
        assert "5개" in prompt
        assert "등산복인가?" in prompt


class TestParseYN:
    def test_standard_format(self, verifier: BatchVerifier) -> None:
        result = verifier._parse_yn("1:Y, 2:N, 3:Y", 3)
        assert result == [True, False, True]

    def test_with_spaces(self, verifier: BatchVerifier) -> None:
        result = verifier._parse_yn("1: Y, 2: N, 3: Y", 3)
        assert result == [True, False, True]

    def test_newline_separated(self, verifier: BatchVerifier) -> None:
        result = verifier._parse_yn("1:Y\n2:N\n3:Y", 3)
        assert result == [True, False, True]

    def test_json_array(self, verifier: BatchVerifier) -> None:
        result = verifier._parse_yn("[true, false, true]", 3)
        assert result == [True, False, True]

    def test_lowercase_yn(self, verifier: BatchVerifier) -> None:
        result = verifier._parse_yn("1:y, 2:n, 3:y", 3)
        assert result == [True, False, True]

    def test_missing_items_default_false(
        self, verifier: BatchVerifier,
    ) -> None:
        # Only 2 items in response but expect 4
        result = verifier._parse_yn("1:Y, 2:N", 4)
        assert result == [True, False, False, False]

    def test_empty_response(self, verifier: BatchVerifier) -> None:
        result = verifier._parse_yn("", 3)
        assert result == [False, False, False]

    def test_fallback_yn_tokens(
        self, verifier: BatchVerifier,
    ) -> None:
        # Plain Y/N without numbers
        result = verifier._parse_yn("Y N Y", 3)
        assert result == [True, False, True]

    def test_extra_items_truncated(
        self, verifier: BatchVerifier,
    ) -> None:
        result = verifier._parse_yn(
            "1:Y, 2:Y, 3:Y, 4:Y, 5:Y", 3,
        )
        assert len(result) == 3
        assert result == [True, True, True]
