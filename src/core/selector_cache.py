"""Selector Cache — thin wrapper over PatternDB providing cache semantics.

Provides a simple lookup/save/invalidate interface for the LLM-First
orchestrator.  Successful LLM selector choices are cached so that repeated
executions skip the LLM call entirely.

Usage::

    cache = SelectorCache("data/patterns.db")
    await cache.init()
    hit = await cache.lookup("검색", "shopping.naver.com")
    if hit is None:
        # LLM selects element ...
        await cache.save("검색", "shopping.naver.com", "#search-input", "type")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.learning.pattern_db import PatternDB

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheHit:
    """A cached selector lookup result.

    Attributes:
        selector: CSS selector string.
        method: Interaction method (click, type, etc.).
        confidence: Success ratio (0.0 - 1.0).
    """

    selector: str
    method: str
    confidence: float


class SelectorCache:
    """Thin wrapper over PatternDB providing cache semantics.

    Args:
        db_path: SQLite database path.
        min_success: Minimum success count to trust a cached entry.
    """

    def __init__(
        self, db_path: str | Path = "data/patterns.db", min_success: int = 1
    ) -> None:
        self._db = PatternDB(db_path)
        self._min_success = min_success

    async def init(self) -> None:
        """Initialize the underlying database."""
        await self._db.init_db()

    async def lookup(self, intent: str, site: str) -> CacheHit | None:
        """Look up a cached selector.

        Returns ``None`` if no good entry exists.  Entries with more failures
        than successes or below *min_success* threshold are not trusted.

        Args:
            intent: Natural-language intent string.
            site: Hostname or glob pattern.

        Returns:
            A ``CacheHit`` with the cached selector, or ``None``.
        """
        pattern = await self._db.get_pattern(intent, site)
        if pattern is None:
            return None
        if pattern.fail_count >= pattern.success_count:
            return None
        if pattern.success_count < self._min_success:
            return None
        ratio = pattern.success_count / max(
            pattern.success_count + pattern.fail_count, 1
        )
        return CacheHit(
            selector=pattern.selector, method=pattern.method, confidence=ratio
        )

    async def save(
        self, intent: str, site: str, selector: str, method: str
    ) -> None:
        """Record a successful selector usage.

        Args:
            intent: Natural-language intent string.
            site: Hostname or glob pattern.
            selector: CSS selector used.
            method: Interaction method (click, type, etc.).
        """
        await self._db.record_success(intent, site, selector, method)

    async def invalidate(self, intent: str, site: str) -> None:
        """Record a failure, reducing trust in cached entries.

        Args:
            intent: Natural-language intent string.
            site: Hostname or glob pattern.
        """
        pattern = await self._db.get_pattern(intent, site)
        if pattern is not None:
            await self._db.record_failure(
                intent, site, pattern.selector, pattern.method
            )
