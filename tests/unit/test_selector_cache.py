"""Tests for SelectorCache — thin cache wrapper over PatternDB.

Covers lookup miss, save-and-lookup round-trip, and invalidation
(failure recording that drops confidence below trust threshold).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from src.core.selector_cache import CacheHit, SelectorCache

# -- Fixtures ---------------------------------------------------------------


@pytest_asyncio.fixture
async def cache(tmp_path: Path) -> SelectorCache:
    """Create a fresh SelectorCache backed by a temp SQLite file."""
    c = SelectorCache(db_path=str(tmp_path / "test_cache.db"))
    await c.init()
    return c


# -- Tests ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_miss(cache: SelectorCache) -> None:
    """Lookup on an empty cache should return None."""
    result = await cache.lookup("검색", "shopping.naver.com")
    assert result is None


@pytest.mark.asyncio
async def test_save_and_lookup(cache: SelectorCache) -> None:
    """After saving a selector, lookup should return a CacheHit."""
    await cache.save("검색", "shopping.naver.com", "#search-input", "type")
    hit = await cache.lookup("검색", "shopping.naver.com")
    assert hit is not None
    assert isinstance(hit, CacheHit)
    assert hit.selector == "#search-input"
    assert hit.method == "type"


@pytest.mark.asyncio
async def test_invalidate(cache: SelectorCache) -> None:
    """After invalidation (1 success + 1 failure), lookup should return None."""
    await cache.save("검색", "shopping.naver.com", "#search-input", "type")
    await cache.invalidate("검색", "shopping.naver.com")
    result = await cache.lookup("검색", "shopping.naver.com")
    # 1 success, 1 failure => fail_count >= success_count => not trusted
    assert result is None
