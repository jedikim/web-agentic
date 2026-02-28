#!/usr/bin/env python3
"""Run the v3 pipeline on a real site.

Usage:
    python scripts/run_live.py \
        --intent "네이버 쇼핑에서 노트북 검색해서 인기순 정렬" \
        --url https://shopping.naver.com

    python scripts/run_live.py \
        --intent "구글에서 python 검색" \
        --url https://www.google.com

    # Legacy orchestrator:
    python scripts/run_live.py --intent "..." --legacy
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.browser import Browser as V3Browser  # noqa: E402
from src.core.config import load_config  # noqa: E402
from src.core.executor import create_executor  # noqa: E402
from src.core.v3_factory import create_v3_pipeline  # noqa: E402
from src.observability.tracing import flush as flush_tracing  # noqa: E402


async def main(intent: str, url: str | None, headless: bool, legacy: bool) -> None:
    """Run the v3 pipeline (or legacy orchestrator) on a real site."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("run_live")

    config = load_config()

    log.info("Launching browser (headless=%s)...", headless)
    executor = await create_executor(headless=headless)

    # Navigate to starting URL if provided
    if url:
        log.info("Navigating to: %s", url)
        await executor.goto(url)
        page = await executor.get_page()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

    try:
        if legacy:
            result = await _run_legacy(executor, intent, config, log)
        else:
            result = await _run_v3(executor, intent, config, log)

        log.info("=" * 60)
        log.info("RESULT: %s", "SUCCESS" if result.success else "FAILED")
        log.info("Steps: %d total", len(result.step_results))
        for i, sr in enumerate(result.step_results):
            status = "OK" if sr.success else "FAIL"
            log.info(
                "  [%d] %s method=%s latency=%.0fms",
                i + 1,
                status,
                sr.method,
                sr.latency_ms,
            )
        log.info(
            "Tokens: %d | Cost: $%.4f", result.total_tokens, result.total_cost_usd,
        )
        if hasattr(result, "result_summary") and result.result_summary:
            log.info("Summary: %s", result.result_summary)
        log.info("=" * 60)

        # Keep browser open for inspection
        if not headless:
            log.info("Browser open for inspection. Press Ctrl+C to close.")
            with contextlib.suppress(KeyboardInterrupt):
                await asyncio.sleep(30)
    finally:
        flush_tracing()
        await executor.close()


async def _run_v3(executor, intent, config, log):
    """Run via v3 pipeline."""
    log.info("Pipeline: v3")
    pipeline = create_v3_pipeline(config=config)

    page = await executor.get_page()
    browser = V3Browser(page)

    return await pipeline.orchestrator.run_with_result(intent, browser)


async def _run_legacy(executor, intent, config, log):
    """Run via legacy LLMFirstOrchestrator."""
    from src.ai.candidate_filter import create_candidate_filter
    from src.ai.llm_planner import create_llm_planner
    from src.core.extractor import DOMExtractor
    from src.core.fallback_router import FallbackRouter
    from src.core.llm_orchestrator import LLMFirstOrchestrator
    from src.core.selector_cache import SelectorCache
    from src.core.verifier import Verifier

    log.info("Pipeline: legacy (LLMFirstOrchestrator)")

    extractor = DOMExtractor()
    planner = create_llm_planner()
    verifier = Verifier()
    cache = SelectorCache("data/live_cache.db")
    await cache.init()

    candidate_filter = create_candidate_filter(config.candidate_filter)

    orch = LLMFirstOrchestrator(
        executor=executor,
        extractor=extractor,
        planner=planner,
        verifier=verifier,
        cache=cache,
        screenshot_dir=Path("data/screenshots"),
        fallback_router=FallbackRouter(),
        candidate_filter=candidate_filter,
    )

    return await orch.run(intent)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="v3 live site runner")
    parser.add_argument(
        "--intent", required=True, help="User intent in natural language",
    )
    parser.add_argument("--url", default=None, help="Starting URL (optional)")
    parser.add_argument(
        "--headless", action="store_true", default=False, help="Run headless",
    )
    parser.add_argument(
        "--legacy", action="store_true", default=False,
        help="Use legacy LLMFirstOrchestrator instead of v3 pipeline",
    )
    args = parser.parse_args()

    asyncio.run(main(args.intent, args.url, args.headless, args.legacy))
