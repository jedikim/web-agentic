"""V3 Pipeline Factory — assemble the full orchestrator from config.

Creates all v3 components with proper DI wiring:
  Planner, DOMExtractor, ElementFilter, Actor, V3Executor,
  Cache, ResultVerifier, RetryHandler, CanvasDetector, CanvasExecutor.

Usage:
    from src.core.config import load_config
    from src.core.v3_factory import create_v3_pipeline

    config = load_config()
    pipeline = create_v3_pipeline(config)
    # pipeline.orchestrator, pipeline.canvas_detector, etc.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.core.actor import Actor
from src.core.cache import Cache, InMemoryCacheDB
from src.core.config import EngineConfig
from src.core.dom_extractor import DOMExtractor
from src.core.element_filter import ElementFilter
from src.core.planner import Planner
from src.core.result_verifier import ResultVerifier
from src.core.retry_handler import RetryHandler
from src.core.skill_synthesizer import SkillSynthesizer
from src.core.text_matcher import TextMatcher
from src.core.v3_adapters import GeminiTextAdapter, GeminiVisionAdapter
from src.core.v3_executor import V3Executor
from src.core.v3_orchestrator import V3Orchestrator
from src.vision.canvas_detector import CanvasDetector
from src.vision.canvas_executor import CanvasExecutor
from src.vision.local_detector import LocalDetector

logger = logging.getLogger(__name__)


@dataclass
class V3Pipeline:
    """Container for all v3 pipeline components.

    Attributes:
        orchestrator: Main execution loop.
        canvas_detector: Canvas page detection.
        canvas_executor: Vision-only Canvas execution.
        retry_handler: VLM-assisted retry.
        skill_synthesizer: Trajectory → Python function.
        config: Engine configuration used.
    """

    orchestrator: V3Orchestrator
    canvas_detector: CanvasDetector
    canvas_executor: CanvasExecutor
    retry_handler: RetryHandler
    skill_synthesizer: SkillSynthesizer
    config: EngineConfig


def create_v3_pipeline(
    config: EngineConfig | None = None,
    cache_db: Any | None = None,
    vlm_adapter: Any | None = None,
    text_adapter: Any | None = None,
) -> V3Pipeline:
    """Create a fully wired v3 pipeline from configuration.

    Args:
        config: Engine configuration. Uses defaults if None.
        cache_db: Cache database implementation. InMemoryCacheDB if None.
        vlm_adapter: Vision LLM adapter. Auto-created from config if None.
        text_adapter: Text LLM adapter. Auto-created from config if None.

    Returns:
        V3Pipeline with all components ready to use.
    """
    if config is None:
        config = EngineConfig()

    # LLM adapters
    if vlm_adapter is None:
        vlm_adapter = GeminiVisionAdapter(
            model=config.llm.flash_model,
        )
    if text_adapter is None:
        text_adapter = GeminiTextAdapter(
            model=config.llm.flash_model,
        )

    pro_text_adapter = GeminiTextAdapter(
        model=config.llm.pro_model,
    )

    # Core v3 components
    planner = Planner(vlm=vlm_adapter)
    extractor = DOMExtractor()
    text_matcher = TextMatcher()
    element_filter = ElementFilter(matcher=text_matcher)
    actor = Actor(llm=text_adapter)
    executor = V3Executor()
    verifier = ResultVerifier()

    # Cache
    if cache_db is None:
        cache_db = InMemoryCacheDB()
    cache = Cache(
        db=cache_db,
        ttl_days=config.v3_pipeline.cache_ttl_days,
    )

    # Orchestrator
    orchestrator = V3Orchestrator(
        planner=planner,
        extractor=extractor,
        element_filter=element_filter,
        actor=actor,
        executor=executor,
        cache=cache,
        verifier=verifier,
    )

    # Retry handler
    retry_handler = RetryHandler(vlm=vlm_adapter)

    # Skill synthesizer (uses Pro for code generation)
    skill_synthesizer = SkillSynthesizer(llm=pro_text_adapter)

    # Canvas components
    canvas_detector = CanvasDetector()
    if config.canvas.canvas_threshold != 5:
        canvas_detector.CANVAS_THRESHOLD = config.canvas.canvas_threshold

    local_detector = LocalDetector(backend=None)
    canvas_executor = CanvasExecutor(
        local_detector=local_detector,
        vlm=vlm_adapter,
    )

    logger.info(
        "V3 pipeline created (flash=%s, pro=%s, cache_ttl=%d)",
        config.llm.flash_model,
        config.llm.pro_model,
        config.v3_pipeline.cache_ttl_days,
    )

    return V3Pipeline(
        orchestrator=orchestrator,
        canvas_detector=canvas_detector,
        canvas_executor=canvas_executor,
        retry_handler=retry_handler,
        skill_synthesizer=skill_synthesizer,
        config=config,
    )
