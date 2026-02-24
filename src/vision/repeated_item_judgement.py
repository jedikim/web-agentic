"""Repeated Item Judgement Chain — YOLO→VLM pipeline for repeated item detection.

Detects repeated items (search results, product lists) using a two-phase approach:
1. Create a composite grid image from individual item screenshots.
2. Run YOLO detection on the grid.
3. If YOLO confidence is below threshold, fall back to VLM for semantic judgement.
"""
from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.vision.image_batcher import create_grid_from_images


@dataclass(frozen=True)
class YoloJudgementResult:
    """Result from YOLO detection phase."""

    detections: list[dict]
    accepted: bool | None = None
    reason: str | None = None


@dataclass(frozen=True)
class VlmJudgementResult:
    """Result from VLM fallback phase."""

    accepted: bool
    reason: str | None = None
    selected_source_ids: list[str] | None = None


@dataclass(frozen=True)
class JudgementResult:
    """Full result of the repeated item judgement chain."""

    composite_image_path: str
    yolo_result: YoloJudgementResult
    mapped_detections: list[dict]
    yolo_accepted: bool
    yolo_decision_reason: str
    used_vlm_fallback: bool
    vlm_result: VlmJudgementResult | None
    final_status: str  # "accepted" | "rejected"
    final_reason: str


# Type aliases
YoloRunner = Callable[[bytes], Awaitable[list[dict]]]
VlmRunner = Callable[[bytes, str], Awaitable[dict]]


async def execute_repeated_item_judgement(
    images: list[dict],  # [{"source_id": str, "data": bytes}]
    output_image_path: str,
    run_yolo: YoloRunner,
    run_vlm: VlmRunner | None = None,
    yolo_min_confidence: float = 0.55,
    columns: int = 4,
    cell_width: int = 200,
    cell_height: int = 200,
) -> JudgementResult:
    """Execute repeated item judgement chain: grid -> YOLO -> (optional) VLM.

    Args:
        images: List of dicts with ``source_id`` and ``data`` (bytes) keys.
        output_image_path: Path to save composite grid image.
        run_yolo: Async callable: (image_bytes) -> list[dict] with 'confidence' key.
        run_vlm: Optional async callable: (image_bytes, prompt) -> dict with 'accepted' key.
        yolo_min_confidence: Minimum confidence threshold for YOLO acceptance.
        columns: Grid columns.
        cell_width: Cell width in pixels.
        cell_height: Cell height in pixels.

    Returns:
        JudgementResult with full chain results.
    """
    # 1. Create composite grid image
    image_bytes_list = [img["data"] for img in images]
    if not image_bytes_list:
        return JudgementResult(
            composite_image_path=output_image_path,
            yolo_result=YoloJudgementResult(
                detections=[], accepted=False, reason="No images provided",
            ),
            mapped_detections=[],
            yolo_accepted=False,
            yolo_decision_reason="No images provided",
            used_vlm_fallback=False,
            vlm_result=None,
            final_status="rejected",
            final_reason="No images provided",
        )

    grid_bytes = create_grid_from_images(
        image_bytes_list, columns, cell_width, cell_height,
    )

    # Save composite image
    os.makedirs(os.path.dirname(output_image_path) or ".", exist_ok=True)
    with open(output_image_path, "wb") as f:
        f.write(grid_bytes)

    # 2. Run YOLO detection
    detections = await run_yolo(grid_bytes)

    # Map detections back to source images
    mapped_detections: list[dict] = []
    for det in detections:
        mapped = dict(det)
        if "bbox" in det:
            x, y = det["bbox"][0], det["bbox"][1]
            col = x // cell_width
            row = y // cell_height
            idx = row * columns + col
            if idx < len(images):
                mapped["source_id"] = images[idx]["source_id"]
        mapped_detections.append(mapped)

    # 3. Evaluate YOLO results
    confident_detections = [
        d for d in detections if d.get("confidence", 0) >= yolo_min_confidence
    ]
    yolo_accepted = len(confident_detections) > 0
    yolo_reason = (
        f"{len(confident_detections)} detections above {yolo_min_confidence} confidence"
        if yolo_accepted
        else f"No detections above {yolo_min_confidence} confidence ({len(detections)} total)"
    )

    yolo_result = YoloJudgementResult(
        detections=detections,
        accepted=yolo_accepted,
        reason=yolo_reason,
    )

    # 4. If YOLO accepted, return immediately
    if yolo_accepted:
        return JudgementResult(
            composite_image_path=output_image_path,
            yolo_result=yolo_result,
            mapped_detections=mapped_detections,
            yolo_accepted=True,
            yolo_decision_reason=yolo_reason,
            used_vlm_fallback=False,
            vlm_result=None,
            final_status="accepted",
            final_reason=f"YOLO accepted: {yolo_reason}",
        )

    # 5. YOLO rejected -- try VLM fallback if available
    if run_vlm is not None:
        vlm_response = await run_vlm(
            grid_bytes, "Are there repeated items in this grid image?",
        )
        vlm_accepted = vlm_response.get("accepted", False)
        vlm_result = VlmJudgementResult(
            accepted=vlm_accepted,
            reason=vlm_response.get("reason"),
            selected_source_ids=vlm_response.get("selected_source_ids"),
        )
        final_status = "accepted" if vlm_accepted else "rejected"
        final_reason = (
            f"VLM {'accepted' if vlm_accepted else 'rejected'}: "
            f"{vlm_result.reason or 'no reason'}"
        )

        return JudgementResult(
            composite_image_path=output_image_path,
            yolo_result=yolo_result,
            mapped_detections=mapped_detections,
            yolo_accepted=False,
            yolo_decision_reason=yolo_reason,
            used_vlm_fallback=True,
            vlm_result=vlm_result,
            final_status=final_status,
            final_reason=final_reason,
        )

    # 6. No VLM -> rejected
    return JudgementResult(
        composite_image_path=output_image_path,
        yolo_result=yolo_result,
        mapped_detections=mapped_detections,
        yolo_accepted=False,
        yolo_decision_reason=yolo_reason,
        used_vlm_fallback=False,
        vlm_result=None,
        final_status="rejected",
        final_reason=f"YOLO rejected and no VLM fallback: {yolo_reason}",
    )
