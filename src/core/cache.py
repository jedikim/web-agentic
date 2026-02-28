"""Cache — SQLite-based selector cache for repeat runs.

Stores successful action results (selector + viewport_xy + keyword_weights)
keyed by (domain, url_pattern, task_type). On repeat runs, the cached path
skips all LLM calls and directly executes, then verifies.

Cache entries auto-expire after TTL days of no successful use.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Protocol

from src.core.types import CacheEntry

logger = logging.getLogger(__name__)

_DEFAULT_TTL_DAYS = 30


class ICacheDB(Protocol):
    """Async database interface for cache persistence."""

    async def get(self, domain: str, url_pattern: str, task_type: str) -> dict | None: ...  # type: ignore[type-arg]
    async def put(self, entry: dict) -> None: ...  # type: ignore[type-arg]
    async def update_success(self, domain: str, url_pattern: str, task_type: str) -> None: ...
    async def delete_expired(self, ttl_days: int) -> int: ...


class InMemoryCacheDB:
    """In-memory cache DB for testing and simple use cases."""

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}  # type: ignore[type-arg]

    def _key(self, domain: str, url_pattern: str, task_type: str) -> str:
        return f"{domain}|{url_pattern}|{task_type}"

    async def get(self, domain: str, url_pattern: str, task_type: str) -> dict | None:  # type: ignore[type-arg]
        return self._store.get(self._key(domain, url_pattern, task_type))

    async def put(self, entry: dict) -> None:  # type: ignore[type-arg]
        key = self._key(entry["domain"], entry["url_pattern"], entry["task_type"])
        self._store[key] = entry

    async def update_success(self, domain: str, url_pattern: str, task_type: str) -> None:
        key = self._key(domain, url_pattern, task_type)
        if key in self._store:
            self._store[key]["success_count"] = self._store[key].get("success_count", 0) + 1
            self._store[key]["last_success"] = datetime.now(tz=UTC).isoformat()

    async def delete_expired(self, ttl_days: int) -> int:
        now = datetime.now(tz=UTC)
        expired_keys = []
        for key, entry in self._store.items():
            last = entry.get("last_success")
            if last:
                last_dt = datetime.fromisoformat(last)
                if (now - last_dt).days > ttl_days:
                    expired_keys.append(key)
        for key in expired_keys:
            del self._store[key]
        return len(expired_keys)


class Cache:
    """Selector cache with lookup, store, and success tracking.

    Usage:
        cache = Cache(db=InMemoryCacheDB())
        entry = await cache.lookup("example.com", "https://example.com/search", "검색창 클릭")
        if entry:
            # Use cached selector/viewport
        else:
            # Full pipeline
            await cache.store(new_entry)
    """

    def __init__(self, db: ICacheDB, ttl_days: int = _DEFAULT_TTL_DAYS) -> None:
        self._db = db
        self._ttl_days = ttl_days

    async def lookup(
        self, domain: str, url: str, task_description: str,
    ) -> CacheEntry | None:
        """Look up a cached entry by domain, URL, and task.

        Args:
            domain: Website domain.
            url: Current page URL.
            task_description: Task description to match.

        Returns:
            CacheEntry if found, None otherwise.
        """
        data = await self._db.get(domain, url, task_description)
        if not data:
            return None

        return self._dict_to_entry(data)

    async def store(self, entry: CacheEntry) -> None:
        """Store a new cache entry after successful execution.

        Args:
            entry: CacheEntry to persist.
        """
        data = self._entry_to_dict(entry)
        await self._db.put(data)

    async def record_success(self, entry: CacheEntry) -> None:
        """Increment success count and update timestamp.

        Args:
            entry: The entry that succeeded.
        """
        await self._db.update_success(
            entry.domain, entry.url_pattern, entry.task_type,
        )

    async def cleanup_expired(self) -> int:
        """Remove entries that haven't been used within TTL.

        Returns:
            Number of entries removed.
        """
        return await self._db.delete_expired(self._ttl_days)

    def _entry_to_dict(self, entry: CacheEntry) -> dict:  # type: ignore[type-arg]
        return {
            "domain": entry.domain,
            "url_pattern": entry.url_pattern,
            "task_type": entry.task_type,
            "selector": entry.selector,
            "action_type": entry.action_type,
            "value": entry.value,
            "keyword_weights": json.dumps(entry.keyword_weights),
            "viewport_xy": json.dumps(entry.viewport_xy) if entry.viewport_xy else None,
            "viewport_bbox": json.dumps(entry.viewport_bbox) if entry.viewport_bbox else None,
            "expected_result": entry.expected_result,
            "post_screenshot_path": entry.post_screenshot_path,
            "post_screenshot_phash": entry.post_screenshot_phash,
            "success_count": entry.success_count,
            "last_success": entry.last_success,
        }

    def _dict_to_entry(self, data: dict) -> CacheEntry:  # type: ignore[type-arg]
        kw = data.get("keyword_weights", "{}")
        if isinstance(kw, str):
            kw = json.loads(kw)

        xy = data.get("viewport_xy")
        if isinstance(xy, str):
            xy = tuple(json.loads(xy))
        elif isinstance(xy, list):
            xy = tuple(xy)

        bbox = data.get("viewport_bbox")
        if isinstance(bbox, str):
            bbox = tuple(json.loads(bbox))
        elif isinstance(bbox, list):
            bbox = tuple(bbox)

        return CacheEntry(
            domain=data["domain"],
            url_pattern=data["url_pattern"],
            task_type=data["task_type"],
            selector=data.get("selector"),
            action_type=data.get("action_type", "click"),
            value=data.get("value"),
            keyword_weights=kw,
            viewport_xy=xy,  # type: ignore[arg-type]
            viewport_bbox=bbox,  # type: ignore[arg-type]
            expected_result=data.get("expected_result"),
            post_screenshot_path=data.get("post_screenshot_path", ""),
            post_screenshot_phash=data.get("post_screenshot_phash", ""),
            success_count=data.get("success_count", 0),
            last_success=data.get("last_success"),
        )
