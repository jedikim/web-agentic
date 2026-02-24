"""Tests for src.core.navigation — rate limiting, robots.txt, homepage warming."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import NavigationConfig
from src.core.navigation import NavigationBlockedError, NavigationGuard


def _make_guard(**overrides: object) -> NavigationGuard:
    config_kwargs = {
        "homepage_first": True,
        "respect_robots_txt": False,  # disabled by default in tests
        "rate_limit_ms": 100,
        "referrer_chain": True,
    }
    config_kwargs.update(overrides)
    config = NavigationConfig(**config_kwargs)  # type: ignore[arg-type]
    return NavigationGuard(config)


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_first_access_no_delay(self) -> None:
        guard = _make_guard(respect_robots_txt=False, homepage_first=False)
        page = MagicMock()

        start = time.monotonic()
        await guard.pre_navigate("https://example.com/page", page)
        elapsed = time.monotonic() - start

        assert elapsed < 0.5  # No significant delay

    @pytest.mark.asyncio
    async def test_same_domain_delayed(self) -> None:
        guard = _make_guard(
            respect_robots_txt=False,
            homepage_first=False,
            rate_limit_ms=200,
        )
        page = MagicMock()

        await guard.pre_navigate("https://example.com/a", page)

        start = time.monotonic()
        await guard.pre_navigate("https://example.com/b", page)
        elapsed_ms = (time.monotonic() - start) * 1000

        # Should have waited ~200ms
        assert elapsed_ms >= 100  # At least some delay

    @pytest.mark.asyncio
    async def test_different_domain_no_delay(self) -> None:
        guard = _make_guard(
            respect_robots_txt=False,
            homepage_first=False,
            rate_limit_ms=500,
        )
        page = MagicMock()

        await guard.pre_navigate("https://a.com/page", page)

        start = time.monotonic()
        await guard.pre_navigate("https://b.com/page", page)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 200  # No delay for different domain


class TestRobotsTxt:
    @pytest.mark.asyncio
    async def test_allowed_url_passes(self) -> None:
        guard = _make_guard(
            respect_robots_txt=True,
            homepage_first=False,
            rate_limit_ms=0,
        )

        # Mock the robots fetcher to return a permissive parser
        from urllib.robotparser import RobotFileParser
        rp = RobotFileParser()
        rp.parse(["User-agent: *", "Allow: /"])
        guard._robots_cache["example.com"] = rp

        page = MagicMock()
        # Should not raise
        await guard.pre_navigate("https://example.com/allowed", page)

    @pytest.mark.asyncio
    async def test_blocked_url_raises(self) -> None:
        guard = _make_guard(
            respect_robots_txt=True,
            homepage_first=False,
            rate_limit_ms=0,
        )

        from urllib.robotparser import RobotFileParser
        rp = RobotFileParser()
        rp.parse(["User-agent: *", "Disallow: /private/"])
        guard._robots_cache["example.com"] = rp

        page = MagicMock()
        with pytest.raises(NavigationBlockedError):
            await guard.pre_navigate("https://example.com/private/data", page)

    @pytest.mark.asyncio
    async def test_robots_cache_reused(self) -> None:
        guard = _make_guard(
            respect_robots_txt=True,
            homepage_first=False,
            rate_limit_ms=0,
        )

        from urllib.robotparser import RobotFileParser
        rp = RobotFileParser()
        rp.parse(["User-agent: *", "Allow: /"])
        guard._robots_cache["example.com"] = rp

        page = MagicMock()
        await guard.pre_navigate("https://example.com/a", page)
        await guard.pre_navigate("https://example.com/b", page)

        # Same parser should be reused (no re-fetch)
        assert guard._robots_cache["example.com"] is rp


class TestHomepageWarming:
    @pytest.mark.asyncio
    async def test_deep_url_visits_root_first(self) -> None:
        guard = _make_guard(
            homepage_first=True,
            respect_robots_txt=False,
            rate_limit_ms=0,
        )

        page = MagicMock()
        page.goto = AsyncMock()

        await guard.pre_navigate(
            "https://shop.example.com/products/laptop", page,
        )

        # Root URL should have been visited
        calls = page.goto.call_args_list
        assert len(calls) == 1
        assert calls[0][0][0] == "https://shop.example.com/"

    @pytest.mark.asyncio
    async def test_root_url_skips_warming(self) -> None:
        guard = _make_guard(
            homepage_first=True,
            respect_robots_txt=False,
            rate_limit_ms=0,
        )

        page = MagicMock()
        page.goto = AsyncMock()

        await guard.pre_navigate("https://example.com/", page)

        page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_shallow_url_skips_warming(self) -> None:
        guard = _make_guard(
            homepage_first=True,
            respect_robots_txt=False,
            rate_limit_ms=0,
        )

        page = MagicMock()
        page.goto = AsyncMock()

        await guard.pre_navigate("https://example.com/about", page)

        page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_second_visit_skips_warming(self) -> None:
        guard = _make_guard(
            homepage_first=True,
            respect_robots_txt=False,
            rate_limit_ms=0,
        )

        page = MagicMock()
        page.goto = AsyncMock()

        await guard.pre_navigate(
            "https://shop.example.com/products/laptop", page,
        )
        page.goto.reset_mock()

        await guard.pre_navigate(
            "https://shop.example.com/products/phone", page,
        )

        # No warming on second visit
        page.goto.assert_not_called()
