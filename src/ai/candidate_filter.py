"""2-stage candidate filter pipeline — structural filter + optional vector search.

Stage 1 (StructuralFilter): Always runs. Region classification + keyword ranking.
  - Zero cost, <5ms. Reduces 500+ elements → 20-80.

Stage 2 (VectorRanker): Conditional. Semantic vector similarity search.
  - Runs only when: ranker is available + candidates > threshold + intent is specific.
  - ~15ms. Reduces 30-80 → 5-10.

Falls back to the legacy keyword-only ranker when no filter is configured.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.core.structural_filter import StructuralFilter
from src.core.types import ExtractedElement

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilterResult:
    """Result of the 2-stage candidate filtering pipeline.

    Attributes:
        candidates: Filtered and ranked candidates.
        stage1_count: Number of candidates after Stage 1.
        stage2_count: Number of candidates after Stage 2 (0 if skipped).
        stage2_used: Whether Stage 2 (vector search) was applied.
    """

    candidates: list[ExtractedElement]
    stage1_count: int = 0
    stage2_count: int = 0
    stage2_used: bool = False


@runtime_checkable
class IVectorRanker(Protocol):
    """Protocol for Stage 2 vector-based rankers."""

    async def rank(
        self,
        candidates: Sequence[ExtractedElement],
        intent: str,
        top_k: int = 10,
    ) -> list[ExtractedElement]: ...


@dataclass
class CandidateFilterConfig:
    """Configuration for the candidate filter pipeline.

    Attributes:
        stage1_enabled: Whether Stage 1 (structural filter) is active.
        stage1_max: Max candidates after Stage 1.
        stage2_enabled: Whether Stage 2 (vector ranker) is active.
        stage2_top_k: How many candidates Stage 2 should return.
        vector_threshold: Minimum candidate count to trigger Stage 2.
        viewport_height: Viewport height for bbox classification.
    """

    stage1_enabled: bool = True
    stage1_max: int = 80
    stage2_enabled: bool = False
    stage2_top_k: int = 10
    vector_threshold: int = 15
    viewport_height: int = 1080


class CandidateFilterPipeline:
    """2-stage candidate filter: structural → optional vector search.

    Args:
        config: Pipeline configuration.
        structural_filter: Stage 1 filter (created from config if None).
        vector_ranker: Optional Stage 2 vector ranker.
    """

    def __init__(
        self,
        config: CandidateFilterConfig | None = None,
        structural_filter: StructuralFilter | None = None,
        vector_ranker: Any | None = None,  # IVectorRanker
    ) -> None:
        self._config = config or CandidateFilterConfig()
        self._structural = structural_filter or StructuralFilter(
            max_candidates=self._config.stage1_max,
            viewport_height=self._config.viewport_height,
        )
        self._vector_ranker = vector_ranker

    async def filter(
        self,
        candidates: Sequence[ExtractedElement],
        intent: str,
    ) -> FilterResult:
        """Run the 2-stage filter pipeline.

        Stage 1 always runs (if enabled). Stage 2 runs only when:
        - A vector ranker is available
        - Stage 2 is enabled in config
        - Post-Stage-1 candidate count exceeds vector_threshold

        Args:
            candidates: Raw extracted DOM elements.
            intent: User intent string.

        Returns:
            FilterResult with filtered candidates and pipeline metadata.
        """
        working = list(candidates)

        # Stage 1: Structural filter
        if self._config.stage1_enabled:
            working = self._structural.filter(working, intent)
            logger.debug(
                "Stage 1: %d → %d candidates", len(candidates), len(working),
            )
        stage1_count = len(working)

        # Stage 2: Vector search (conditional)
        stage2_used = False
        stage2_count = 0
        if (
            self._config.stage2_enabled
            and self._vector_ranker is not None
            and len(working) > self._config.vector_threshold
        ):
            try:
                working = await self._vector_ranker.rank(
                    working, intent, top_k=self._config.stage2_top_k,
                )
                stage2_used = True
                stage2_count = len(working)
                logger.debug(
                    "Stage 2: %d → %d candidates", stage1_count, stage2_count,
                )
            except Exception:
                logger.warning(
                    "Stage 2 vector ranking failed, using Stage 1 results",
                    exc_info=True,
                )

        return FilterResult(
            candidates=working,
            stage1_count=stage1_count,
            stage2_count=stage2_count,
            stage2_used=stage2_used,
        )


# ── Factory ─────────────────────────────────────────────


def create_candidate_filter(
    config: Any | None = None,
) -> CandidateFilterPipeline | None:
    """Create a CandidateFilterPipeline from engine config.

    Imports ``CandidateFilterConfig`` from ``src.core.config`` at runtime
    to avoid a name collision with the pipeline-level config in this module.

    Stage 1 (StructuralFilter) is always enabled by default.
    Stage 2 (VectorRanker) activates only when ``config.stage2.enabled``
    is True **and** the ``fastembed``/``hnswlib`` packages are installed.

    Args:
        config: ``CandidateFilterConfig`` from ``src.core.config``.
            If None, returns a default pipeline (Stage 1 only).

    Returns:
        A configured pipeline, or None if Stage 1 is explicitly disabled.
    """
    from src.core.config import CandidateFilterConfig as EngineFilterConfig

    if config is None:
        config = EngineFilterConfig()

    if not config.stage1.enabled:
        return None

    structural = StructuralFilter(max_candidates=config.stage1.max_candidates)

    ranker = None
    if config.stage2.enabled:
        try:
            from src.ai.vector_ranker import FastEmbedProvider, VectorRanker

            embedder = FastEmbedProvider(model_name=config.stage2.model)
            ranker = VectorRanker(embedder=embedder)
        except ImportError:
            logger.warning(
                "fastembed/hnswlib not installed — Stage 2 vector ranking disabled. "
                "Install with: pip install -e '.[embeddings]'",
            )

    pipeline_config = CandidateFilterConfig(
        stage1_max=config.stage1.max_candidates,
        stage2_enabled=config.stage2.enabled and ranker is not None,
        stage2_top_k=config.stage2.top_k,
        vector_threshold=config.stage2.vector_threshold,
    )

    return CandidateFilterPipeline(
        config=pipeline_config,
        structural_filter=structural,
        vector_ranker=ranker,
    )
