"""Tests for the Repeated Item Judgement Chain (YOLO→VLM pipeline)."""
from __future__ import annotations

import io
import os

import pytest
from PIL import Image

from src.vision.repeated_item_judgement import (
    execute_repeated_item_judgement,
)


def _make_test_image(
    color: str = "red", size: tuple[int, int] = (100, 100),
) -> bytes:
    """Create a small test image as bytes."""
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_yolo_accepted_skips_vlm(tmp_path: object) -> None:
    """YOLO accepts -> VLM not called, finalStatus=accepted."""
    images = [{"source_id": "s1", "data": _make_test_image("red")}]

    async def run_yolo(data: bytes) -> list[dict]:
        return [{"confidence": 0.9, "label": "item"}]

    vlm_called = False

    async def run_vlm(data: bytes, prompt: str) -> dict:
        nonlocal vlm_called
        vlm_called = True
        return {"accepted": True}

    result = await execute_repeated_item_judgement(
        images, str(tmp_path / "grid.png"), run_yolo, run_vlm,  # type: ignore[operator]
    )
    assert result.final_status == "accepted"
    assert result.yolo_accepted is True
    assert result.used_vlm_fallback is False
    assert not vlm_called


@pytest.mark.asyncio
async def test_yolo_rejected_no_vlm(tmp_path: object) -> None:
    """YOLO rejects, no VLM -> finalStatus=rejected."""
    images = [{"source_id": "s1", "data": _make_test_image()}]

    async def run_yolo(data: bytes) -> list[dict]:
        return [{"confidence": 0.3}]

    result = await execute_repeated_item_judgement(
        images, str(tmp_path / "grid.png"), run_yolo, run_vlm=None,  # type: ignore[operator]
    )
    assert result.final_status == "rejected"
    assert result.used_vlm_fallback is False


@pytest.mark.asyncio
async def test_yolo_rejected_vlm_accepted(tmp_path: object) -> None:
    """YOLO rejects + VLM accepts -> finalStatus=accepted, usedVlmFallback=True."""
    images = [{"source_id": "s1", "data": _make_test_image()}]

    async def run_yolo(data: bytes) -> list[dict]:
        return [{"confidence": 0.2}]

    async def run_vlm(data: bytes, prompt: str) -> dict:
        return {"accepted": True, "reason": "VLM sees items"}

    result = await execute_repeated_item_judgement(
        images, str(tmp_path / "grid.png"), run_yolo, run_vlm,  # type: ignore[operator]
    )
    assert result.final_status == "accepted"
    assert result.used_vlm_fallback is True
    assert result.vlm_result is not None
    assert result.vlm_result.accepted is True


@pytest.mark.asyncio
async def test_yolo_rejected_vlm_rejected(tmp_path: object) -> None:
    """YOLO rejects + VLM rejects -> finalStatus=rejected."""
    images = [{"source_id": "s1", "data": _make_test_image()}]

    async def run_yolo(data: bytes) -> list[dict]:
        return [{"confidence": 0.2}]

    async def run_vlm(data: bytes, prompt: str) -> dict:
        return {"accepted": False, "reason": "No repeated items"}

    result = await execute_repeated_item_judgement(
        images, str(tmp_path / "grid.png"), run_yolo, run_vlm,  # type: ignore[operator]
    )
    assert result.final_status == "rejected"
    assert result.used_vlm_fallback is True


@pytest.mark.asyncio
async def test_min_confidence_threshold(tmp_path: object) -> None:
    """Detections below min_confidence are not accepted."""
    images = [{"source_id": "s1", "data": _make_test_image()}]

    async def run_yolo(data: bytes) -> list[dict]:
        return [{"confidence": 0.54}]  # just below 0.55 default

    result = await execute_repeated_item_judgement(
        images, str(tmp_path / "grid.png"), run_yolo,  # type: ignore[operator]
    )
    assert result.yolo_accepted is False

    # With custom lower threshold
    result2 = await execute_repeated_item_judgement(
        images,
        str(tmp_path / "grid2.png"),  # type: ignore[operator]
        run_yolo,
        yolo_min_confidence=0.5,
    )
    assert result2.yolo_accepted is True


@pytest.mark.asyncio
async def test_empty_images(tmp_path: object) -> None:
    """Empty images list -> rejected."""

    async def run_yolo(data: bytes) -> list[dict]:
        return []

    result = await execute_repeated_item_judgement(
        [], str(tmp_path / "grid.png"), run_yolo,  # type: ignore[operator]
    )
    assert result.final_status == "rejected"
    assert "No images" in result.final_reason


@pytest.mark.asyncio
async def test_empty_detections(tmp_path: object) -> None:
    """YOLO returns no detections -> rejected."""
    images = [{"source_id": "s1", "data": _make_test_image()}]

    async def run_yolo(data: bytes) -> list[dict]:
        return []

    result = await execute_repeated_item_judgement(
        images, str(tmp_path / "grid.png"), run_yolo,  # type: ignore[operator]
    )
    assert result.yolo_accepted is False
    assert result.final_status == "rejected"


@pytest.mark.asyncio
async def test_composite_image_saved(tmp_path: object) -> None:
    """Grid image is saved to output path."""
    images = [
        {"source_id": "s1", "data": _make_test_image("red")},
        {"source_id": "s2", "data": _make_test_image("blue")},
    ]

    async def run_yolo(data: bytes) -> list[dict]:
        return [{"confidence": 0.9}]

    out_path = str(tmp_path / "grid.png")  # type: ignore[operator]
    result = await execute_repeated_item_judgement(images, out_path, run_yolo)
    assert os.path.exists(out_path)
    assert result.composite_image_path == out_path
