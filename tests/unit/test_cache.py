"""Tests for Cache — selector cache with lookup/store/cleanup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.core.cache import Cache, InMemoryCacheDB
from src.core.types import CacheEntry


@pytest.fixture
def cache() -> Cache:
    return Cache(db=InMemoryCacheDB(), ttl_days=30)


def _entry(
    domain: str = "example.com",
    url_pattern: str = "https://example.com/search",
    task_type: str = "검색창 클릭",
    selector: str | None = "#search-input",
    action_type: str = "click",
) -> CacheEntry:
    return CacheEntry(
        domain=domain,
        url_pattern=url_pattern,
        task_type=task_type,
        selector=selector,
        action_type=action_type,
        keyword_weights={"검색": 0.9},
        viewport_xy=(0.5, 0.05),
        expected_result="DOM 존재: input:focus",
        success_count=1,
    )


class TestLookup:
    async def test_empty_cache_returns_none(self, cache: Cache) -> None:
        result = await cache.lookup("example.com", "https://example.com", "task")
        assert result is None

    async def test_lookup_after_store(self, cache: Cache) -> None:
        entry = _entry()
        await cache.store(entry)

        result = await cache.lookup("example.com", "https://example.com/search", "검색창 클릭")
        assert result is not None
        assert result.selector == "#search-input"
        assert result.keyword_weights == {"검색": 0.9}
        assert result.viewport_xy == (0.5, 0.05)

    async def test_lookup_wrong_domain_returns_none(self, cache: Cache) -> None:
        await cache.store(_entry())
        result = await cache.lookup("other.com", "https://example.com/search", "검색창 클릭")
        assert result is None

    async def test_lookup_wrong_task_returns_none(self, cache: Cache) -> None:
        await cache.store(_entry())
        result = await cache.lookup("example.com", "https://example.com/search", "다른 태스크")
        assert result is None


class TestStore:
    async def test_store_and_retrieve_with_value(self, cache: Cache) -> None:
        entry = CacheEntry(
            domain="shop.com",
            url_pattern="https://shop.com/search",
            task_type="검색어 입력",
            selector="input#q",
            action_type="type",
            value="등산복",
            keyword_weights={"검색": 0.9, "등산복": 1.0},
            viewport_xy=(0.5, 0.1),
        )
        await cache.store(entry)

        result = await cache.lookup("shop.com", "https://shop.com/search", "검색어 입력")
        assert result is not None
        assert result.action_type == "type"
        assert result.value == "등산복"

    async def test_store_without_selector(self, cache: Cache) -> None:
        entry = _entry(selector=None)
        await cache.store(entry)

        result = await cache.lookup("example.com", "https://example.com/search", "검색창 클릭")
        assert result is not None
        assert result.selector is None
        assert result.viewport_xy == (0.5, 0.05)

    async def test_store_overwrites(self, cache: Cache) -> None:
        await cache.store(_entry(selector="#old"))
        await cache.store(_entry(selector="#new"))

        result = await cache.lookup("example.com", "https://example.com/search", "검색창 클릭")
        assert result is not None
        assert result.selector == "#new"


class TestRecordSuccess:
    async def test_increments_count(self, cache: Cache) -> None:
        entry = _entry()
        await cache.store(entry)
        await cache.record_success(entry)

        result = await cache.lookup("example.com", "https://example.com/search", "검색창 클릭")
        assert result is not None
        assert result.success_count == 2  # 1 initial + 1 recorded
        assert result.last_success is not None


class TestCleanupExpired:
    async def test_removes_expired(self) -> None:
        db = InMemoryCacheDB()
        cache = Cache(db=db, ttl_days=7)

        entry = _entry()
        await cache.store(entry)

        # Manually set last_success to 10 days ago
        key = "example.com|https://example.com/search|검색창 클릭"
        old_time = (datetime.now(tz=UTC) - timedelta(days=10)).isoformat()
        db._store[key]["last_success"] = old_time

        removed = await cache.cleanup_expired()
        assert removed == 1

    async def test_keeps_recent(self) -> None:
        db = InMemoryCacheDB()
        cache = Cache(db=db, ttl_days=7)

        entry = _entry()
        await cache.store(entry)
        await cache.record_success(entry)  # Sets last_success to now

        removed = await cache.cleanup_expired()
        assert removed == 0


class TestInMemoryCacheDB:
    async def test_get_nonexistent(self) -> None:
        db = InMemoryCacheDB()
        result = await db.get("x", "y", "z")
        assert result is None

    async def test_put_and_get(self) -> None:
        db = InMemoryCacheDB()
        await db.put({"domain": "d", "url_pattern": "u", "task_type": "t", "selector": "#s"})
        result = await db.get("d", "u", "t")
        assert result is not None
        assert result["selector"] == "#s"
