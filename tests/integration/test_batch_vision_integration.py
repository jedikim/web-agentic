"""Integration tests for batch vision pipeline with LLMFirstOrchestrator."""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from src.core.llm_orchestrator import LLMFirstOrchestrator
from src.core.types import (
    ExtractedElement,
    StepDefinition,
)
from src.vision.batch_vision_pipeline import BatchItemResult, BatchVisionPipeline, BatchVisionResult
from src.vision.image_batcher import CellInfo, GridMetadata

# ── Helpers ────────────────────────────────────────


def _make_png(w: int = 400, h: int = 320) -> bytes:
    img = Image.new("RGB", (w, h), (128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _product_candidates(n: int = 4) -> list[ExtractedElement]:
    """Create n similarly-sized product card candidates."""
    return [
        ExtractedElement(
            eid=f"product-{i}",
            type="card",
            text=None,  # image-only cards
            bbox=(i * 100, 0, 100, 200),
            visible=True,
            parent_context="product-grid",
        )
        for i in range(n)
    ]


def _simple_candidates() -> list[ExtractedElement]:
    """Candidates that should NOT trigger batch vision."""
    return [
        ExtractedElement(
            eid="btn-login", type="button", text="Login",
            bbox=(10, 10, 80, 30), visible=True,
        ),
        ExtractedElement(
            eid="btn-signup", type="button", text="Signup",
            bbox=(100, 10, 80, 30), visible=True,
        ),
    ]


def _make_batch_result() -> BatchVisionResult:
    meta = GridMetadata(
        cells=[CellInfo(
            index=0, source_bbox=(0, 0, 100, 200),
            grid_offset=(0, 0), cell_size=(100, 80),
        )],
        grid_size=(100, 80), cols=1, rows=1,
    )
    return BatchVisionResult(
        items=[
            BatchItemResult(
                cell_index=0, label="product", confidence=0.9,
                grid_bbox=(10, 10, 20, 20), page_bbox=(50, 100, 100, 200),
                source="yolo",
            ),
        ],
        grid_image=b"fake",
        grid_metadata=meta,
        yolo_used=True, vlm_used=False,
    )


def _make_orchestrator(batch_vision: BatchVisionPipeline | None = None) -> LLMFirstOrchestrator:
    executor = AsyncMock()
    executor.get_page.return_value = MagicMock()
    executor.screenshot.return_value = _make_png()

    extractor = AsyncMock()
    planner = AsyncMock()
    planner.usage = MagicMock(total_cost_usd=0.0, total_tokens=0)
    verifier = AsyncMock()

    return LLMFirstOrchestrator(
        executor=executor,
        extractor=extractor,
        planner=planner,
        verifier=verifier,
        screenshot_dir="/tmp/test_screenshots",
        batch_vision=batch_vision,
    )


# ── _should_use_batch_vision() Tests ──────────────


class TestShouldUseBatchVision:
    def test_product_intent_with_similar_candidates(self) -> None:
        """Product intent + similarly-sized candidates → True."""
        bv = MagicMock(spec=BatchVisionPipeline)
        orch = _make_orchestrator(batch_vision=bv)
        step = StepDefinition(step_id="s1", intent="가장 싼 상품 클릭")
        candidates = _product_candidates(4)
        assert orch._should_use_batch_vision(step, candidates) is True

    def test_english_product_keywords(self) -> None:
        bv = MagicMock(spec=BatchVisionPipeline)
        orch = _make_orchestrator(batch_vision=bv)
        step = StepDefinition(step_id="s1", intent="click the cheapest product")
        candidates = _product_candidates(4)
        assert orch._should_use_batch_vision(step, candidates) is True

    def test_simple_click_returns_false(self) -> None:
        """Simple click intent without batch keywords → False."""
        bv = MagicMock(spec=BatchVisionPipeline)
        orch = _make_orchestrator(batch_vision=bv)
        step = StepDefinition(step_id="s1", intent="로그인 버튼 클릭")
        candidates = _simple_candidates()
        assert orch._should_use_batch_vision(step, candidates) is False

    def test_no_batch_vision_returns_false(self) -> None:
        """Without batch_vision configured → always False."""
        orch = _make_orchestrator(batch_vision=None)
        step = StepDefinition(step_id="s1", intent="가장 싼 상품 클릭")
        candidates = _product_candidates(4)
        assert orch._should_use_batch_vision(step, candidates) is False

    def test_too_few_candidates_returns_false(self) -> None:
        """Fewer than 3 candidates → False."""
        bv = MagicMock(spec=BatchVisionPipeline)
        orch = _make_orchestrator(batch_vision=bv)
        step = StepDefinition(step_id="s1", intent="compare products")
        candidates = _product_candidates(2)
        assert orch._should_use_batch_vision(step, candidates) is False

    def test_batch_select_node_type_always_true(self) -> None:
        """node_type='batch_select' triggers batch vision regardless of keywords."""
        bv = MagicMock(spec=BatchVisionPipeline)
        orch = _make_orchestrator(batch_vision=bv)
        step = StepDefinition(step_id="s1", intent="select something", node_type="batch_select")
        # Even simple candidates should trigger with batch_select hint.
        candidates = _simple_candidates()
        assert orch._should_use_batch_vision(step, candidates) is True

    def test_dissimilar_sizes_returns_false(self) -> None:
        """Candidates with very different heights → False."""
        bv = MagicMock(spec=BatchVisionPipeline)
        orch = _make_orchestrator(batch_vision=bv)
        step = StepDefinition(step_id="s1", intent="compare products")
        # Heights: 50, 200, 300 — very different
        candidates = [
            ExtractedElement(eid="a", type="card", bbox=(0, 0, 100, 50), visible=True),
            ExtractedElement(eid="b", type="card", bbox=(0, 0, 100, 200), visible=True),
            ExtractedElement(eid="c", type="card", bbox=(0, 0, 100, 300), visible=True),
        ]
        assert orch._should_use_batch_vision(step, candidates) is False


# ── _execute_step_with_batch_vision() Tests ───────


class TestExecuteStepWithBatchVision:
    @pytest.mark.asyncio
    async def test_end_to_end_mocked(self) -> None:
        """Full pipeline runs through batch vision with all mocks."""
        bv = AsyncMock(spec=BatchVisionPipeline)
        bv.process_batch.return_value = _make_batch_result()

        orch = _make_orchestrator(batch_vision=bv)
        page_mock = orch._executor.get_page.return_value
        page_mock.mouse = AsyncMock()

        step = StepDefinition(step_id="s1", intent="가장 싼 상품 클릭")
        candidates = _product_candidates(4)

        import time
        result = await orch._execute_step_with_batch_vision(step, candidates, time.perf_counter())

        assert result.success is True
        assert result.method == "BV"
        # Verify click was called with centre of best item's page_bbox (50+50, 100+100)
        page_mock.mouse.click.assert_called_once_with(100, 200)

    @pytest.mark.asyncio
    async def test_batch_vision_fallback_on_empty_result(self) -> None:
        """Empty batch result returns failure."""
        meta = GridMetadata(cells=[], grid_size=(0, 0), cols=0, rows=0)
        bv = AsyncMock(spec=BatchVisionPipeline)
        bv.process_batch.return_value = BatchVisionResult(
            items=[], grid_image=b"", grid_metadata=meta,
            yolo_used=True, vlm_used=False,
        )

        orch = _make_orchestrator(batch_vision=bv)
        step = StepDefinition(step_id="s1", intent="find product")
        candidates = _product_candidates(4)

        import time
        result = await orch._execute_step_with_batch_vision(step, candidates, time.perf_counter())

        assert result.success is False
        assert result.method == "BV"

    @pytest.mark.asyncio
    async def test_batch_vision_picks_relevant_item(self) -> None:
        """Pipeline picks the relevant VLM item with highest confidence."""
        meta = GridMetadata(
            cells=[
                CellInfo(
                    index=0, source_bbox=(0, 0, 100, 200),
                    grid_offset=(0, 0), cell_size=(100, 80),
                ),
                CellInfo(
                    index=1, source_bbox=(100, 0, 100, 200),
                    grid_offset=(100, 0), cell_size=(100, 80),
                ),
            ],
            grid_size=(200, 80), cols=2, rows=1,
        )
        bv = AsyncMock(spec=BatchVisionPipeline)
        bv.process_batch.return_value = BatchVisionResult(
            items=[
                BatchItemResult(
                    cell_index=0, label="hat", confidence=0.95,
                    grid_bbox=(0, 0, 0, 0), page_bbox=(0, 0, 100, 200),
                    source="vlm", extra={"relevant": False},
                ),
                BatchItemResult(
                    cell_index=1, label="shoes", confidence=0.88,
                    grid_bbox=(0, 0, 0, 0), page_bbox=(100, 0, 100, 200),
                    source="vlm", extra={"relevant": True},
                ),
            ],
            grid_image=b"grid", grid_metadata=meta,
            yolo_used=False, vlm_used=True,
        )

        orch = _make_orchestrator(batch_vision=bv)
        page_mock = orch._executor.get_page.return_value
        page_mock.mouse = AsyncMock()

        step = StepDefinition(step_id="s1", intent="find shoes")
        candidates = _product_candidates(2)

        import time
        result = await orch._execute_step_with_batch_vision(step, candidates, time.perf_counter())

        assert result.success is True
        # Should click centre of shoes item (100 + 50, 0 + 100)
        page_mock.mouse.click.assert_called_once_with(150, 100)
