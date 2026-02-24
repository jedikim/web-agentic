"""High-level SDK facade for the adaptive web automation engine.

Provides a simple ``async with WebAgent() as agent`` interface
that wires together all internal modules (Executor, Extractor,
LLM Planner, Verifier, SelectorCache, Orchestrator).

Example::

    async with WebAgent(headless=True) as agent:
        await agent.goto("https://example.com")
        result = await agent.run("Click the 'More information' link")
        print(result.success)
"""
from __future__ import annotations

import logging

from src.ai.llm_planner import create_llm_planner
from src.ai.llm_provider import ILLMProvider
from src.core.adaptive_controller import AdaptiveController
from src.core.config import StealthConfig
from src.core.executor import Executor, create_executor
from src.core.extractor import DOMExtractor
from src.core.fallback_router import FallbackRouter
from src.core.llm_orchestrator import LLMFirstOrchestrator, RunResult
from src.core.selector_cache import SelectorCache
from src.core.verifier import Verifier
from src.learning.replay_store import ReplayStore
from src.vision.batch_vision_pipeline import BatchVisionPipeline
from src.vision.coord_mapper import CoordMapper
from src.vision.image_batcher import ImageBatcher
from src.vision.vlm_client import VLMClient
from src.vision.yolo_detector import YOLODetector

logger = logging.getLogger(__name__)


