"""Unit tests for 2-stage candidate filter pipeline."""
from __future__ import annotations

from unittest.mock import AsyncMock

from src.ai.candidate_filter import (
    CandidateFilterConfig,
    CandidateFilterPipeline,
    FilterResult,
)
from src.core.structural_filter import StructuralFilter
from src.core.types import ExtractedElement


def _el(
    eid: str = "el",
    text: str | None = None,
    bbox: tuple[int, int, int, int] = (0, 300, 100, 40),
    landmark: str | None = None,
) -> ExtractedElement:
    return ExtractedElement(
        eid=eid, type="button", text=text,
        bbox=bbox, visible=True, landmark=landmark,
    )


def _make_candidates(n: int) -> list[ExtractedElement]:
    return [_el(eid=f"el-{i}", text=f"Element {i}") for i in range(n)]


class TestCandidateFilterPipeline:
    """Tests for CandidateFilterPipeline."""

    async def test_stage1_only(self) -> None:
        """With default config (stage2 disabled), only Stage 1 runs."""
        pipeline = CandidateFilterPipeline()
        candidates = _make_candidates(100)
        result = await pipeline.filter(candidates, "search")
        assert isinstance(result, FilterResult)
        assert len(result.candidates) <= 80
        assert result.stage1_count <= 80
        assert result.stage2_used is False
        assert result.stage2_count == 0

    async def test_passthrough_when_small(self) -> None:
        """Few candidates should pass through Stage 1 unchanged."""
        pipeline = CandidateFilterPipeline()
        candidates = _make_candidates(5)
        result = await pipeline.filter(candidates, "click button")
        assert len(result.candidates) == 5

    async def test_stage2_triggered_when_configured(self) -> None:
        """Stage 2 should run when enabled and ranker is available."""
        mock_ranker = AsyncMock()
        mock_ranker.rank = AsyncMock(return_value=[_el(eid="top-1"), _el(eid="top-2")])

        config = CandidateFilterConfig(
            stage2_enabled=True,
            stage2_top_k=5,
            vector_threshold=10,
        )
        pipeline = CandidateFilterPipeline(config=config, vector_ranker=mock_ranker)
        candidates = _make_candidates(50)
        result = await pipeline.filter(candidates, "search for laptop")
        assert result.stage2_used is True
        assert result.stage2_count == 2
        mock_ranker.rank.assert_awaited_once()

    async def test_stage2_skipped_below_threshold(self) -> None:
        """Stage 2 should NOT run when candidates <= threshold."""
        mock_ranker = AsyncMock()
        mock_ranker.rank = AsyncMock(return_value=[])

        config = CandidateFilterConfig(
            stage1_max=10,
            stage2_enabled=True,
            vector_threshold=15,
        )
        pipeline = CandidateFilterPipeline(config=config, vector_ranker=mock_ranker)
        candidates = _make_candidates(20)
        result = await pipeline.filter(candidates, "click")
        # After Stage 1 limits to 10, which is < threshold 15
        assert result.stage2_used is False
        mock_ranker.rank.assert_not_awaited()

    async def test_stage2_skipped_without_ranker(self) -> None:
        """Stage 2 should NOT run without a vector ranker."""
        config = CandidateFilterConfig(stage2_enabled=True)
        pipeline = CandidateFilterPipeline(config=config, vector_ranker=None)
        candidates = _make_candidates(100)
        result = await pipeline.filter(candidates, "search")
        assert result.stage2_used is False

    async def test_stage2_failure_falls_back_to_stage1(self) -> None:
        """If Stage 2 raises, fall back to Stage 1 results."""
        mock_ranker = AsyncMock()
        mock_ranker.rank = AsyncMock(side_effect=RuntimeError("embedding failed"))

        config = CandidateFilterConfig(
            stage2_enabled=True,
            vector_threshold=5,
        )
        pipeline = CandidateFilterPipeline(config=config, vector_ranker=mock_ranker)
        candidates = _make_candidates(50)
        result = await pipeline.filter(candidates, "search for laptop")
        assert result.stage2_used is False
        assert len(result.candidates) > 0  # Stage 1 results preserved

    async def test_stage1_disabled(self) -> None:
        """When Stage 1 is disabled, all candidates pass through."""
        config = CandidateFilterConfig(stage1_enabled=False)
        pipeline = CandidateFilterPipeline(config=config)
        candidates = _make_candidates(200)
        result = await pipeline.filter(candidates, "search")
        assert len(result.candidates) == 200

    async def test_custom_structural_filter(self) -> None:
        """Can inject a custom StructuralFilter instance."""
        sf = StructuralFilter(max_candidates=3)
        pipeline = CandidateFilterPipeline(structural_filter=sf)
        candidates = _make_candidates(50)
        result = await pipeline.filter(candidates, "search")
        assert len(result.candidates) <= 3

    async def test_config_defaults(self) -> None:
        """Default config should have sensible values."""
        config = CandidateFilterConfig()
        assert config.stage1_enabled is True
        assert config.stage1_max == 80
        assert config.stage2_enabled is False
        assert config.stage2_top_k == 10
        assert config.vector_threshold == 15

    async def test_stage2_receives_correct_top_k(self) -> None:
        """Stage 2 should pass top_k from config."""
        mock_ranker = AsyncMock()
        mock_ranker.rank = AsyncMock(return_value=[_el(eid="r")])

        config = CandidateFilterConfig(
            stage2_enabled=True,
            stage2_top_k=7,
            vector_threshold=5,
        )
        pipeline = CandidateFilterPipeline(config=config, vector_ranker=mock_ranker)
        candidates = _make_candidates(50)
        await pipeline.filter(candidates, "find product")
        _, kwargs = mock_ranker.rank.call_args
        assert kwargs["top_k"] == 7
