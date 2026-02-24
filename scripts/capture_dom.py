#!/usr/bin/env python3
"""Capture real-site DOM for offline analysis.

Usage:
    python scripts/capture_dom.py https://example.com --output data/dom_captures/example.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from src.core.executor import create_executor  # noqa: E402
from src.core.extractor import DOMExtractor  # noqa: E402


async def capture(url: str, output: Path, headless: bool = True) -> None:
    """Capture DOM elements from a URL and save to JSON.

    Args:
        url: The URL to capture.
        output: Path to write the JSON output.
        headless: Whether to run the browser in headless mode.
    """
    executor = await create_executor(headless=headless)
    try:
        await executor.goto(url)
        page = await executor.get_page()
        extractor = DOMExtractor()

        clickables = await extractor.extract_clickables(page)
        inputs = await extractor.extract_inputs(page)
        state = await extractor.extract_state(page)

        data = {
            "url": url,
            "title": state.title,
            "clickables": [
                {"eid": e.eid, "type": e.type, "text": e.text, "role": e.role}
                for e in clickables
            ],
            "inputs": [
                {"eid": e.eid, "type": e.type, "text": e.text}
                for e in inputs
            ],
            "state": {
                "url": state.url,
                "title": state.title,
                "element_count": state.element_count,
            },
        }

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"Captured DOM to {output}")
    finally:
        await executor.close()


def main() -> None:
    """Entry point for DOM capture CLI."""
    parser = argparse.ArgumentParser(description="Capture real-site DOM")
    parser.add_argument("url", help="URL to capture")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("data/dom_captures/capture.json"),
    )
    parser.add_argument("--no-headless", action="store_true")
    args = parser.parse_args()
    asyncio.run(capture(args.url, args.output, headless=not args.no_headless))


if __name__ == "__main__":
    main()
