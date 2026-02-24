#!/usr/bin/env python3
"""Run the LLM-First orchestrator on a real site with headful browser.

Usage:
    python scripts/run_live.py \\
        --intent "네이버 쇼핑에서 노트북 검색해서 인기순 정렬" \\
        --url https://shopping.naver.com

    python scripts/run_live.py \\
        --intent "구글에서 python 검색" \\
        --url https://www.google.com
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai.llm_planner import create_llm_planner  # noqa: E402
from src.core.executor import create_executor  # noqa: E402
from src.core.extractor import DOMExtractor  # noqa: E402
from src.core.llm_orchestrator import LLMFirstOrchestrator  # noqa: E402
from src.core.selector_cache import SelectorCache  # noqa: E402
from src.core.verifier import Verifier  # noqa: E402


async def main(intent: str, url: str | None, headless: bool) -> None:
    """Run the LLM-First orchestrator on a real site."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("run_live")

    # Create modules
    log.info("Launching browser (headless=%s)...", headless)
    executor = await create_executor(headless=headless)
    extractor = DOMExtractor()
    planner = create_llm_planner()
    verifier = Verifier()
    cache = SelectorCache("data/live_cache.db")
    await cache.init()

    screenshot_dir = Path("data/screenshots")

    orch = LLMFirstOrchestrator(
        executor=executor,
        extractor=extractor,
        planner=planner,
        verifier=verifier,
        cache=cache,
        screenshot_dir=screenshot_dir,
    )

    # Navigate to starting URL if provided
    if url:
        log.info("Navigating to: %s", url)
        await executor.goto(url)
        page = await executor.get_page()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

    try:
        result = await orch.run(intent)

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
            "Screenshots: %d saved to %s", len(result.screenshots), screenshot_dir
        )
        log.info(
            "Tokens: %d | Cost: $%.4f", result.total_tokens, result.total_cost_usd
        )
        log.info("=" * 60)

        # Keep browser open for inspection
        if not headless:
            log.info("Browser open for inspection. Press Ctrl+C to close.")
            try:
                await asyncio.sleep(30)
            except KeyboardInterrupt:
                pass
    finally:
        await executor.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-First live site runner")
    parser.add_argument(
        "--intent", required=True, help="User intent in natural language"
    )
    parser.add_argument("--url", default=None, help="Starting URL (optional)")
    parser.add_argument(
        "--headless", action="store_true", default=False, help="Run headless"
    )
    args = parser.parse_args()

    asyncio.run(main(args.intent, args.url, args.headless))