class WebAgent:
    """High-level SDK for adaptive web automation.

    Wraps the LLM-First orchestrator pipeline behind a minimal
    async context-manager interface.

    Args:
        headless: Run browser in headless mode.
        max_cost_per_run: Maximum USD cost allowed per ``run()`` call.
        max_total_cost: Maximum cumulative USD cost across all runs.
        cache_db_path: Path to the SQLite selector cache database.
        screenshot_dir: Directory for step screenshots.
        llm_provider: Optional LLM provider for multi-provider support.
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        max_cost_per_run: float = 0.05,
        max_total_cost: float = 0.50,
        cache_db_path: str = "data/patterns.db",
        screenshot_dir: str = "data/screenshots",
        enable_vision: bool = False,
        stealth_level: str = "standard",
        enable_adaptive: bool = False,
        replay_db_path: str = "data/replay.db",
        llm_provider: ILLMProvider | None = None,
    ) -> None:
        self._headless = headless
        self._max_cost_per_run = max_cost_per_run
        self._max_total_cost = max_total_cost
        self._cache_db_path = cache_db_path
        self._screenshot_dir = screenshot_dir
        self._enable_vision = enable_vision
        self._stealth_level = stealth_level
        self._enable_adaptive = enable_adaptive
        self._replay_db_path = replay_db_path
        self._llm_provider = llm_provider

        self._executor: Executor | None = None
        self._cache: SelectorCache | None = None
        self._replay_store: ReplayStore | None = None
        self._orchestrator: LLMFirstOrchestrator | None = None
        self._total_cost: float = 0.0
        self._started: bool = False
        self._owns_executor: bool = False

    async def start(self) -> WebAgent:
        """Initialize browser, cache, and orchestrator.

        Returns:
            ``self`` for fluent chaining.
        """
        if self._started:
            return self

        if self._executor is None:
            stealth = StealthConfig(level=self._stealth_level)
            self._executor = await create_executor(
                headless=self._headless, stealth=stealth,
            )
            self._owns_executor = True

        self._cache = SelectorCache(db_path=self._cache_db_path)
        await self._cache.init()

        extractor = DOMExtractor()
        planner = create_llm_planner(provider=self._llm_provider)
        verifier = Verifier()

        # Optional vision components.
        batch_vision: BatchVisionPipeline | None = None
        yolo_detector: YOLODetector | None = None
        vlm_client: VLMClient | None = None

        if self._enable_vision:
            yolo_detector = YOLODetector()
            vlm_client = VLMClient()
            batcher = ImageBatcher()
            coord_mapper = CoordMapper()
            batch_vision = BatchVisionPipeline(
                batcher=batcher,
                yolo=yolo_detector,
                vlm=vlm_client,
                coord_mapper=coord_mapper,
            )

        # Optional adaptive controller
        adaptive_controller: AdaptiveController | None = None
        if self._enable_adaptive:
            self._replay_store = ReplayStore(db_path=self._replay_db_path)
            await self._replay_store.init()
            adaptive_controller = AdaptiveController(self._replay_store)

        self._orchestrator = LLMFirstOrchestrator(
            executor=self._executor,
            extractor=extractor,
            planner=planner,
            verifier=verifier,
            cache=self._cache,
            screenshot_dir=self._screenshot_dir,
            max_cost_per_run=self._max_cost_per_run,
            yolo_detector=yolo_detector,
            vlm_client=vlm_client,
            batch_vision=batch_vision,
            fallback_router=FallbackRouter(),
            adaptive_controller=adaptive_controller,
        )

        self._started = True
        logger.info("WebAgent started (headless=%s)", self._headless)
        return self

    async def goto(self, url: str) -> None:
        """Navigate to a URL.

        Args:
            url: The URL to navigate to.

        Raises:
            RuntimeError: If ``start()`` has not been called.
        """
        self._ensure_started()
        assert self._executor is not None
        await self._executor.goto(url)

    async def run(self, intent: str) -> RunResult:
        """Execute a natural-language intent.

        Args:
            intent: What to do on the current page.

        Returns:
            ``RunResult`` with success flag, step results, and cost.

        Raises:
            RuntimeError: If ``start()`` has not been called or
                total cost exceeds ``max_total_cost``.
        """
        self._ensure_started()
        assert self._orchestrator is not None

        if self._total_cost >= self._max_total_cost:
            raise RuntimeError(
                f"Total cost ${self._total_cost:.4f} already exceeds "
                f"limit ${self._max_total_cost:.4f}"
            )

        result = await self._orchestrator.run(intent)
        self._total_cost += result.total_cost_usd

        if self._total_cost > self._max_total_cost:
            logger.warning(
                "Total cost $%.4f exceeds limit $%.4f",
                self._total_cost,
                self._max_total_cost,
            )

        return result

    async def screenshot(self) -> bytes:
        """Take a screenshot of the current page.

        Returns:
            PNG image data as bytes.

        Raises:
            RuntimeError: If ``start()`` has not been called.
        """
        self._ensure_started()
        assert self._executor is not None
        return await self._executor.screenshot()

    async def close(self) -> None:
        """Release all resources (browser, cache).

        Safe to call multiple times.
        """
        if self._cache is not None:
            await self._cache._db.close()
            self._cache = None

        if self._executor is not None and self._owns_executor:
            await self._executor.close()
            self._executor = None

        self._orchestrator = None
        self._started = False
        logger.info("WebAgent closed")

    @classmethod
    async def from_executor(cls, executor: Executor, **kwargs: object) -> WebAgent:
        """Create a WebAgent using an existing Executor.

        Useful when the SessionManager provides a pool-acquired executor.

        Args:
            executor: An already-created Executor instance.
            **kwargs: Forwarded to ``WebAgent.__init__`` (except ``headless``).

        Returns:
            A started ``WebAgent`` bound to the given executor.
        """
        agent = cls(**kwargs)  # type: ignore[arg-type]
        agent._executor = executor
        agent._owns_executor = False
        await agent.start()
        return agent

    @property
    def total_cost(self) -> float:
        """Cumulative cost across all ``run()`` calls."""
        return self._total_cost

    # ── Context manager ─────────────────────────────────

    async def __aenter__(self) -> WebAgent:
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.close()

    # ── Private ─────────────────────────────────────────

    def _ensure_started(self) -> None:
        """Raise if the agent has not been started."""
        if not self._started:
            raise RuntimeError(
                "WebAgent not started. Call start() or use 'async with WebAgent()'"
            )
