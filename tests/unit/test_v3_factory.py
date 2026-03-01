"""Tests for v3 pipeline factory."""

from __future__ import annotations

from unittest.mock import AsyncMock

from src.core.cache import InMemoryCacheDB
from src.core.config import CanvasConfig, EngineConfig, V3PipelineConfig
from src.core.v3_factory import V3Pipeline, create_v3_pipeline
from src.core.v3_orchestrator import V3Orchestrator
from src.learning.site_knowledge import SiteKnowledgeStore
from src.vision.canvas_detector import CanvasDetector
from src.vision.canvas_executor import CanvasExecutor
from src.vision.visual_judge import VisualJudge


class TestCreateV3Pipeline:
    def test_creates_pipeline_with_defaults(self) -> None:
        vlm = AsyncMock()
        text = AsyncMock()
        pipeline = create_v3_pipeline(
            vlm_adapter=vlm, text_adapter=text,
        )
        assert isinstance(pipeline, V3Pipeline)
        assert isinstance(pipeline.orchestrator, V3Orchestrator)
        assert isinstance(pipeline.canvas_detector, CanvasDetector)
        assert isinstance(pipeline.canvas_executor, CanvasExecutor)

    def test_creates_pipeline_with_config(self) -> None:
        config = EngineConfig(
            v3_pipeline=V3PipelineConfig(
                cache_ttl_days=7,
                max_retry_per_step=5,
            ),
        )
        vlm = AsyncMock()
        text = AsyncMock()
        pipeline = create_v3_pipeline(
            config=config, vlm_adapter=vlm, text_adapter=text,
        )
        assert pipeline.config.v3_pipeline.cache_ttl_days == 7

    def test_custom_cache_db(self) -> None:
        db = InMemoryCacheDB()
        vlm = AsyncMock()
        text = AsyncMock()
        pipeline = create_v3_pipeline(
            cache_db=db, vlm_adapter=vlm, text_adapter=text,
        )
        assert pipeline.orchestrator is not None

    def test_canvas_threshold_applied(self) -> None:
        config = EngineConfig(
            canvas=CanvasConfig(canvas_threshold=10),
        )
        vlm = AsyncMock()
        text = AsyncMock()
        pipeline = create_v3_pipeline(
            config=config, vlm_adapter=vlm, text_adapter=text,
        )
        assert pipeline.canvas_detector.CANVAS_THRESHOLD == 10

    def test_pipeline_has_all_components(self) -> None:
        vlm = AsyncMock()
        text = AsyncMock()
        pipeline = create_v3_pipeline(
            vlm_adapter=vlm, text_adapter=text,
        )
        assert pipeline.orchestrator is not None
        assert pipeline.canvas_detector is not None
        assert pipeline.canvas_executor is not None
        assert pipeline.retry_handler is not None
        assert pipeline.skill_synthesizer is not None
        assert pipeline.config is not None

    def test_orchestrator_has_visual_judge(self) -> None:
        vlm = AsyncMock()
        text = AsyncMock()
        pipeline = create_v3_pipeline(vlm_adapter=vlm, text_adapter=text)
        assert pipeline.orchestrator.visual_judge is not None
        assert isinstance(pipeline.orchestrator.visual_judge, VisualJudge)

    def test_orchestrator_has_site_knowledge(self) -> None:
        vlm = AsyncMock()
        text = AsyncMock()
        pipeline = create_v3_pipeline(vlm_adapter=vlm, text_adapter=text)
        assert pipeline.orchestrator.site_knowledge is not None
        assert isinstance(pipeline.orchestrator.site_knowledge, SiteKnowledgeStore)
